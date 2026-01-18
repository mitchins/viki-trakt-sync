"""Sync Workflow - orchestrates the full Viki → Trakt sync.

ARCHITECTURE: Watch status is the PRIMARY goal.

Flow (watch-status-first):
  1. Fetch watch status (what's actually been watched) from Viki
  2. For each watched show, enrich with episode metadata
  3. Match shows to Trakt
  4. Sync watch status to Trakt

This ensures the watch status is accurate and primary, with all other
operations (matching, metadata) supporting that core goal.

Implements the Command/Orchestrator pattern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from typing import Callable, List, Optional

from ..adapters import VikiAdapter, TraktAdapter, MetadataAdapter
from ..adapters.viki import VikiBillboardItem, VikiEpisode
from ..adapters.trakt import TraktEpisode
from ..repository import Repository
from ..models import Show

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    shows_fetched: int = 0
    shows_refreshed: int = 0
    episodes_fetched: int = 0
    matches_attempted: int = 0
    matches_found: int = 0
    episodes_synced: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class SyncWorkflow:
    """Orchestrates the full sync workflow.
    
    Coordinates between:
    - VikiAdapter: Fetches watch data
    - TraktAdapter: Syncs to Trakt
    - MetadataAdapter: Helps with matching
    - Repository: Persists local state
    """
    
    def __init__(
        self,
        viki: VikiAdapter,
        trakt: TraktAdapter,
        metadata: Optional[MetadataAdapter] = None,
        repository: Optional[Repository] = None,
        matcher: Optional[Callable] = None,  # Optional matcher function
    ):
        """Initialize workflow.
        
        Args:
            viki: Viki API adapter
            trakt: Trakt API adapter
            metadata: Metadata adapter (optional)
            repository: Data repository (default: new instance)
            matcher: Function to match shows (from matcher.py)
        """
        self.viki = viki
        self.trakt = trakt
        self.metadata = metadata or MetadataAdapter()
        self.repo = repository or Repository()
        self.matcher = matcher
    
    def run(
        self,
        force_refresh: bool = False,
        dry_run: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> SyncResult:
        """Execute the full sync workflow (WATCH-STATUS-FIRST).
        
        ARCHITECTURE: Watch status is PRIMARY. This method follows the
        watch-status-first flow:
        
          1. Fetch watch status (what's actually been watched) from Viki
          2. For each watched show, enrich with episode metadata
          3. Match unmatched shows to Trakt
          4. Sync watch status to Trakt
        
        Watch status is the SOURCE OF TRUTH and GOAL. Everything else
        (matching, metadata, billboard) enables accurate watch syncing.
        
        Args:
            force_refresh: Force refresh all shows (ignore billboard hash)
            dry_run: Preview only, don't sync to Trakt
            progress_callback: Optional callback for progress updates
            
        Returns:
            SyncResult with operation counts
        """
        result = SyncResult()
        
        def log_progress(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)
        
        # STEP 1 (PRIMARY): Fetch watch status - SOURCE OF TRUTH
        # Uses ?from=timestamp for incremental syncs (ONE global call)
        log_progress("Fetching watch status from Viki...")
        try:
            # Get last fetch timestamp for incremental sync
            # IMPORTANT: Default to 1 (ALL HISTORY) on first sync, never start incremental
            from_timestamp = self.repo.get_last_watch_markers_timestamp()
            
            # Force from=1 on first sync to ensure we get complete history
            # This is critical - if we miss the initial sync, we're blind to old watches forever
            is_first_sync = from_timestamp == 1
            if is_first_sync:
                log_progress("First sync - fetching all watch history from beginning (from=1)")
            else:
                log_progress(f"Incremental sync from timestamp {from_timestamp}")
            
            # Fetch watch status (ONE global call with ?from=timestamp)
            watch_status, current_timestamp = self.viki.get_watch_status_with_metadata(
                from_timestamp=from_timestamp
            )
            
            if not watch_status:
                log_progress("No new watch history found")
                # Still update timestamp to avoid re-fetching
                self.repo.set_last_watch_markers_timestamp(current_timestamp)
                return result
            
            result.shows_fetched = len(watch_status)
            total_episodes = sum(len(videos) for videos in watch_status.values())
            log_progress(f"Found watch status for {result.shows_fetched} shows, {total_episodes} episodes")
            
            # Save timestamp for next incremental sync
            self.repo.set_last_watch_markers_timestamp(current_timestamp)
            
        except Exception as e:
            result.errors.append(f"Failed to fetch watch status: {e}")
            logger.error(result.errors[-1])
            return result
        
        # STEP 2: Upsert shows from watch status
        for viki_id, videos in watch_status.items():
            # Get show info from billboard to get titles
            try:
                container = self.viki.get_container(viki_id)
                if container:
                    title = self._extract_title(container)
                    show_type = container.get("type", "series")
                    origin = container.get("origin", {})
                    
                    self.repo.upsert_show(
                        viki_id=viki_id,
                        title=title,
                        type_=show_type,
                        origin_country=origin.get("country"),
                        origin_language=origin.get("language"),
                    )
                else:
                    # Fallback if container fetch fails
                    self.repo.upsert_show(
                        viki_id=viki_id,
                        title=f"Show {viki_id}",
                        type_="series",
                    )
            except Exception as e:
                logger.warning(f"Could not fetch container {viki_id}: {e}")
                result.errors.append(f"Container fetch failed for {viki_id}: {e}")
        
        # STEP 3: Upsert episodes with watch status
        for viki_id, videos in watch_status.items():
            for video_id, watch_data in videos.items():
                self.repo.upsert_episode(
                    viki_video_id=video_id,
                    viki_id=viki_id,
                    episode_number=watch_data["episode_number"],
                    duration=watch_data["duration"],
                    watched_seconds=watch_data["watched_seconds"],
                    credits_marker=watch_data.get("credits_marker"),
                )
                result.episodes_fetched += 1
        
        log_progress(f"Processed {result.episodes_fetched} episodes with watch status")
        
        # STEP 4: Match unmatched shows
        unmatched = self.repo.get_unmatched_shows()
        if unmatched:
            log_progress(f"Matching {len(unmatched)} unmatched shows...")
            for show in unmatched:
                result.matches_attempted += 1
                if self._try_match(show):
                    result.matches_found += 1
        
        # STEP 5: Sync watch status to Trakt
        if not dry_run:
            unsynced = self.repo.get_unsynced_episodes()
            if unsynced:
                log_progress(f"Syncing {len(unsynced)} episodes to Trakt...")
                result.episodes_synced = self._sync_to_trakt(unsynced)
            else:
                log_progress("All episodes already synced")
        else:
            unsynced = self.repo.get_unsynced_episodes()
            log_progress(f"[DRY RUN] Would sync {len(unsynced)} episodes")
        
        # Log sync
        self.repo.log_sync(
            operation="sync",
            shows_processed=result.shows_fetched,
            episodes_synced=result.episodes_synced,
            status="success" if not result.errors else "partial",
            notes=f"Errors: {len(result.errors)}" if result.errors else None,
        )
        
        log_progress("Sync complete!")
        return result
    
    def _upsert_show(self, item: VikiBillboardItem) -> Show:
        """Create or update a show in the repository."""
        return self.repo.upsert_show(
            viki_id=item.viki_id,
            title=item.title,
            type_=item.type,
            origin_country=item.origin_country,
            origin_language=item.origin_language,
        )
    
    def _upsert_episodes(self, viki_id: str, episodes: List[VikiEpisode]) -> None:
        """Create or update episodes in the repository."""
        for ep in episodes:
            self.repo.upsert_episode(
                viki_video_id=ep.viki_video_id,
                viki_id=viki_id,
                episode_number=ep.episode_number,
                duration=ep.duration,
                credits_marker=ep.credits_marker,
            )
    
    def _update_watch_progress(self, progress: dict) -> None:
        """Update watch progress for all episodes.
        
        Args:
            progress: Dict mapping container_id -> video_id -> watched_seconds
        """
        for container_id, videos in progress.items():
            for video_id, watched_seconds in videos.items():
                ep = self.repo.get_episode(video_id)
                if ep:
                    # Get values from Peewee model instance
                    duration = getattr(ep, 'duration', None) or 0
                    credits_marker = getattr(ep, 'credits_marker', None) or 0
                    
                    # Update episode with watched progress
                    # The repository will calculate is_watched automatically
                    self.repo.upsert_episode(
                        viki_video_id=video_id,
                        viki_id=container_id,
                        watched_seconds=int(watched_seconds) if watched_seconds else 0,
                        duration=duration,
                        credits_marker=credits_marker,
                        last_watched_at=datetime.now(timezone.utc),
                    )
                    
                    logger.debug(f"Updated episode {video_id}: {watched_seconds}s watched")
    
    def _try_match(self, show: Show) -> bool:
        """Try to match a show to Trakt.
        
        Returns True if match found.
        """
        if self.matcher is None:
            # No matcher provided - try simple search
            return self._simple_match(show)
        
        # Use provided matcher function
        try:
            viki_show = {
                "id": show.viki_id,
                "viki_id": show.viki_id,
                "titles": {"en": show.title},
                "origin": {
                    "country": show.origin_country,
                    "language": show.origin_language,
                },
            }
            result = self.matcher(viki_show)
            
            if result and result.is_matched():
                self.repo.save_match(
                    viki_id=show.viki_id,
                    trakt_id=result.trakt_id,
                    trakt_slug=result.trakt_slug,
                    trakt_title=result.trakt_title,
                    source="AUTO",
                    confidence=result.match_confidence,
                    method=result.match_method,
                )
                return True
            else:
                # Record no-match
                self.repo.save_match(
                    viki_id=show.viki_id,
                    trakt_id=None,
                    trakt_slug=None,
                    trakt_title=None,
                    source="NONE",
                    notes="No match found",
                )
                return False
                
        except Exception as e:
            logger.error(f"Match failed for {show.viki_id}: {e}")
            return False
    
    def _simple_match(self, show: Show) -> bool:
        """Simple matching using just Trakt search."""
        results = self.trakt.search(show.title or "")
        if not results:
            return False
        
        # Take first high-confidence result
        best = results[0]
        if best.score < 50:
            return False
        
        self.repo.save_match(
            viki_id=show.viki_id,
            trakt_id=best.show.trakt_id,
            trakt_slug=best.show.slug,
            trakt_title=best.show.title,
            source="AUTO",
            confidence=best.score / 100.0,
            method="simple_search",
        )
        return True
    
    def _extract_title(self, container: Dict[str, Any]) -> str:
        """Extract best title from container data."""
        titles = container.get("titles", {})
        # Prefer English, then original
        if isinstance(titles, dict):
            return (
                titles.get("en") or 
                titles.get("en-us") or 
                titles.get("ko") or 
                titles.get("th") or 
                list(titles.values())[0] if titles else f"Show {container.get('id', 'unknown')}"
            )
        return str(titles) if titles else f"Show {container.get('id', 'unknown')}"
    
    def _sync_to_trakt(self, episodes: List) -> int:
        """Sync watched episodes to Trakt.
        
        Returns count of synced episodes.
        """
        # Group by show and build Trakt episodes
        trakt_episodes = []
        
        for ep in episodes:
            show = self.repo.get_show(ep.show_id) if hasattr(ep, 'show_id') else ep.show
            if not show or not show.trakt_id:
                continue
            
            # Map Viki episode to Trakt (assume season 1 for Asian dramas)
            trakt_episodes.append(TraktEpisode(
                show_trakt_id=show.trakt_id,
                season=1,  # Most Viki shows are single-season
                episode=ep.episode_number or 1,
                watched_at=ep.last_watched_at,
            ))
        
        if not trakt_episodes:
            return 0
        
        result = self.trakt.sync_watched(trakt_episodes)
        
        # Mark as synced when episodes are added OR already existing (idempotent)
        # If result shows items were synced, mark all as done
        synced_count = result.get("added", 0) + result.get("existing", 0)
        if synced_count > 0:
            self.repo.mark_episodes_synced(episodes)
            return len(episodes)  # Return total submitted, not just newly added
        
        return 0
