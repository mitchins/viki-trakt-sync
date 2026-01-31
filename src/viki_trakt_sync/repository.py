"""Repository - single data access layer for all persistence.

Implements the Repository pattern to provide a clean interface
to the Peewee models, handling all database operations.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import Show, Episode, Match, SyncLog, SyncMetadata, database, init_db


class Repository:
    """Single source of truth for all data access."""
    
    def __init__(self):
        """Initialize repository and ensure DB is ready."""
        init_db()
    
    # --- Show Operations ---
    
    def get_show(self, viki_id: str) -> Optional[Show]:
        """Get a show by Viki ID."""
        return Show.get_or_none(Show.viki_id == viki_id)
    
    def get_all_shows(self) -> List[Show]:
        """Get all shows."""
        return list(Show.select())
    
    def upsert_show(
        self,
        viki_id: str,
        title: Optional[str] = None,
        type_: Optional[str] = None,
        origin_country: Optional[str] = None,
        origin_language: Optional[str] = None,
    ) -> Show:
        """Create or update a show."""
        now = datetime.now(timezone.utc)
        show, created = Show.get_or_create(
            viki_id=viki_id,
            defaults={
                'title': title,
                'type': type_,
                'origin_country': origin_country,
                'origin_language': origin_language,
                'first_seen_at': now,
                'last_fetched_at': now,
            }
        )
        
        if not created:
            # Update existing
            if title:
                show.title = title
            if type_:
                show.type = type_
            if origin_country:
                show.origin_country = origin_country
            if origin_language:
                show.origin_language = origin_language
            show.last_fetched_at = now
            show.save()
        
        return show
    
    def get_unmatched_shows(self) -> List[Show]:
        """Get shows without a Trakt match."""
        return list(Show.select().where(
            (Show.trakt_id.is_null()) | (Show.match_source == 'NONE')
        ))
    
    def get_matched_shows(self) -> List[Show]:
        """Get shows with a Trakt match."""
        return list(Show.select().where(
            Show.trakt_id.is_null(False) & (Show.match_source != 'NONE')
        ))
    
    # --- Episode Operations ---
    
    def get_episode(self, viki_video_id: str) -> Optional[Episode]:
        """Get an episode by Viki video ID."""
        return Episode.get_or_none(Episode.viki_video_id == viki_video_id)
    
    def get_show_episodes(self, viki_id: str) -> List[Episode]:
        """Get all episodes for a show, ordered by episode number."""
        return list(
            Episode.select()
            .where(Episode.show == viki_id)
            .order_by(Episode.episode_number)
        )
    
    def upsert_episode(
        self,
        viki_video_id: str,
        viki_id: str,
        episode_number: Optional[int] = None,
        duration: Optional[int] = None,
        watched_seconds: Optional[int] = None,
        credits_marker: Optional[int] = None,
        last_watched_at: Optional[datetime] = None,
    ) -> Episode:
        """Create or update an episode."""
        # Calculate progress
        progress_percent = None
        is_watched = False
        
        if duration and watched_seconds is not None:
            progress_percent = (watched_seconds / duration) * 100
            credits = credits_marker or duration
            is_watched = watched_seconds >= credits or watched_seconds >= duration * 0.9
        
        episode, created = Episode.get_or_create(
            viki_video_id=viki_video_id,
            defaults={
                'show': viki_id,
                'episode_number': episode_number,
                'duration': duration,
                'watched_seconds': watched_seconds,
                'credits_marker': credits_marker,
                'progress_percent': progress_percent,
                'is_watched': is_watched,
                'last_watched_at': last_watched_at,
            }
        )
        
        if not created:
            # Update existing
            if episode_number is not None:
                episode.episode_number = episode_number
            if duration is not None:
                episode.duration = duration
            if watched_seconds is not None:
                episode.watched_seconds = watched_seconds
                # Recalculate progress
                if episode.duration:
                    episode.progress_percent = (watched_seconds / episode.duration) * 100
                    credits = episode.credits_marker or episode.duration
                    episode.is_watched = watched_seconds >= credits or watched_seconds >= episode.duration * 0.9
            if credits_marker is not None:
                episode.credits_marker = credits_marker
            if last_watched_at is not None:
                episode.last_watched_at = last_watched_at
            episode.save()
        
        return episode
    
    def get_unsynced_episodes(self) -> List[Episode]:
        """Get episodes that are watched but not synced to Trakt."""
        return list(
            Episode.select()
            .join(Show)
            .where(
                (Episode.is_watched == True) &
                (Episode.synced_to_trakt == False) &
                (Show.trakt_id.is_null(False))
            )
        )
    
    def mark_episodes_synced(self, episodes: List[Episode], session_id: Optional[int] = None) -> int:
        """Mark episodes as synced to Trakt (atomic operation).
        
        Args:
            episodes: Episodes to mark as synced
            session_id: SyncLog.id to link for undo capability
        """
        if not episodes:
            return 0
        
        now = datetime.now(timezone.utc)
        
        # Wrap in transaction for atomicity
        try:
            with database.atomic():
                for ep in episodes:
                    ep.synced_to_trakt = True
                    ep.synced_at = now
                    ep.sync_session_id = session_id
                    ep.save()
        except Exception as e:
            logger.error(f"Failed to mark {len(episodes)} episodes as synced: {e}")
            return 0
        
        return len(episodes)
    
    def undo_sync(self, session_id: int) -> int:
        """Undo a sync session by clearing sync flags for all episodes in that session.
        
        Args:
            session_id: SyncLog.id to undo
            
        Returns:
            Number of episodes reverted
        """
        try:
            with database.atomic():
                count = (
                    Episode.update(
                        synced_to_trakt=False,
                        synced_at=None,
                        sync_session_id=None,
                    )
                    .where(Episode.sync_session_id == session_id)
                    .execute()
                )
            logger.info(f"Reverted {count} episodes from sync session {session_id}")
            return count
        except Exception as e:
            logger.error(f"Failed to undo sync session {session_id}: {e}")
            return 0
    
    def get_sync_session_episodes(self, session_id: int) -> List[Episode]:
        """Get all episodes synced in a specific session."""
        return list(
            Episode.select()
            .join(Show)
            .where(Episode.sync_session_id == session_id)
        )
    
    # --- Match Operations ---
    
    def save_match(
        self,
        viki_id: str,
        trakt_id: Optional[int],
        trakt_slug: Optional[str],
        trakt_title: Optional[str],
        source: str,  # AUTO, MANUAL, NONE
        confidence: Optional[float] = None,
        method: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Match:
        """Save a match result and update the Show."""
        # Create match record
        match = Match.create(
            viki_id=viki_id,
            trakt_id=trakt_id,
            trakt_slug=trakt_slug,
            trakt_title=trakt_title,
            source=source,
            confidence=confidence,
            method=method,
            notes=notes,
        )
        
        # Update the Show with match info
        show = self.get_show(viki_id)
        if show:
            show.trakt_id = trakt_id
            show.trakt_slug = trakt_slug
            show.trakt_title = trakt_title
            show.match_source = source
            show.match_confidence = confidence
            show.match_method = method
            show.save()
        
        return match
    
    def get_match(self, viki_id: str) -> Optional[Match]:
        """Get the most recent match for a show."""
        return (
            Match.select()
            .where(Match.viki_id == viki_id)
            .order_by(Match.created_at.desc())
            .first()
        )
    
    def clear_match(self, viki_id: str) -> None:
        """Clear match for a show (set to NONE)."""
        show = self.get_show(viki_id)
        if show:
            show.trakt_id = None
            show.trakt_slug = None
            show.trakt_title = None
            show.match_source = 'NONE'
            show.match_confidence = None
            show.match_method = None
            show.save()
    
    # --- Billboard Hash (Change Detection) ---
    
    def compute_billboard_hash(self, last_video_id: str, last_watched_at: str) -> str:
        """Compute hash for change detection."""
        return hashlib.md5(
            f"{last_video_id}:{last_watched_at}".encode()
        ).hexdigest()
    
    def needs_refresh(self, show: Show, new_hash: str) -> bool:
        """Check if show needs episode refresh based on billboard hash."""
        return show.billboard_hash != new_hash
    
    def update_billboard_hash(self, viki_id: str, hash_value: str) -> None:
        """Update the billboard hash for a show."""
        show = self.get_show(viki_id)
        if show:
            show.billboard_hash = hash_value
            show.save()
    
    # --- Sync Log ---
    
    def log_sync(
        self,
        operation: str,
        shows_processed: int = 0,
        episodes_synced: int = 0,
        status: str = 'success',
        notes: Optional[str] = None,
    ) -> SyncLog:
        """Log a sync operation."""
        return SyncLog.create(
            operation=operation,
            shows_processed=shows_processed,
            episodes_synced=episodes_synced,
            status=status,
            notes=notes,
        )
    
    def get_last_sync(self) -> Optional[SyncLog]:
        """Get the most recent sync log entry."""
        return (
            SyncLog.select()
            .order_by(SyncLog.timestamp.desc())
            .first()
        )
    
    # --- Statistics ---
    
    def get_stats(self) -> Dict[str, Any]:
        """Get repository statistics."""
        total_shows = Show.select().count()
        matched_shows = Show.select().where(Show.trakt_id.is_null(False)).count()
        unmatched_shows = total_shows - matched_shows
        
        total_episodes = Episode.select().count()
        watched_episodes = Episode.select().where(Episode.is_watched == True).count()
        synced_episodes = Episode.select().where(Episode.synced_to_trakt == True).count()
        
        last_sync = self.get_last_sync()
        
        return {
            'total_shows': total_shows,
            'matched_shows': matched_shows,
            'unmatched_shows': unmatched_shows,
            'total_episodes': total_episodes,
            'watched_episodes': watched_episodes,
            'synced_episodes': synced_episodes,
            'pending_sync': watched_episodes - synced_episodes,
            'last_sync': last_sync.timestamp if last_sync else None,
            'last_sync_status': last_sync.status if last_sync else None,
        }
    
    # --- Watch Progress ---
    
    def get_show_progress(self, viki_id: str) -> Optional[Dict[str, Any]]:
        """Get watch progress for a show."""
        show = self.get_show(viki_id)
        if not show:
            return None
        
        episodes = self.get_show_episodes(viki_id)
        total = len(episodes)
        watched = sum(1 for e in episodes if e.is_watched)
        in_progress = sum(1 for e in episodes if e.progress_percent and e.progress_percent > 0 and not e.is_watched)
        
        return {
            'viki_id': viki_id,
            'title': show.title,
            'trakt_id': show.trakt_id,
            'trakt_title': show.trakt_title,
            'match_source': show.match_source,
            'total_episodes': total,
            'watched_episodes': watched,
            'in_progress_episodes': in_progress,
            'episodes': [
                {
                    'viki_video_id': e.viki_video_id,
                    'episode_number': e.episode_number,
                    'duration': e.duration,
                    'watched_seconds': e.watched_seconds,
                    'progress_percent': e.progress_percent,
                    'is_watched': e.is_watched,
                    'last_watched_at': e.last_watched_at,
                    'synced_to_trakt': e.synced_to_trakt,
                }
                for e in episodes
            ],
        }
    
    def get_all_progress(self) -> List[Dict[str, Any]]:
        """Get watch progress for all shows."""
        shows = self.get_all_shows()
        return [self.get_show_progress(s.viki_id) for s in shows]
    
    # --- Metadata Operations ---
    
    def get_metadata(self, key: str) -> Optional[str]:
        """Get metadata value by key."""
        meta = SyncMetadata.get_or_none(SyncMetadata.key == key)
        return meta.value if meta else None
    
    def set_metadata(self, key: str, value: str) -> None:
        """Set metadata value."""
        now = datetime.now(timezone.utc)
        SyncMetadata.insert(
            key=key,
            value=value,
            updated_at=now
        ).on_conflict(
            conflict_target=[SyncMetadata.key],
            update={'value': value, 'updated_at': now}
        ).execute()
    
    def get_last_watch_markers_timestamp(self) -> int:
        """Get the last timestamp used for fetching watch markers.
        
        CRITICAL: This defaults to 1 (ALL HISTORY) on first sync.
        Never returns 0 or None - always returns a valid timestamp.
        Returning anything else would cause incomplete initial syncs.
        
        Returns:
            Unix timestamp (seconds), always >= 1
        """
        ts = self.get_metadata('last_watch_markers_timestamp')
        # Always default to 1 (all history) if not set
        # This is a safety net - first sync MUST get complete history
        return int(ts) if ts else 1
    
    def set_last_watch_markers_timestamp(self, timestamp: int) -> None:
        """Set the last timestamp for watch markers fetch."""
        self.set_metadata('last_watch_markers_timestamp', str(timestamp))
