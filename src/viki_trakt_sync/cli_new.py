"""Simplified CLI - new clean command structure.

Commands:
  sync                    # Main workflow: fetch → match → sync
  watch                   # View watch status from cache
  status                  # System health check
  match                   # View/manage matches

This is the new CLI using the refactored architecture.
Import this in cli.py to add the new commands.
"""

import logging
import sys
from typing import Optional

import click

from .config import get_config
from .repository import Repository
from .queries import WatchQuery, StatusQuery, MatchQuery


# ============================================================
# REFRESH Command
# ============================================================

@click.command()
@click.option("--force", is_flag=True, help="Force refresh all shows")
def refresh(force: bool):
    """Fetch watch data from Viki and update local cache.
    
    This is useful during testing to update your local Viki data
    without syncing to Trakt. Checks billboard hash and only refreshes
    episodes for shows that changed.
    
    Use --force to refresh all shows regardless of change.
    """
    try:
        config = get_config()
        viki_client = config.get_viki_client()
    except Exception as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        click.echo("Run 'viki-trakt-sync config' to check your settings", err=True)
        sys.exit(1)
    
    from .adapters import VikiAdapter
    from datetime import datetime, timezone
    
    viki = VikiAdapter(viki_client)
    repo = Repository()
    
    click.echo("🔄 Fetching Viki billboard...\n")
    
    try:
        billboard = viki.get_billboard()
        click.echo(f"Found {len(billboard)} shows\n")
    except Exception as e:
        click.echo(f"✗ Failed to fetch billboard: {e}", err=True)
        sys.exit(1)
    
    shows_refreshed = 0
    episodes_fetched = 0
    
    for item in billboard:
        show = repo.upsert_show(
            viki_id=item.viki_id,
            title=item.title,
            type_=item.type,
            origin_country=item.origin_country,
            origin_language=item.origin_language,
        )
        
        # Check if needs refresh
        if force:
            needs_refresh = True
        else:
            new_hash = repo.compute_billboard_hash(
                item.last_video_id or "",
                item.last_watched_at or "",
            )
            needs_refresh = repo.needs_refresh(show, new_hash)
            if needs_refresh:
                repo.update_billboard_hash(item.viki_id, new_hash)
        
        if needs_refresh:
            try:
                episodes = viki.get_episodes(item.viki_id)
                for ep in episodes:
                    repo.upsert_episode(
                        viki_video_id=ep.viki_video_id,
                        viki_id=item.viki_id,
                        episode_number=ep.episode_number,
                        duration=ep.duration,
                        credits_marker=ep.credits_marker,
                    )
                shows_refreshed += 1
                episodes_fetched += len(episodes)
                click.echo(f"  ✓ {item.title}: {len(episodes)} episodes")
            except Exception as e:
                click.echo(f"  ✗ {item.title}: {e}", err=True)
    
    # Fetch watch progress
    click.echo(f"\nFetching watch progress...")
    try:
        progress = viki.get_watch_progress()
        for container_id, videos in progress.items():
            for video_id, watched in videos.items():
                ep = repo.get_episode(video_id)
                if ep:
                    watched_seconds = watched if isinstance(watched, int) else 0
                    repo.upsert_episode(
                        viki_video_id=video_id,
                        viki_id=container_id,
                        watched_seconds=watched_seconds,
                        last_watched_at=datetime.now(timezone.utc),
                    )
    except Exception as e:
        click.echo(f"✗ Failed to fetch progress: {e}", err=True)
    
    click.echo(f"\n✅ Complete")
    click.echo(f"   Shows refreshed: {shows_refreshed}")
    click.echo(f"   Episodes fetched: {episodes_fetched}")


# ============================================================
# SYNC Command
# ============================================================

