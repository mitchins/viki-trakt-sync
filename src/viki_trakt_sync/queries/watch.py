"""Watch Query - view watch status from local cache.

Reads the local database to show watch progress
without hitting external APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..repository import Repository


@dataclass
class ShowWatchStatus:
    """Watch status for a single show."""
    viki_id: str
    title: str
    trakt_id: Optional[int]
    trakt_title: Optional[str]
    match_source: Optional[str]
    total_episodes: int
    watched_episodes: int
    in_progress_episodes: int
    pending_sync: int
    
    @property
    def progress_percent(self) -> float:
        """Calculate overall progress percentage."""
        if self.total_episodes == 0:
            return 0.0
        return (self.watched_episodes / self.total_episodes) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if show is fully watched."""
        return self.total_episodes > 0 and self.watched_episodes >= self.total_episodes


@dataclass  
class EpisodeWatchStatus:
    """Watch status for a single episode."""
    viki_video_id: str
    episode_number: int
    duration: int
    watched_seconds: int
    progress_percent: float
    is_watched: bool
    synced_to_trakt: bool


class WatchQuery:
    """Query for viewing watch status from local cache."""
    
    def __init__(self, repository: Optional[Repository] = None):
        """Initialize query.
        
        Args:
            repository: Data repository (default: new instance)
        """
        self.repo = repository or Repository()
    
    def all_shows(self) -> List[ShowWatchStatus]:
        """Get watch status for all shows.
        
        Returns:
            List of ShowWatchStatus sorted by title
        """
        shows = self.repo.get_all_shows()
        statuses = []
        
        for show in shows:
            episodes = self.repo.get_show_episodes(str(show.viki_id))
            
            watched = sum(1 for e in episodes if e.is_watched)
            in_progress = sum(1 for e in episodes if e.progress_percent and float(e.progress_percent) > 0 and not e.is_watched)
            pending = sum(1 for e in episodes if e.is_watched and not e.synced_to_trakt)
            
            statuses.append(ShowWatchStatus(
                viki_id=str(show.viki_id),
                title=str(show.title) if show.title else "Unknown",
                trakt_id=int(show.trakt_id) if show.trakt_id else None,
                trakt_title=str(show.trakt_title) if show.trakt_title else None,
                match_source=str(show.match_source) if show.match_source else None,
                total_episodes=len(episodes),
                watched_episodes=watched,
                in_progress_episodes=in_progress,
                pending_sync=pending,
            ))
        
        return sorted(statuses, key=lambda s: s.title.lower())
    
    def show_detail(self, viki_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed watch status for a single show.
        
        Args:
            viki_id: Viki container ID
            
        Returns:
            Dict with show info and episode list, or None
        """
        show = self.repo.get_show(viki_id)
        if not show:
            return None
        
        episodes = self.repo.get_show_episodes(viki_id)
        
        episode_statuses = []
        for ep in episodes:
            episode_statuses.append(EpisodeWatchStatus(
                viki_video_id=str(ep.viki_video_id),
                episode_number=int(ep.episode_number) if ep.episode_number else 0,
                duration=int(ep.duration) if ep.duration else 0,
                watched_seconds=int(ep.watched_seconds) if ep.watched_seconds else 0,
                progress_percent=float(ep.progress_percent) if ep.progress_percent else 0.0,
                is_watched=bool(ep.is_watched),
                synced_to_trakt=bool(ep.synced_to_trakt),
            ))
        
        watched = sum(1 for e in episode_statuses if e.is_watched)
        pending = sum(1 for e in episode_statuses if e.is_watched and not e.synced_to_trakt)
        
        return {
            "viki_id": viki_id,
            "title": str(show.title) if show.title else "Unknown",
            "type": str(show.type) if show.type else None,
            "trakt_id": int(show.trakt_id) if show.trakt_id else None,
            "trakt_slug": str(show.trakt_slug) if show.trakt_slug else None,
            "trakt_title": str(show.trakt_title) if show.trakt_title else None,
            "match_source": str(show.match_source) if show.match_source else None,
            "match_confidence": float(show.match_confidence) if show.match_confidence else None,
            "match_method": str(show.match_method) if show.match_method else None,
            "total_episodes": len(episode_statuses),
            "watched_episodes": watched,
            "pending_sync": pending,
            "episodes": episode_statuses,
        }
    
    def in_progress(self) -> List[ShowWatchStatus]:
        """Get shows that are currently being watched (not complete).
        
        Returns:
            List of shows with partial progress
        """
        all_shows = self.all_shows()
        return [s for s in all_shows if s.watched_episodes > 0 and not s.is_complete]
    
    def pending_sync(self) -> List[ShowWatchStatus]:
        """Get shows with episodes pending sync to Trakt.
        
        Returns:
            List of shows with unsynced watched episodes
        """
        all_shows = self.all_shows()
        return [s for s in all_shows if s.pending_sync > 0]
