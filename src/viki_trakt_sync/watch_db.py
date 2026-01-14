"""Local DB for tracking watching/watched state (Peewee ORM only).

Persists snapshots from Viki "Continue Watching" and markers into
episode-level and show-level records so we don't lose progress when
Viki prunes history.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .models import init_models, Show, Episode, Scan, Snapshot, database

logger = logging.getLogger(__name__)


@dataclass
class EpisodeRecord:
    viki_video_id: str
    viki_container_id: str
    episode_number: Optional[int] = None
    duration: Optional[int] = None
    watched_seconds: Optional[int] = None
    credits_marker: Optional[int] = None
    progress_percent: Optional[float] = None
    is_watched: Optional[bool] = None
    last_watched_at: Optional[str] = None  # ISO8601
    source: str = "watchlist"  # watchlist | markers


class WatchDB:
    """Peewee-backed store of shows and episodes watch state."""

    def __init__(self):
        init_models()
        self.db_path = Path(database.database) if hasattr(database, "database") else None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close database connection."""
        if hasattr(database, 'close'):
            database.close()
        return False

    def upsert_show(
        self,
        viki_container_id: str,
        title: Optional[str] = None,
        type_: Optional[str] = None,
        origin_country: Optional[str] = None,
        origin_language: Optional[str] = None,
        trakt_id: Optional[int] = None,
        trakt_slug: Optional[str] = None,
        trakt_title: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with database.atomic():
            first_seen = now
            existing = Show.get_or_none(Show.viki_container_id == viki_container_id)
            if existing and existing.first_seen:
                first_seen = existing.first_seen

            (Show
             .insert(
                 viki_container_id=viki_container_id,
                 title=title,
                 type=type_,
                 origin_country=origin_country,
                 origin_language=origin_language,
                 trakt_id=trakt_id,
                 trakt_slug=trakt_slug,
                 trakt_title=trakt_title,
                 first_seen=first_seen,
                 last_seen=now,
                 last_updated=now,
             )
             .on_conflict(
                 conflict_target=[Show.viki_container_id],
                 preserve=[Show.first_seen],
                 update={
                     Show.title: Show.title if title is None else title,
                     Show.type: Show.type if type_ is None else type_,
                     Show.origin_country: Show.origin_country if origin_country is None else origin_country,
                     Show.origin_language: Show.origin_language if origin_language is None else origin_language,
                     Show.trakt_id: Show.trakt_id if trakt_id is None else trakt_id,
                     Show.trakt_slug: Show.trakt_slug if trakt_slug is None else trakt_slug,
                     Show.trakt_title: Show.trakt_title if trakt_title is None else trakt_title,
                     Show.last_seen: now,
                     Show.last_updated: now,
                 }
             )
             .execute())

    def upsert_episode(self, rec: EpisodeRecord) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with database.atomic():
            (Episode
             .insert(
                 viki_video_id=rec.viki_video_id,
                 viki_container_id=rec.viki_container_id,
                 episode_number=rec.episode_number,
                 duration=rec.duration,
                 watched_seconds=rec.watched_seconds,
                 credits_marker=rec.credits_marker,
                 progress_percent=rec.progress_percent,
                 is_watched=(int(rec.is_watched) if rec.is_watched is not None else None),
                 last_watched_at=rec.last_watched_at,
                 source=rec.source,
                 updated_at=now,
             )
             .on_conflict(
                 conflict_target=[Episode.viki_video_id],
                 update={
                     Episode.viki_container_id: rec.viki_container_id,
                     Episode.episode_number: Episode.episode_number if rec.episode_number is None else rec.episode_number,
                     Episode.duration: Episode.duration if rec.duration is None else rec.duration,
                     Episode.watched_seconds: Episode.watched_seconds if rec.watched_seconds is None else rec.watched_seconds,
                     Episode.credits_marker: Episode.credits_marker if rec.credits_marker is None else rec.credits_marker,
                     Episode.progress_percent: Episode.progress_percent if rec.progress_percent is None else rec.progress_percent,
                     Episode.is_watched: Episode.is_watched if rec.is_watched is None else int(rec.is_watched),
                     Episode.last_watched_at: Episode.last_watched_at if rec.last_watched_at is None else rec.last_watched_at,
                     Episode.source: rec.source,
                     Episode.updated_at: now,
                 }
             )
             .execute())

    def record_scan(self, source: str, items: int) -> None:
        with database.atomic():
            Scan.insert(
                scanned_at=datetime.now(timezone.utc).isoformat(),
                source=source,
                items=items,
            ).execute()

    def save_snapshot(self, payload: Dict, source: str) -> None:
        with database.atomic():
            Snapshot.insert(
                created_at=datetime.now(timezone.utc).isoformat(),
                source=source,
                payload=json.dumps(payload),
            ).execute()

    def stats(self) -> Dict[str, int]:
        return {
            "shows": Show.select().count(),
            "episodes": Episode.select().count(),
            "scans": Scan.select().count(),
        }

    def get_show_progress(self, viki_container_id: str) -> Dict:
        """Get watched/watching status for a show.
        
        Returns show metadata plus episode progress breakdown.
        """
        try:
            show = Show.get(Show.viki_container_id == viki_container_id)
        except Show.DoesNotExist:
            return None
        
        episodes = Episode.select().where(Episode.viki_container_id == viki_container_id)
        
        total_eps = episodes.count()
        watched_eps = episodes.where(Episode.is_watched == 1).count()
        in_progress_eps = episodes.where(
            (Episode.is_watched.is_null(False)) & (Episode.is_watched == 0)
        ).count()
        
        # Get last watched episode
        last_ep = (
            episodes
            .where(Episode.last_watched_at.is_null(False))
            .order_by(Episode.last_watched_at.desc())
            .first()
        )
        
        return {
            "show_id": show.viki_container_id,
            "title": show.title,
            "trakt_id": show.trakt_id,
            "total_episodes": total_eps,
            "watched_episodes": watched_eps,
            "in_progress_episodes": in_progress_eps,
            "last_watched_ep": last_ep.episode_number if last_ep else None,
            "last_watched_at": last_ep.last_watched_at if last_ep else None,
        }
    
    def get_all_progress(self) -> list[Dict]:
        """Get all shows with their watch progress."""
        shows = Show.select().order_by(Show.last_seen.desc())
        return [
            self.get_show_progress(show.viki_container_id)
            for show in shows
        ]
    
    def get_show_episodes(self, viki_container_id: str) -> list[Dict]:
        """Get all episode watch markers for a specific show.
        
        Args:
            viki_container_id: Viki container ID
        
        Returns:
            List of episode records with watch progress
        """
        episodes = Episode.select().where(
            Episode.viki_container_id == viki_container_id
        ).order_by(Episode.episode_number)
        
        return [
            {
                "video_id": ep.viki_video_id,
                "episode_number": ep.episode_number,
                "duration": ep.duration,
                "watched_seconds": ep.watched_seconds,
                "progress_percent": ep.progress_percent,
                "is_watched": bool(ep.is_watched) if ep.is_watched is not None else None,
                "last_watched_at": ep.last_watched_at,
                "credits_marker": ep.credits_marker,
            }
            for ep in episodes
        ]

    def ingest_watch_markers(self, markers: Dict, source: str = "watchlist") -> int:
        count = 0
        markers_map = markers.get("markers", {})
        for container_id, videos in markers_map.items():
            for video_id, marker in videos.items():
                rec = EpisodeRecord(
                    viki_video_id=str(video_id),
                    viki_container_id=str(container_id),
                    episode_number=marker.get("episode"),
                    duration=marker.get("duration"),
                    watched_seconds=marker.get("watch_marker"),
                    credits_marker=marker.get("credits_marker"),
                    progress_percent=None,
                    is_watched=None,
                    last_watched_at=marker.get("timestamp"),
                    source=source,
                )
                if rec.duration and rec.watched_seconds is not None and rec.duration > 0:
                    rec.progress_percent = rec.watched_seconds / rec.duration * 100.0
                if rec.watched_seconds is not None and rec.duration:
                    credits = rec.credits_marker or rec.duration
                    rec.is_watched = bool(
                        rec.watched_seconds >= credits or rec.watched_seconds >= rec.duration * 0.9
                    )
                self.upsert_episode(rec)
                count += 1
        self.record_scan(source=source, items=count)
        return count