@click.command()
@click.option("--force-refresh", is_flag=True, help="Force refresh all shows")
@click.option("--dry-run", is_flag=True, help="Preview only, don't sync to Trakt")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def sync(force_refresh: bool, dry_run: bool, verbose: bool):
    """Sync watch history from Viki to Trakt.
    
    This is the main workflow that:
    1. Fetches your Viki watchlist
    2. Refreshes episodes for shows that changed
    3. Matches unmatched shows to Trakt
    4. Syncs watched episodes to Trakt
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    try:
        config = get_config()
        viki_client = config.get_viki_client()
        trakt_client = config.get_trakt_client()
    except Exception as e:
        click.echo(f"✗ Configuration error: {e}", err=True)
        click.echo("Run 'viki-trakt-sync config' to check your settings", err=True)
        sys.exit(1)
    
    # Import adapters and workflow
    from .adapters import VikiAdapter, TraktAdapter
    from .workflows import SyncWorkflow
    from .matcher import ShowMatcher
    from .config_provider import TomlConfigProvider
    
    viki = VikiAdapter(viki_client)
    trakt = TraktAdapter(trakt_client)
    
    # Create matcher with config provider (DI pattern)
    config_provider = TomlConfigProvider()
    matcher = ShowMatcher(config_provider=config_provider)
    
    workflow = SyncWorkflow(
        viki=viki,
        trakt=trakt,
        matcher=matcher.match,
    )
    
    def progress(msg: str):
        click.echo(f"  {msg}")
    
    click.echo("🔄 Starting sync...\n")
    
    result = workflow.run(
        force_refresh=force_refresh,
        dry_run=dry_run,
        progress_callback=progress,
    )
    
    click.echo(f"\n📊 Results:")
    click.echo(f"  Shows fetched:    {result.shows_fetched}")
    click.echo(f"  Shows refreshed:  {result.shows_refreshed}")
    click.echo(f"  Episodes fetched: {result.episodes_fetched}")
    click.echo(f"  Matches found:    {result.matches_found}/{result.matches_attempted}")
    click.echo(f"  Episodes synced:  {result.episodes_synced}")
    
    # Show errors FIRST if there are any (don't hide them with tree output)
    if result.errors:
        click.echo(f"\n❌ ERRORS ({len(result.errors)}):") 
        for err in result.errors[:10]:
            click.echo(f"  - {err}")
        if len(result.errors) > 10:
            click.echo(f"  ... and {len(result.errors) - 10} more")
    else:
        # Only show episode tree if sync succeeded
        click.echo(f"\n📺 Episode Status:")
        _print_episode_status_tree(viki)


def _print_episode_status_tree(viki_adapter):
    """Print a tree view of episode watch status for all shows."""
    repo = Repository()
    shows = repo.get_all_shows()
    
    if not shows:
        return
    
    click.echo("\n📺 Episode Status:\n")
    
    for show_idx, show in enumerate(shows):
        # Show header
        show_title = show.title or f"Unknown ({show.viki_id})"
        is_last_show = show_idx == len(shows) - 1
        show_prefix = "└─ " if is_last_show else "├─ "
        click.echo(f"{show_prefix}{show_title}")
        
        # Get episodes
        viki_id_str = str(show.viki_id)
        episodes = repo.get_show_episodes(viki_id_str)
        
        if not episodes:
            ep_prefix = "   └─ " if is_last_show else "   ├─ "
            click.echo(f"{ep_prefix}(no episodes)")
            continue
        
        # Show episodes (limit to first 10)
        episodes_to_show = episodes[:10]
        
        for ep_idx, ep in enumerate(episodes_to_show):
            is_last_ep = ep_idx == len(episodes_to_show) - 1
            has_more = len(episodes) > 10
            
            # Determine line prefix - use spaces for last item, vertical bar for others
            base_prefix = "   " if is_last_show else "   │"
            ep_connector = "└─ " if (is_last_ep and not has_more) else "├─ "
            
            # Status indicator
            watched_sec = getattr(ep, 'watched_seconds', None)
            duration = getattr(ep, 'duration', None)
            is_watched = getattr(ep, 'is_watched', False)
            ep_num = getattr(ep, 'episode_number', '?')
            
            if is_watched:
                status = "✓ Watched"
            elif watched_sec and duration and watched_sec > 0:
                try:
                    pct = int((watched_sec / duration) * 100)
                    status = f"⏸ {pct}% ({watched_sec}s)"
                except (TypeError, ZeroDivisionError):
                    status = "⏸ In Progress"
            else:
                status = "○ Unwatched"
            
            # Synced indicator
            synced_to_trakt = getattr(ep, 'synced_to_trakt', False)
            synced = " → Trakt" if synced_to_trakt else ""
            
            click.echo(f"{base_prefix}{ep_connector}Ep {ep_num:3}: {status}{synced}")
        
        # Show if more episodes
        if len(episodes) > 10:
            base_prefix = "   " if is_last_show else "   │"
            click.echo(f"{base_prefix}└─ ... and {len(episodes) - 10} more episodes")


# ============================================================
# WATCH Command
# ============================================================

@click.command()
@click.argument("show_id", required=False)
@click.option("--refresh", is_flag=True, help="Fetch fresh data from Viki first")
@click.option("--in-progress", is_flag=True, help="Show only in-progress shows")
@click.option("--pending", is_flag=True, help="Show only shows with pending sync")
def watch(show_id: Optional[str], refresh: bool, in_progress: bool, pending: bool):
    """View watch status from local cache.
    
    Shows your Viki watch progress for all shows or a specific show.
    Data comes from the local cache - use --refresh to fetch fresh data.
    
    \b
    Examples:
      watch                  # List all shows
      watch 12345v           # Show details for a specific show
      watch --in-progress    # Only shows you're currently watching
      watch --pending        # Shows with unsynced episodes
    """
    if refresh:
        # TODO: Trigger a light refresh (just billboard, no episodes)
        click.echo("Refreshing from Viki...")
    
    query = WatchQuery()
    
    if show_id:
        # Show detail view
        detail = query.show_detail(show_id)
        if not detail:
            click.echo(f"Show not found: {show_id}", err=True)
            sys.exit(1)
        
        _print_show_detail(detail)
    else:
        # List view
        if in_progress:
            shows = query.in_progress()
            title = "📺 In Progress"
        elif pending:
            shows = query.pending_sync()
            title = "⏳ Pending Sync"
        else:
            shows = query.all_shows()
            title = "📺 All Shows"
        
        _print_show_list(title, shows)


def _print_show_list(title: str, shows):
    """Print a list of shows with progress."""
    click.echo(f"\n{title} ({len(shows)} shows)\n")
    
    if not shows:
        click.echo("  No shows found")
        return
    
    click.echo(f"  {'Title':<40} {'Progress':<12} {'Synced':<8} {'Match'}")
    click.echo(f"  {'-'*40} {'-'*12} {'-'*8} {'-'*20}")
    
    for s in shows:
        progress = f"{s.watched_episodes}/{s.total_episodes}"
        synced = "✓" if s.pending_sync == 0 else f"{s.pending_sync} pending"
        match = s.match_source or "No match"
        title = s.title[:38] + ".." if len(s.title) > 40 else s.title
        
        click.echo(f"  {title:<40} {progress:<12} {synced:<8} {match}")


def _print_show_detail(detail):
    """Print detailed view of a show."""
    click.echo(f"\n📺 {detail['title']}")
    click.echo(f"   Viki ID: {detail['viki_id']}")
    
    if detail.get('trakt_id'):
        click.echo(f"   Trakt: {detail['trakt_title']} (ID: {detail['trakt_id']})")
        click.echo(f"   Match: {detail['match_source']} ({detail.get('match_confidence', 0)*100:.0f}% confidence)")
    else:
        click.echo(f"   Trakt: Not matched")
    
    click.echo(f"\n   Progress: {detail['watched_episodes']}/{detail['total_episodes']} episodes")
    if detail['pending_sync'] > 0:
        click.echo(f"   Pending sync: {detail['pending_sync']} episodes")
    
    click.echo(f"\n   Episodes:")
    for ep in detail['episodes'][:20]:  # Limit to first 20
        status = "✓" if ep.is_watched else f"{ep.progress_percent:.0f}%" if ep.progress_percent > 0 else "-"
        synced = "→Trakt" if ep.synced_to_trakt else ""
        click.echo(f"     Ep {ep.episode_number:3}: {status:>6} {synced}")
    
    if len(detail['episodes']) > 20:
        click.echo(f"     ... and {len(detail['episodes']) - 20} more episodes")


# ============================================================
# STATUS Command
# ============================================================

@click.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(as_json: bool):
    """Show sync system status and health.
    
    Displays statistics about your sync state and any issues.
    """
    import json
    
    query = StatusQuery()
    health = query.health_check()
    stats = health['stats']
    issues = health['issues']
    
    if as_json:
        output = {
            'status': health['status'],
            'stats': {
                'total_shows': stats.total_shows,
                'matched_shows': stats.matched_shows,
                'unmatched_shows': stats.unmatched_shows,
                'total_episodes': stats.total_episodes,
                'watched_episodes': stats.watched_episodes,
                'synced_episodes': stats.synced_episodes,
                'pending_sync': stats.pending_sync,
                'match_rate': stats.match_rate,
                'sync_rate': stats.sync_rate,
            },
            'issues': [{'severity': i.severity, 'message': i.message} for i in issues],
        }
        click.echo(json.dumps(output, indent=2))
        return
    
    # Header
    status_emoji = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "❌"}
    click.echo(f"\n{status_emoji.get(health['status'], '?')} System Status: {health['status'].upper()}\n")
    
    # Stats
    click.echo("📊 Statistics:")
    click.echo(f"   Shows:    {stats.matched_shows}/{stats.total_shows} matched ({stats.match_rate:.0f}%)")
    click.echo(f"   Episodes: {stats.synced_episodes}/{stats.watched_episodes} synced ({stats.sync_rate:.0f}%)")
    click.echo(f"   Pending:  {stats.pending_sync} episodes to sync")
    
    if stats.last_sync:
        click.echo(f"\n   Last sync: {stats.last_sync} ({stats.last_sync_status})")
    else:
        click.echo(f"\n   Last sync: Never")
    
    # Issues
    if issues:
        click.echo(f"\n⚠️  Issues ({len(issues)}):")
        for issue in issues:
            icon = "❌" if issue.severity == "error" else "⚠️"
            click.echo(f"   {icon} {issue.message}")
            if issue.context:
                click.echo(f"      → {issue.context}")


# ============================================================
# MATCH Command Group
# ============================================================

@click.group()
def match_cmd():
    """View and manage show matches.
    
    \b
    Subcommands:
      show <id>     View match for a show
      list          List unmatched shows
      set           Set a manual match
      clear         Clear a match
    """
    pass


@match_cmd.command("show")
@click.argument("viki_id")
def match_show(viki_id: str):
    """View match information for a show."""
    query = MatchQuery()
    info = query.get_match(viki_id)
    
    if not info:
        click.echo(f"Show not found: {viki_id}", err=True)
        sys.exit(1)
    
    click.echo(f"\n📺 {info.viki_title}")
    click.echo(f"   Viki ID: {info.viki_id}")
    
    if info.is_matched:
        click.echo(f"\n   ✓ Matched to Trakt:")
        click.echo(f"     Title: {info.trakt_title}")
        click.echo(f"     ID: {info.trakt_id}")
        click.echo(f"     Slug: {info.trakt_slug}")
        click.echo(f"     Source: {info.match_source}")
        if info.match_confidence:
            click.echo(f"     Confidence: {info.match_confidence*100:.0f}%")
        if info.match_method:
            click.echo(f"     Method: {info.match_method}")
    else:
        click.echo(f"\n   ✗ Not matched to Trakt")


@match_cmd.command("list")
@click.option("--matched", is_flag=True, help="Show matched instead of unmatched")
def match_list(matched: bool):
    """List unmatched (or matched) shows."""
    query = MatchQuery()
    
    if matched:
        shows = query.list_matched()
        title = "Matched Shows"
    else:
        shows = query.list_unmatched()
        title = "Unmatched Shows"
    
    click.echo(f"\n{title} ({len(shows)})\n")
    
    if not shows:
        click.echo("  None")
        return
    
    for s in shows:
        if matched:
            click.echo(f"  {s.viki_id}: {s.viki_title} → {s.trakt_title} ({s.match_source})")
        else:
            click.echo(f"  {s.viki_id}: {s.viki_title}")


@match_cmd.command("set")
@click.argument("viki_id")
@click.argument("trakt_id", type=int)
@click.option("--slug", help="Trakt slug")
@click.option("--title", "trakt_title", help="Trakt title")
def match_set(viki_id: str, trakt_id: int, slug: Optional[str], trakt_title: Optional[str]):
    """Set a manual match for a show.
    
    \b
    Example:
      match set 12345v 98765 --title "My Show"
    """
    query = MatchQuery()
    
    if query.set_manual_match(viki_id, trakt_id, slug, trakt_title):
        click.echo(f"✓ Set manual match: {viki_id} → Trakt ID {trakt_id}")
    else:
        click.echo(f"✗ Show not found: {viki_id}", err=True)
        sys.exit(1)


@match_cmd.command("clear")
@click.argument("viki_id")
@click.confirmation_option(prompt="Are you sure you want to clear this match?")
def match_clear(viki_id: str):
    """Clear the match for a show."""
    query = MatchQuery()
    
    if query.clear_match(viki_id):
        click.echo(f"✓ Cleared match for: {viki_id}")
    else:
        click.echo(f"✗ Show not found: {viki_id}", err=True)
        sys.exit(1)


@match_cmd.command("test")
def match_test():
    """Test matcher on all shows in local watchlist.
    
    Runs the matcher on every show in your watch database and reports:
    - Match success rate (matched/total)
    - Confidence scores
    - Match methods used
    """
    from .config import get_config
    from .matcher import ShowMatcher
    from .queries.watch import WatchQuery
    from .queries.match import MatchQuery as MatchQueryClass
    
    try:
        config = get_config()
        trakt_creds = config.get_section("trakt")
        
        # Initialize matcher with credentials from config
        matcher = ShowMatcher(
            trakt_client_id=trakt_creds.get("client_id"),
            trakt_client_secret=trakt_creds.get("client_secret"),
        )
        
        # Get all shows from watch database
        watch_query = WatchQuery()
        all_shows = watch_query.all_shows()
        
        if not all_shows:
            click.echo("No shows in watch database yet", err=True)
            sys.exit(1)
        
        click.echo(f"\n🔍 Testing matcher on {len(all_shows)} shows\n")
        
        # Test each show
        results = []
        matched_count = 0
        
        for show in all_shows:
            viki_show = {
                'id': show.viki_id,
                'titles': {'en': show.title}
            }
            
            result = matcher.match(viki_show)
            results.append((show, result))
            
            if result.is_matched():
                matched_count += 1
        
        # Display results summary
        success_rate = 100*matched_count/len(all_shows)
        click.echo(f"📊 Match Results: {matched_count}/{len(all_shows)} ({success_rate:.1f}%)\n")
        
        # Build comprehensive display data
        exact = []
        probable = []
        uncertain = []
        unmatched = []
        
        for show, result in results:
            if result.match_confidence >= 0.95:
                exact.append((show, result))
            elif result.match_confidence >= 0.7:
                probable.append((show, result))
            elif result.match_confidence > 0:
                uncertain.append((show, result))
            else:
                unmatched.append((show, result))
        
        # Display each tier with formatting
        def display_matches(items, title, icon):
            if not items:
                return
            click.echo(f"{icon} {title} ({len(items)})")
            for show, result in items:
                if result.is_matched():
                    conf_pct = f"{result.match_confidence*100:.0f}%"
                    method = f"{result.match_method}" if result.match_method else "unknown"
                    click.echo(f"   {show.title}")
                    click.echo(f"   ↳ {result.trakt_title} ({conf_pct}, {method})\n")
                else:
                    click.echo(f"   {show.title}")
                    if result.notes:
                        click.echo(f"   ↳ {result.notes}\n")
        
        display_matches(exact, "High Confidence (≥95%)", "✓")
        display_matches(probable, "Medium Confidence (70-95%)", "~")
        display_matches(uncertain, "Low Confidence (0-70%)", "?")
        display_matches(unmatched, "Unmatched", "✗")
        
        # Summary statistics
        click.echo(f"📈 Summary:")
        click.echo(f"   High (≥95%):     {len(exact):2d} shows")
        click.echo(f"   Medium (70-95%): {len(probable):2d} shows")
        click.echo(f"   Low (0-70%):     {len(uncertain):2d} shows")
        click.echo(f"   Unmatched:       {len(unmatched):2d} shows")
        click.echo()
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ============================================================
# Export for integration with main CLI
# ============================================================

def register_commands(cli_group):
    """Register new commands with an existing Click group.
    
    Usage in cli.py:
        from .cli_new import register_commands
        register_commands(main)
    """
    cli_group.add_command(sync)
    cli_group.add_command(refresh)
    cli_group.add_command(watch)
    cli_group.add_command(status)
    cli_group.add_command(match_cmd, name="match")  # Replace old match command
