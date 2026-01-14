"""Command-line interface for Viki-Trakt sync."""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv
import builtins

from .viki_client import VikiClient
from .cache import WatchHistoryCache, ShowMetadataCache
from .evaluator import MatchingEvaluator

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """
    Sync watch history from Viki to Trakt.tv
    
    Configure credentials in .env file (see README.md for details)
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@main.group()
def viki():
    """Authenticate with Viki and manage credentials."""
    pass


@main.group()
def match():
    """Match Viki shows to Trakt database."""
    pass


@main.group()
def cache():
    """Manage local watch history cache."""
    pass


@main.group()
def watchdb():
    """Manage local watch database (shows/episodes)."""
    pass


@viki.command()
@click.option("--username", "-u", prompt=True, help="Viki username/email")
@click.option("--password", "-p", prompt=True, hide_input=True, help="Viki password")
def login(username: str, password: str):
    """Authenticate with Viki (requires manual CAPTCHA in browser)."""
    client = VikiClient()
    
    click.echo("\n⚠️  WARNING: Viki requires reCAPTCHA for programmatic login.")
    click.echo("Instead, please follow these steps:\n")
    
    click.echo("1. Open https://www.viki.com in your browser")
    click.echo("2. Login with your credentials")
    click.echo("3. Open DevTools (F12) → Application tab → Cookies → https://www.viki.com")
    click.echo("4. Find and copy these values:")
    click.echo("   - session__id")
    click.echo("5. Set environment variables:")
    click.echo("   export VIKI_SESSION='<your session__id value>'")
    click.echo("\n6. To get your API token, you can:")
    click.echo("   a. Check Network tab for any API request with ?token=... parameter")
    click.echo("   b. Or run: python -m viki_trakt_sync.cli viki extract-token")
    click.echo("\nAlternatively, update your .env file:")
    click.echo("   VIKI_SESSION=<session__id>")
    click.echo("   VIKI_TOKEN=<token>")


@viki.command("extract-token")
@click.option("--session-cookie", "-s", help="Session cookie (or set VIKI_SESSION)")
def extract_token(session_cookie: Optional[str]):
    """Extract API token from existing session."""
    session_cookie = session_cookie or os.getenv("VIKI_SESSION")
    
    if not session_cookie:
        click.echo("Error: Session cookie required", err=True)
        click.echo("Set VIKI_SESSION or use --session-cookie flag", err=True)
        sys.exit(1)
    
    client = VikiClient(session_cookie=session_cookie)
    
    try:
        # Get current user (this should work with just session cookie)
        user = client.get_current_user()
        click.echo(f"✓ Session valid for user: {user.get('username', 'Unknown')}")
        click.echo(f"✓ User ID: {user['id']}")
        
        # Try to get watch markers to extract token from URL
        click.echo("\nAttempting to extract token from API calls...")
        
        # Make a request that includes token in response or URL
        # For now, user needs to check browser DevTools
        click.echo("\nTo get your token:")
        click.echo("1. Stay logged in to Viki in browser")
        click.echo("2. Open DevTools → Network tab")
        click.echo("3. Visit your Viki continue watching page")
        click.echo("4. Look for requests to api.viki.io")
        click.echo("5. Find the 'token' parameter in the URL (starts with 'ex1')")
        click.echo("\nThen run: export VIKI_TOKEN='<token>'")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@viki.command()
@click.option("--username", "-u", help="Viki username/email (or set VIKI_USER)")
@click.option("--password", "-p", help="Viki password (or set VIKI_PASS)")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
@click.option("--session-cookie", "-s", help="Viki session cookie (or set VIKI_SESSION)")
@click.option("--limit", "-n", type=int, default=10, help="Limit number of items to show")
def list(
    username: Optional[str],
    password: Optional[str],
    token: Optional[str],
    session_cookie: Optional[str],
    limit: int,
):
    """List watch history from Viki."""
    # Load from environment if not provided
    username = username or os.getenv("VIKI_USER")
    password = password or os.getenv("VIKI_PASS")
    token = token or os.getenv("VIKI_TOKEN")
    session_cookie = session_cookie or os.getenv("VIKI_SESSION")
    
    # Initialize client with available credentials
    client = VikiClient(
        username=username,
        password=password,
        token=token,
        session_cookie=session_cookie,
    )
    
    try:
        # If we have token, use it directly (no need for session validation)
        if token:
            click.echo("✓ Using provided token")
        elif session_cookie:
            click.echo("✓ Using session cookie")
        elif username and password:
            # Try to login (will fail with CAPTCHA error and provide instructions)
            click.echo("⚠ Attempting login (may require CAPTCHA)...")
            client.login(username, password)
        else:
            click.echo("Error: Need token, session cookie, or username+password", err=True)
            click.echo("\nQuickest method - extract from browser:", err=True)
            click.echo("  python extract_credentials.py", err=True)
            sys.exit(1)
        
        # Fetch watch markers
        markers_data = client.get_watch_markers()
        
        click.echo(f"\n📺 Watch History (Total: {markers_data['count']} items)")
        click.echo(f"Last updated: {markers_data['updated_till']}\n")
        
        # Flatten markers
        all_markers = []
        for container_id, videos in markers_data["markers"].items():
            for video_id, marker in videos.items():
                marker["container_id"] = container_id
                all_markers.append(marker)
        
        # Sort by timestamp (most recent first)
        all_markers.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Display limited results
        for idx, marker in enumerate(all_markers[:limit], 1):
            # Handle both formats: with and without watch_marker/credits_marker
            has_progress = "watch_marker" in marker
            
            if has_progress:
                watched = client.is_episode_watched(
                    marker["watch_marker"],
                    marker["duration"],
                    marker["credits_marker"]
                )
                
                status = "✓ Watched" if watched else "⏸ In Progress"
                progress_pct = (marker["watch_marker"] / marker["duration"]) * 100 if marker["duration"] else 0
                progress_str = f"| Progress: {progress_pct:.1f}% ({marker['watch_marker']}/{marker['duration']}s)"
            else:
                # If no detailed progress, assume watched (from watchlist)
                watched = True
                status = "✓ Watched"
                progress_str = "(from watchlist)"
            
            click.echo(f"{idx}. Container: {marker['container_id']} | Episode: {marker.get('episode', 'N/A')}")
            click.echo(f"   {status} {progress_str}")
            click.echo(f"   Watched at: {marker['timestamp']}")
            click.echo()
        
        if len(all_markers) > limit:
            click.echo(f"... and {len(all_markers) - limit} more items")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@viki.command()
@click.argument("container_id")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
def show(container_id: str, token: Optional[str]):
    """Show metadata for a container (series/movie)."""
    token = token or os.getenv("VIKI_TOKEN")
    
    if not token:
        click.echo("Error: Token required", err=True)
        click.echo("Set VIKI_TOKEN environment variable or use --token flag", err=True)
        sys.exit(1)
    
    client = VikiClient(token=token)
    
    try:
        # Fetch container
        container = client.get_container(container_id)
        
        # Display
        click.echo(f"\n📺 {container['titles'].get('en', container['titles'].get('ko', 'Unknown'))}")
        click.echo(f"ID: {container['id']}")
        click.echo(f"Type: {container['type']}")
        
        if 'origin' in container:
            click.echo(f"Origin: {container['origin'].get('country', 'Unknown')} ({container['origin'].get('language', 'Unknown')})")
        
        if 'genres' in container:
            click.echo(f"Genres: {', '.join(container['genres'])}")
        
        # All titles
        click.echo("\nTitles:")
        for lang, title in container['titles'].items():
            click.echo(f"  [{lang}] {title}")
        
        # Episodes count if series
        if container['type'] == 'series':
            click.echo(f"\nEpisodes: {container.get('planned_episodes', 'Unknown')}")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@viki.command()
@click.argument("container_id")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
def episodes(container_id: str, token: Optional[str]):
    """List episodes for a container."""
    token = token or os.getenv("VIKI_TOKEN")
    
    if not token:
        click.echo("Error: Token required", err=True)
        click.echo("Set VIKI_TOKEN environment variable or use --token flag", err=True)
        sys.exit(1)
    
    client = VikiClient(token=token)
    
    try:
        # Fetch episodes
        episodes_data = client.get_episodes(container_id)
        
        episodes_list = episodes_data["response"]
        
        click.echo(f"\n📺 Episodes for {container_id} (Total: {len(episodes_list)})\n")
        
        for ep in episodes_list:
            click.echo(f"Episode {ep['number']}: {ep['id']}")
            click.echo(f"  Duration: {ep['duration']}s ({ep['duration']//60}min)")
            if 'viki_air_time' in ep:
                click.echo(f"  Air time: {ep['viki_air_time']}")
            click.echo()
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)

@viki.command(name="watchlaters")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
@click.option("--ids-only/--full", default=True, help="Return only container IDs or full items")
def watchlaters(token: Optional[str], ids_only: bool):
    """List count and first page of Watch Later (bookmarks)."""
    token = token or os.getenv("VIKI_TOKEN")
    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)

    client = VikiClient(token=token)
    try:
        data = client.get_watchlaters(ids_only=ids_only, per_page=100)
        click.echo(f"\n🔖 Watch Later: {data['count']} items")
        sample = data.get("response", [])[:10]
        if not sample:
            return
        click.echo("\nFirst items:")
        if ids_only:
            for cid in sample:
                click.echo(f"  - {cid}")
        else:
            for item in sample:
                click.echo(f"  - {item.get('id')}: {item.get('titles',{}).get('en') or item.get('titles',{}).get('ko')}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@match.command(name="list-shows")
@click.option("--limit", "-n", type=int, default=10, help="Limit number of shows to match")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
def match_list_shows(limit: int, token: Optional[str]):
    """List and match Viki shows from watch history.
    
    This is the core Phase 1.2 matching feature.
    Shows Viki shows matched to Trakt IDs.
    """
    from .matcher import ShowMatcher
    
    token = token or os.getenv("VIKI_TOKEN")
    
    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)
    
    # Initialize clients
    viki_client = VikiClient(token=token)
    trakt_client_id = os.getenv("TRAKT_CLIENT_ID")
    trakt_client_secret = os.getenv("TRAKT_CLIENT_SECRET")
    matcher = ShowMatcher(trakt_client_id, trakt_client_secret)
    
    try:
        # Get watch history
        click.echo("📺 Fetching watch history from Viki...")
        markers_data = viki_client.get_watch_markers()
        
        # Get unique shows (flatten and deduplicate)
        shows_by_id = {}
        for container_id, videos in markers_data.get("markers", {}).items():
            if container_id not in shows_by_id:
                shows_by_id[container_id] = {
                    "id": container_id,
                    "episodes": []
                }
            
            for video_id, marker in videos.items():
                shows_by_id[container_id]["episodes"].append(marker)
        
        click.echo(f"\n📊 Found {len(shows_by_id)} unique shows in your watch history\n")
        
        # Match first N shows
        shows_to_match = builtins.list(shows_by_id.items())[:limit]
        
        for idx, (viki_id, show_data) in enumerate(shows_to_match, 1):
            # Get show title from first episode
            episodes = show_data["episodes"]
            if episodes:
                title = episodes[0].get("show_title", f"Unknown ({viki_id})")
            else:
                title = f"Unknown ({viki_id})"
            
            click.echo(f"{idx}. {title} ({viki_id})")
            
            # Get container metadata for more info
            try:
                container = viki_client.get_container(viki_id)
                viki_show = {
                    "id": viki_id,
                    "titles": container.get("titles", {}),
                    "origin": container.get("origin", {}),
                }
            except:
                viki_show = {
                    "id": viki_id,
                    "titles": {"en": title},
                    "origin": {},
                }
            
            # Match to Trakt
            result = matcher.match(viki_show)
            
            if result.is_matched():
                click.echo(
                    f"   ✅ Matched to Trakt: {result.trakt_title} "
                    f"(ID: {result.trakt_id}, Confidence: {result.match_confidence:.0%})"
                )
                click.echo(f"   📺 Episodes watched: {len(episodes)}")
            else:
                click.echo(
                    f"   ❌ No match found (tried: {result.match_method})"
                )
                if result.notes:
                    click.echo(f"   Note: {result.notes}")
            
            click.echo()
        
        # Show statistics
        stats = matcher.db.stats()
        click.echo(f"\n📊 Matching Statistics:")
        click.echo(f"   Total in database: {stats['total']}")
        click.echo(f"   Matched: {stats['matched']}")
        click.echo(f"   Unmatched: {stats['unmatched']}")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@match.command()
@click.argument("viki_id")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed matching info")
def show_match(viki_id: str, token: Optional[str], verbose: bool):
    """Match a specific Viki show to Trakt."""
    from .matcher import ShowMatcher
    
    token = token or os.getenv("VIKI_TOKEN")
    
    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)
    
    # Initialize clients
    viki_client = VikiClient(token=token)
    trakt_client_id = os.getenv("TRAKT_CLIENT_ID")
    trakt_client_secret = os.getenv("TRAKT_CLIENT_SECRET")
    matcher = ShowMatcher(trakt_client_id, trakt_client_secret)
    
    try:
        # Get show from Viki
        click.echo(f"Looking up Viki show: {viki_id}...")
        container = viki_client.get_container(viki_id)
        
        viki_show = {
            "id": viki_id,
            "titles": container.get("titles", {}),
            "origin": container.get("origin", {}),
        }
        
        title = container.get("titles", {}).get("en", f"Unknown ({viki_id})")
        click.echo(f"\n📺 {title}")
        click.echo(f"   Viki ID: {viki_id}")
        click.echo(f"   Type: {container.get('type')}")
        
        if container.get("origin"):
            click.echo(
                f"   Origin: {container['origin'].get('country')} "
                f"({container['origin'].get('language')})"
            )
        
        # Match to Trakt
        click.echo(f"\n🔍 Matching to Trakt...")
        result = matcher.match(viki_show)
        
        if result.is_matched():
            click.echo(f"\n✅ Match found!")
            click.echo(f"   Trakt Title: {result.trakt_title}")
            click.echo(f"   Trakt ID: {result.trakt_id}")
            click.echo(f"   Trakt Slug: {result.trakt_slug}")
            click.echo(f"   Confidence: {result.match_confidence:.0%}")
            click.echo(f"   Method: {result.match_method}")
            
            if verbose:
                click.echo(f"\n   Full result:")
                for key, value in result.to_dict().items():
                    click.echo(f"     {key}: {value}")
        else:
            click.echo(f"\n❌ No match found")
            if result.notes:
                click.echo(f"   Details: {result.notes}")
            
            if verbose:
                click.echo(f"\n   Tried methods: {result.match_method}")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@match.command()
def stats():
    """Show matching statistics from local database."""
    from .matcher import ShowMatcher
    
    try:
        matcher = ShowMatcher()  # Just for DB access
        db_stats = matcher.db.stats()
        
        click.echo("\n📊 Matching Database Statistics\n")
        click.echo(f"Total shows processed: {db_stats['total']}")
        click.echo(f"Successfully matched: {db_stats['matched']}")
        click.echo(f"Unmatched: {db_stats['unmatched']}")
        
        if db_stats['total'] > 0:
            match_rate = (db_stats['matched'] / db_stats['total']) * 100
            click.echo(f"Match rate: {match_rate:.1f}%")
        
        # List first few unmatched
        if db_stats['unmatched'] > 0:
            unmatched = matcher.db.list_unmatched(limit=5)
            click.echo(f"\nFirst {len(unmatched)} unmatched shows:")
            for vid in unmatched:
                click.echo(f"  - {vid}")
            
            if db_stats['unmatched'] > 5:
                click.echo(f"  ... and {db_stats['unmatched'] - 5} more")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@match.command(name="watchlaters")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
@click.option("--limit", "-n", type=int, help="Limit number to match")
@click.option("--verbose", "-v", is_flag=True, help="Verbose matching output")
def match_watchlaters(token: Optional[str], limit: Optional[int], verbose: bool):
    """Match bookmarked Watch Later shows (stress test for Trakt matching)."""
    from .matcher import ShowMatcher, MatchResult

    token = token or os.getenv("VIKI_TOKEN")
    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)

    client = VikiClient(token=token)
    matcher = ShowMatcher(os.getenv("TRAKT_CLIENT_ID"), os.getenv("TRAKT_CLIENT_SECRET"))

    try:
        # Fetch watch later IDs (fast path)
        wl = client.get_watchlaters(ids_only=True, per_page=100)
        ids = wl.get("response", [])
        total = len(ids)
        if limit:
            ids = ids[:limit]
        click.echo(f"\n🔖 Matching Watch Later shows: {len(ids)} of {total}")

        exact = []
        close = []
        nomatch = []

        for idx, cid in enumerate(ids, 1):
            if verbose:
                click.echo(f"[{idx}/{len(ids)}] {cid}")
            # Fetch container metadata for titles
            try:
                c = client.get_container(cid)
                viki_show = {
                    "id": cid,
                    "titles": c.get("titles", {}),
                    "origin": c.get("origin", {}),
                }
            except Exception:
                viki_show = {"id": cid, "titles": {}, "origin": {}}

            result = matcher.match(viki_show)
            if result.is_matched():
                if result.match_confidence >= 0.95:
                    exact.append(result)
                elif result.match_confidence >= 0.70:
                    close.append(result)
                else:
                    nomatch.append(result)
            else:
                nomatch.append(result)

        # Print summary
        click.echo("\n📊 MATCH SUMMARY (Watch Later)")
        tot = len(exact) + len(close) + len(nomatch)
        click.echo(f"  Total: {tot}")
        click.echo(f"  Exact: {len(exact)}")
        click.echo(f"  Close: {len(close)}")
        click.echo(f"  No Match: {len(nomatch)}")

        # Show samples
        def _print_group(name: str, arr):
            if not arr:
                return
            click.echo(f"\n{name} ({len(arr)})")
            for r in arr[:10]:
                click.echo(
                    f"- Viki: {r.viki_title or r.viki_id} → Trakt: {r.trakt_title or 'n/a'} "
                    f"(id={r.trakt_id}, conf={r.match_confidence:.0%}, method={r.match_method})"
                )

        _print_group("Exact", exact)
        _print_group("Close", close)
        _print_group("No Match", nomatch)

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cache.command(name="init")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
def cache_init(token: Optional[str]):
    """Initialize cache with your watch history.

    Downloads your watch history once and caches it locally.
    Also fetches show details (title, year, etc) for each show.
    All future matching operations use cached data (no API calls).

    Run this once, then use evaluation commands for instant testing.
    """
    token = token or os.getenv("VIKI_TOKEN")

    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)

    try:
        click.echo("📺 Fetching watch history from Viki...")
        viki_client = VikiClient(token=token)
        markers = viki_client.get_watch_markers()

        # Extract show IDs
        show_count = len(markers.get("markers", {}))
        show_ids = builtins.list(markers.get("markers", {}).keys())
        click.echo(f"   Found {show_count} shows")

        # Fetch show details for each show
        click.echo("📖 Fetching show details...")
        shows = {}
        for idx, show_id in enumerate(show_ids, 1):
            click.echo(f"   [{idx}/{show_count}] {show_id}...")
            try:
                show_data = viki_client.get_container(show_id)
                shows[show_id] = show_data
            except Exception as e:
                click.echo(f"      ⚠️  Failed to fetch {show_id}: {e}")
                shows[show_id] = {"id": show_id, "titles": {"en": f"Unknown ({show_id})"}}

        # Cache it
        click.echo("💾 Caching to disk...")
        watch_cache = WatchHistoryCache()
        watch_cache.save(
            markers,
            shows=shows,
            metadata={"show_count": show_count, "shows_cached": len(shows)}
        )

        click.echo(f"\n✅ Cache initialized!")
        click.echo(f"   Location: {watch_cache.cache_path}")
        click.echo(f"   Shows cached: {show_count}")
        click.echo(f"   Show details: {len(shows)}/{show_count}")
        click.echo(f"\nNow use: python -m viki_trakt_sync.cli match evaluate")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


@cache.command(name="stats")
def cache_stats():
    """Show cache statistics."""
    try:
        watch_cache = WatchHistoryCache()
        metadata_cache = ShowMetadataCache()

        watch_data = watch_cache.get()
        watch_shows = len(watch_data.get("markers", {})) if watch_data else 0

        metadata_stats = metadata_cache.stats()

        click.echo("\n📊 Cache Statistics\n")

        click.echo("Watch History Cache:")
        if watch_data:
            click.echo(f"  ✅ Cached")
            click.echo(f"  Shows: {watch_shows}")
            click.echo(f"  Cached at: {watch_data.get('cached_at', 'unknown')}")
            click.echo(f"  Size: {watch_cache.cache_path.stat().st_size / 1024:.1f} KB")
        else:
            click.echo(f"  ❌ Not cached (run: cache init)")

        click.echo("\nShow Metadata Cache:")
        click.echo(f"  Total shows: {metadata_stats['total']}")
        click.echo(f"  With TVDB: {metadata_stats['with_tvdb']}")
        click.echo(f"  With MDL: {metadata_stats['with_mdl']}")
        if metadata_stats["total"] > 0:
            click.echo(f"  Size: {metadata_cache.cache_path.stat().st_size / 1024:.1f} KB")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cache.command(name="clear")
@click.confirmation_option(
    prompt="Are you sure you want to clear all caches?",
    help="Confirm clearing caches",
)
def cache_clear():
    """Clear all caches."""
    try:
        watch_cache = WatchHistoryCache()
        metadata_cache = ShowMetadataCache()

        watch_cache.clear()
        metadata_cache.clear()

        click.echo("✅ All caches cleared")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cache.command(name="http-stats")
def cache_http_stats():
    """Show HTTP cache (Trakt/TVDB) statistics."""
    try:
        from .http_cache import get_trakt_session, get_tvdb_session
        t = get_trakt_session()
        v = get_tvdb_session()
        t_stats = t.stats()
        v_stats = v.stats()
        click.echo("\n🌐 HTTP Cache Stats\n")
        click.echo(f"Trakt: {t_stats}")
        click.echo(f"TVDB:  {v_stats}")
        click.echo("\nTTL overrides via env:")
        click.echo("  TRAKT_CACHE_HOURS (default 1)")
        click.echo("  TVDB_CACHE_HOURS (default 24)")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@cache.command(name="http-clear")
def cache_http_clear():
    """Clear HTTP cache databases (Trakt/TVDB)."""
    try:
        from .http_cache import get_trakt_session, get_tvdb_session
        get_trakt_session().clear()
        get_tvdb_session().clear()
        click.echo("✅ HTTP caches cleared (Trakt, TVDB)")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@watchdb.command(name="update")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
@click.option("--match", is_flag=True, help="Attempt to match shows to Trakt and store IDs")
@click.option("--snapshot", is_flag=True, help="Cache raw payload to DB for auditing")
def watchdb_update(token: Optional[str], match: bool, snapshot: bool):
    """Scan Continue Watching and update the local watch DB.

    Ingests the current Continue Watching (watchlist section) into a
    local SQLite DB to persist episodes and show presence.
    """
    from .watch_db import WatchDB
    from .matcher import ShowMatcher

    token = token or os.getenv("VIKI_TOKEN")
    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)

    try:
        viki_client = VikiClient(token=token)
        db = WatchDB()

        click.echo("📺 Fetching Continue Watching from Viki...")
        markers = viki_client.get_watch_markers()

        # Optionally enrich shows and store show-level rows
        matcher = ShowMatcher() if match else None

        shows_seen = 0
        for container_id in markers.get("markers", {}).keys():
            title = None
            type_ = None
            origin_country = None
            origin_language = None
            trakt_id = None
            trakt_slug = None
            trakt_title = None

            # Fetch container metadata (cheap, used for identifying purposes)
            try:
                container = viki_client.get_container(container_id)
                titles = container.get("titles", {})
                title = titles.get("en") or next(iter(titles.values()), None)
                type_ = container.get("type")
                if container.get("origin"):
                    origin_country = container["origin"].get("country")
                    origin_language = container["origin"].get("language")

                if matcher:
                    result = matcher.match({
                        "id": container_id,
                        "titles": titles,
                        "origin": container.get("origin", {}),
                    })
                    if result.is_matched():
                        trakt_id = result.trakt_id
                        trakt_slug = result.trakt_slug
                        trakt_title = result.trakt_title
            except Exception as e:
                logger.debug(f"Failed to fetch container {container_id}: {e}")

            db.upsert_show(
                viki_container_id=container_id,
                title=title,
                type_=type_,
                origin_country=origin_country,
                origin_language=origin_language,
                trakt_id=trakt_id,
                trakt_slug=trakt_slug,
                trakt_title=trakt_title,
            )
            shows_seen += 1

        # Optionally snapshot raw payload for caching/auditing
        if snapshot:
            db.save_snapshot(markers, source="watchlist")

        # Ingest episode-level data from markers/watchlist
        episodes = db.ingest_watch_markers(markers, source="watchlist")

        click.echo("\n✅ Watch DB updated")
        click.echo(f"   Shows: {shows_seen}")
        click.echo(f"   Episodes upserted: {episodes}")
        click.echo(f"   DB: {db.db_path}")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@watchdb.command(name="stats")
def watchdb_stats():
    """Show counts and last scan info for the watch DB."""
    from .watch_db import WatchDB
    try:
        db = WatchDB()
        st = db.stats()
        click.echo("\n📊 Watch DB Statistics\n")
        click.echo(f"Shows: {st['shows']}")
        click.echo(f"Episodes: {st['episodes']}")
        click.echo(f"Scans: {st['scans']}")
        click.echo(f"Path: {db.db_path}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@main.group()
def dataset():
    """Matching dataset builder (offline corpus)."""
    pass


@dataset.command(name="build")
@click.option("--token", "-t", help="Viki API token (or set VIKI_TOKEN)")
@click.option("--target", "-n", type=int, default=300, help="Target number of shows to collect")
@click.option("--out", type=click.Path(path_type=Path), help="Output JSON path")
@click.option("--pretty/--compact", default=False, help="Pretty-print JSON output (larger file)")
def dataset_build(token: Optional[str], target: int, out: Optional[Path], pretty: bool):
    """Build a local matching corpus by browsing Viki and querying Trakt."""
    from .dataset import MatchCorpusBuilder

    token = token or os.getenv("VIKI_TOKEN")
    if not token:
        click.echo("Error: Token required", err=True)
        sys.exit(1)

    try:
        builder = MatchCorpusBuilder(token)
        path = builder.build(out_path=out, target=target, pretty=pretty)
        click.echo(f"\n✅ Built corpus: {path}")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@dataset.command(name="stats")
@click.option("--path", type=click.Path(path_type=Path), help="Path to corpus JSON")
def dataset_stats(path: Optional[Path]):
    """Show corpus statistics and quick sample."""
    from .dataset import MatchCorpusBuilder
    try:
        data = MatchCorpusBuilder.load(path)
        items = data.get("items", [])
        exact = sum(1 for it in items if (it.get("matched") or {}).get("match_confidence", 0) >= 0.95)
        close = sum(1 for it in items if 0.7 <= (it.get("matched") or {}).get("match_confidence", 0) < 0.95)
        nom = len(items) - exact - close
        click.echo("\n📊 Corpus Statistics\n")
        click.echo(f"Items: {len(items)}")
        click.echo(f"Exact: {exact}")
        click.echo(f"Close: {close}")
        click.echo(f"No match: {nom}")
        for it in items[:5]:
            mt = it.get("matched", {})
            click.echo(
                f"- {it['viki_titles'].get('en') or next(iter(it['viki_titles'].values()), it['viki_id'])} → "
                f"{mt.get('trakt_title','n/a')} (conf={mt.get('match_confidence',0):.0%}, method={mt.get('match_method')})"
            )
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@dataset.command(name="eval")
@click.option("--path", type=click.Path(path_type=Path), help="Path to corpus JSON")
@click.option("--limit", "-n", type=int, help="Limit items to evaluate")
@click.option("--compare", is_flag=True, help="Compare against stored matches in corpus")
@click.option("--verbose", "-v", is_flag=True, help="Print per-item results for first few")
def dataset_eval(path: Optional[Path], limit: Optional[int], compare: bool, verbose: bool):
    """Re-run matcher across the corpus and report Exact/Close/No-Match rates."""
    from .dataset import MatchCorpusBuilder
    from .matcher import ShowMatcher

    try:
        data = MatchCorpusBuilder.load(path)
        items = data.get("items", [])
        total = len(items)
        if limit:
            items = items[:limit]

        matcher = ShowMatcher()

        exact = []
        close = []
        nomatch = []
        diffs = []

        for idx, it in enumerate(items, 1):
            viki_show = {
                "id": it["viki_id"],
                "titles": it.get("viki_titles", {}),
                "origin": it.get("origin", {}),
            }
            res = matcher.match(viki_show)
            if res.is_matched():
                if res.match_confidence >= 0.95:
                    exact.append(res)
                elif res.match_confidence >= 0.70:
                    close.append(res)
                else:
                    nomatch.append(res)
            else:
                nomatch.append(res)

            if compare:
                old = it.get("matched", {})
                if (res.trakt_id != old.get("trakt_id")) or (
                    res.trakt_slug != old.get("trakt_slug")
                ):
                    diffs.append(
                        (
                            it["viki_titles"].get("en") or next(iter(it["viki_titles"].values()), it["viki_id"]),
                            old.get("trakt_title"),
                            res.trakt_title,
                        )
                    )

        tot_eval = len(items)
        tot_exact = len(exact)
        tot_close = len(close)
        tot_no = len(nomatch)

        click.echo("\n📊 Corpus Evaluation")
        click.echo(f"Items evaluated: {tot_eval} (of {total})")
        click.echo(f"Exact (>=95%): {tot_exact} ({(tot_exact/tot_eval*100):.1f}%)")
        click.echo(f"Close (70-95%): {tot_close} ({(tot_close/tot_eval*100):.1f}%)")
        click.echo(f"No Match: {tot_no} ({(tot_no/tot_eval*100):.1f}%)")

        if compare and diffs:
            click.echo(f"\n⚠️  Differences vs stored corpus: {len(diffs)}")
            for t, old, new in diffs[:10]:
                click.echo(f"- {t}: {old} → {new}")

        if verbose:
            head = exact[:2] + close[:2] + nomatch[:2]
            click.echo("\nSamples:")
            for r in head:
                click.echo(
                    f"- {r.viki_title} → {r.trakt_title or 'n/a'} (conf={r.match_confidence:.0%}, method={r.match_method})"
                )

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@dataset.command(name="nonmatches")
@click.option("--path", type=click.Path(path_type=Path), help="Path to corpus JSON")
@click.option("--limit", "-n", type=int, help="Limit items to show")
@click.option("--recalc", is_flag=True, help="Re-run matcher to determine non-matches (uses cache)")
@click.option("--candidates", is_flag=True, help="Show top Trakt search candidates from corpus")
@click.option("--out", type=click.Path(path_type=Path), help="Export list to JSON (path)")
def dataset_nonmatches(path: Optional[Path], limit: Optional[int], recalc: bool, candidates: bool, out: Optional[Path]):
    """List non-matching items from the corpus, with optional candidate suggestions."""
    from .dataset import MatchCorpusBuilder
    from .matcher import ShowMatcher

    try:
        data = MatchCorpusBuilder.load(path)
        items = data.get("items", [])

        if recalc:
            matcher = ShowMatcher()
            nm: list[dict] = []
            for it in items:
                res = matcher.match({"id": it["viki_id"], "titles": it.get("viki_titles", {}), "origin": it.get("origin", {})})
                if not res.is_matched() or res.match_confidence < 0.70:
                    nm.append({"item": it, "result": res.to_dict()})
        else:
            nm = []
            for it in items:
                m = it.get("matched") or {}
                if (m.get("match_confidence") or 0) < 0.70:
                    nm.append({"item": it, "result": m})

        if limit:
            nm = nm[:limit]

        # Export if requested
        if out:
            serializable = []
            for entry in nm:
                it = entry["item"]
                m = entry["result"]
                title = it.get("viki_titles", {}).get("en") or next(iter(it.get("viki_titles", {}).values()), it["viki_id"])
                serializable.append({
                    "viki_id": it["viki_id"],
                    "title": title,
                    "origin": it.get("origin", {}),
                    "matched": m,
                    "top_candidates": [
                        {"title": s.get("show", {}).get("title"), "slug": (s.get("show", {}).get("ids", {}) or {}).get("slug")}
                        for s in (it.get("trakt_search") or [])[:5]
                    ] if candidates else [],
                })
            with open(out, "w", encoding="utf-8") as f:
                import json
                json.dump(serializable, f, ensure_ascii=False, indent=2)
            click.echo(f"\n✅ Wrote {len(serializable)} non-matches to {out}")
            return

        # Otherwise, print a readable list
        click.echo("\n❌ Non-Matches")
        for entry in nm:
            it = entry["item"]
            m = entry["result"]
            title = it.get("viki_titles", {}).get("en") or next(iter(it.get("viki_titles", {}).values()), it["viki_id"])
            click.echo(f"- {title} ({it['viki_id']})")
            if m:
                click.echo(f"  Matched: {m.get('trakt_title','n/a')} (conf={m.get('match_confidence',0):.0%}, method={m.get('match_method')})")
            if candidates:
                search = it.get("trakt_search") or []
                if search:
                    click.echo("  Candidates:")
                    for s in search[:5]:
                        show = s.get("show", {})
                        click.echo(f"    • {show.get('title')} [{(show.get('ids',{}) or {}).get('slug')}]")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@dataset.command(name="inspect")
@click.argument("viki_id")
@click.option("--path", type=click.Path(path_type=Path), help="Path to corpus JSON")
def dataset_inspect(viki_id: str, path: Optional[Path]):
    """Show detailed info for a specific Viki ID from the corpus (titles, candidates, match)."""
    from .dataset import MatchCorpusBuilder
    try:
        data = MatchCorpusBuilder.load(path)
        items = data.get("items", [])
        it = next((x for x in items if x.get("viki_id") == viki_id), None)
        if not it:
            click.echo("Not found in corpus", err=True)
            sys.exit(1)
        click.echo(f"\n📄 {viki_id}")
        titles = it.get("viki_titles", {})
        for k, v in titles.items():
            click.echo(f"  [{k}] {v}")
        click.echo(f"Origin: {it.get('origin', {})}")
        m = it.get("matched", {})
        click.echo(f"\nMatched: {m.get('trakt_title','n/a')} (id={m.get('trakt_id')}, slug={m.get('trakt_slug')}, conf={m.get('match_confidence',0):.0%}, method={m.get('match_method')})")
        search = it.get("trakt_search") or []
        if search:
            click.echo("\nTop candidates:")
            for s in search[:10]:
                show = s.get("show", {})
                ids = (show.get("ids", {}) or {})
                click.echo(f"  - {show.get('title')} (slug={ids.get('slug')}, trakt={ids.get('trakt')})")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@main.group()
def trakt():
    """Trakt authentication and actions."""
    pass


@trakt.command(name="login")
@click.option("--no-poll", is_flag=True, help="Show device code without polling")
def trakt_login(no_poll: bool):
    """Authenticate with Trakt via device code flow."""
    try:
        from .trakt_client import TraktClient
        client = TraktClient()
        if no_poll:
            code = client.device_login(poll=False)
            click.echo(f"\nGo to: {code.get('verification_url')}\nEnter code: {code.get('user_code')}")
        else:
            tokens = client.device_login()
            click.echo("\n✅ Trakt login successful")
            click.echo(f"Access token: {tokens.get('access_token')[:6]}... (stored in session)")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        click.echo("\nTip: Ensure 'pytrakt' is installed and legacy 'trakt' is NOT installed.", err=True)
        click.echo("Try: pip uninstall -y trakt && pip install -U pytrakt", err=True)
        sys.exit(1)


@trakt.command(name="doctor")
def trakt_doctor():
    """Diagnose Trakt client environment and package conflicts."""
    import sys
    import importlib
    import importlib.util as util
    import importlib.metadata as md
    try:
        dist_trakt = None
        dist_pytrakt = None
        try:
            dist_trakt = md.version('trakt')
        except Exception:
            pass
        try:
            dist_pytrakt = md.version('pytrakt')
        except Exception:
            pass
        click.echo("\n📦 Package versions")
        click.echo(f"  trakt:   {dist_trakt}")
        click.echo(f"  pytrakt: {dist_pytrakt}")
        # Import module and check attributes via reflection
        spec = util.find_spec('trakt')
        click.echo("\n🔎 Module resolution")
        click.echo(f"  find_spec('trakt'): origin={getattr(spec, 'origin', None)} loader={type(getattr(spec, 'loader', None)).__name__ if spec and spec.loader else None}")
        mod = sys.modules.get('trakt')
        click.echo(f"  sys.modules['trakt']: path={getattr(mod, '__file__', None)}")

        top_level_ok = False
        core_ok = False
        try:
            from trakt import Trakt as _TopTrakt  # noqa: F401
            top_level_ok = True
        except Exception as ie:
            click.echo(f"  from trakt import Trakt: FAILED ({ie})")
        try:
            from trakt.core import Trakt as _CoreTrakt  # noqa: F401
            core_ok = True
        except Exception as ie:
            click.echo(f"  from trakt.core import Trakt: FAILED ({ie})")
        if top_level_ok:
            click.echo("  from trakt import Trakt: OK")
        if core_ok:
            click.echo("  from trakt.core import Trakt: OK")

        # Enumerate any installed modules/packages with 'trakt' in name
        import pkgutil
        click.echo("\n📚 Installed modules matching 'trakt'")
        count = 0
        for finder, name, ispkg in pkgutil.iter_modules():
            if 'trakt' in name.lower():
                count += 1
                origin = None
                try:
                    s = util.find_spec(name)
                    origin = getattr(s, 'origin', None)
                except Exception:
                    pass
                click.echo(f"  - {name} (pkg={ispkg}) origin={origin}")
        if count == 0:
            click.echo("  (none)")

        # Peek attributes of 'trakt' and 'trakt.core' if importable
        click.echo("\n🔍 Module attributes")
        try:
            import importlib
            m_trakt = importlib.import_module('trakt')
            attrs = dir(m_trakt)
            click.echo(f"  trakt: attrs={', '.join(sorted([a for a in attrs if not a.startswith('_')])[:30])}...")
        except Exception as ie:
            click.echo(f"  trakt: FAILED ({ie})")
        try:
            import importlib
            m_core = importlib.import_module('trakt.core')
            attrs = dir(m_core)
            click.echo(f"  trakt.core: attrs={', '.join(sorted([a for a in attrs if not a.startswith('_')])[:30])}...")
        except Exception as ie:
            click.echo(f"  trakt.core: FAILED ({ie})")
        # Env vars
        click.echo("\n🔧 Environment")
        click.echo(f"  TRAKT_CLIENT_ID set: {bool(os.getenv('TRAKT_CLIENT_ID'))}")
        click.echo(f"  TRAKT_CLIENT_SECRET set: {bool(os.getenv('TRAKT_CLIENT_SECRET'))}")
        # Show pytrakt config path
        try:
            from trakt.core import CONFIG_PATH
            click.echo(f"\npytrakt config: {CONFIG_PATH} ({'exists' if os.path.exists(CONFIG_PATH) else 'missing'})")
        except Exception:
            pass
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@match.command(name="evaluate")
@click.option("-n", "--limit", type=int, help="Limit number of shows to evaluate")
@click.option("-v", "--verbose", is_flag=True, help="Verbose output during evaluation")
def match_evaluate(limit: Optional[int], verbose: bool):
    """Evaluate matching results and show three tiers.

    Categorizes all matched shows into:
    1. EXACT matches (confidence >= 95%)
    2. CLOSE matches (confidence 70-95%)
    3. NO MATCHES (confidence < 70% or unmatched)

    Shows Viki title → Trakt title mapping with confidence scores.
    """
    try:
        evaluator = MatchingEvaluator()

        click.echo("📊 Evaluating matches...")
        if limit:
            click.echo(f"   Limit: {limit} shows")

        exact, close, no_match = evaluator.evaluate_all(limit=limit, verbose=verbose)

        # Print results
        evaluator.print_results(exact, close, no_match)

        # Print summary
        summary = evaluator.get_summary(exact, close, no_match)
        click.echo("\n📈 SUMMARY")
        click.echo(f"  Total shows: {summary['total']}")
        click.echo(f"  Exact matches: {summary['exact']} ({summary['exact_pct']:.1f}%)")
        click.echo(f"  Close matches: {summary['close']} ({summary['close_pct']:.1f}%)")
        click.echo(f"  Unmatched: {summary['unmatched']} ({summary['unmatched_pct']:.1f}%)")
        click.echo(f"  Total matched: {summary['total_matched']} ({summary['total_matched_pct']:.1f}%)")

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@match.command(name="aliases")
@click.option("--corpus", type=click.Path(path_type=Path), help="Path to corpus JSON (default: cached corpus)")
@click.option("--limit", "-n", type=int, help="Limit to N unmatched shows")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed matching info per show")
def match_aliases(corpus: Optional[Path], limit: Optional[int], verbose: bool):
    """Test TVDB and MDL alias matching on unmatched shows.

    Re-runs the matcher on unmatched shows from the corpus, focusing on:
    1. TVDB alias matching (enhanced alias lookup)
    2. MyDramaList (MDL) API resolution

    This helps identify shows that can be matched via alternate titles.
    """
    import json
    from .matcher import ShowMatcher

    try:
        # Load corpus
        if corpus is None:
            corpus = Path.home() / ".config" / "viki-trakt-sync" / "match_corpus.json"

        if not corpus.exists():
            click.echo(f"✗ Corpus not found: {corpus}", err=True)
            click.echo("  Build one with: dataset build --target 1000", err=True)
            sys.exit(1)

        with open(corpus) as f:
            data = json.load(f)

        items = data.get("items", [])

        # Filter to unmatched
        unmatched = [it for it in items if not (it.get("matched", {}).get("trakt_id"))]

        if limit:
            unmatched = unmatched[:limit]

        click.echo(f"\n🔍 Testing alias matching on {len(unmatched)} unmatched shows...\n")

        matcher = ShowMatcher()

        # Test each one
        newly_matched = []
        still_unmatched = []

        for idx, item in enumerate(unmatched, 1):
            viki_id = item["viki_id"]
            title = item["viki_titles"].get("en") or next(iter(item["viki_titles"].values()), viki_id)

            viki_show = {
                "id": viki_id,
                "titles": item.get("viki_titles", {}),
                "origin": item.get("origin", {}),
            }

            result = matcher.match(viki_show)

            if verbose:
                click.echo(f"[{idx}/{len(unmatched)}] {title}")

            if result.is_matched():
                newly_matched.append((result, title))
                if verbose:
                    click.echo(
                        f"  ✓ Matched: {result.trakt_title} (conf={result.match_confidence:.0%}, method={result.match_method})"
                    )
            else:
                still_unmatched.append((title, viki_id))
                if verbose:
                    click.echo(f"  ✗ Still unmatched")

        # Summary
        click.echo("\n" + "=" * 80)
        click.echo("ALIAS MATCHING RESULTS")
        click.echo("=" * 80)

        click.echo(f"\nTotal unmatched (tested): {len(unmatched)}")
        click.echo(f"Newly matched via aliases: {len(newly_matched)}")
        click.echo(f"Still unmatched: {len(still_unmatched)}")

        if newly_matched:
            click.echo("\n✅ NEWLY MATCHED VIA ALIASES:")
            for result, title in newly_matched:
                click.echo(
                    f"  • {title}"
                    f" → {result.trakt_title} (ID: {result.trakt_id}, conf={result.match_confidence:.0%}, via {result.match_method})"
                )

        if still_unmatched:
            click.echo(f"\n❌ STILL UNMATCHED ({len(still_unmatched)}):")
            for title, vid in still_unmatched[:20]:
                click.echo(f"  • {title} ({vid})")
            if len(still_unmatched) > 20:
                click.echo(f"  ... and {len(still_unmatched) - 20} more")

        click.echo("\n" + "=" * 80)

    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

