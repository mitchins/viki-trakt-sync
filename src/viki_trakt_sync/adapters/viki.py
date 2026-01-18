"""Viki API Adapter.

Provides a clean interface to Viki's API.

ARCHITECTURE: Watch status is the primary data source and goal.
  - Watch markers endpoint (/api/vw_watch_markers) is the SOURCE OF TRUTH
  - Accepts ?from=<unix_timestamp> parameter for incremental syncs  
  - Returns ALL watch markers >= that timestamp in ONE global list
  - Episodes are fetched ONLY to enrich watch status with metadata
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class VikiBillboardItem:
    """A show from the Viki billboard (watchlist)."""
    viki_id: str
    title: str
    type: str  # "series" or "movie"
    origin_country: Optional[str] = None
    origin_language: Optional[str] = None
    last_video_id: Optional[str] = None
    last_watched_at: Optional[str] = None  # ISO timestamp for hash


@dataclass
class VikiEpisode:
    """An episode from Viki."""
    viki_video_id: str
    viki_id: str  # Container ID
    episode_number: int
    duration: int  # seconds
    watched_seconds: int = 0
    credits_marker: Optional[int] = None
    last_watched_at: Optional[datetime] = None


class VikiClientProtocol(Protocol):
    """Protocol defining what we need from a Viki client."""
    
    def get_watchlist(self, page: int = 1, per_page: int = 30) -> Dict[str, Any]: ...
    def get_container(self, container_id: str) -> Dict[str, Any]: ...
    def get_episodes(self, container_id: str, page: int = 1, per_page: int = 100) -> Dict[str, Any]: ...
    def get_watch_markers(self, from_timestamp: int = 1) -> Dict[str, Any]: ...
    def get_watchlaters(self, ids_only: bool = True, page: int = 1, per_page: int = 100) -> Dict[str, Any]: ...


class VikiAdapter:
    """Adapter for Viki API interactions.
    
    Wraps VikiClient to provide a clean domain-focused interface.
    """
    
    def __init__(self, client: VikiClientProtocol):
        """Initialize adapter with a Viki client.
        
        Args:
            client: VikiClient instance (or mock for testing)
        """
        self.client = client
    
    def get_billboard(self) -> List[VikiBillboardItem]:
        """Fetch the user's watchlist (billboard) from Viki.
        
        Returns:
            List of shows the user is watching
        """
        items = []
        page = 1
        per_page = 100
        
        while True:
            try:
                response = self.client.get_watchlist(page=page, per_page=per_page)
            except Exception as e:
                logger.error(f"Failed to fetch watchlist page {page}: {e}")
                break
            
            shows = response.get("response", [])
            if not shows:
                break
            
            for show in shows:
                # Extract last_watched info for change detection
                last_watched = show.get("last_watched", {})
                
                items.append(VikiBillboardItem(
                    viki_id=show.get("id", ""),
                    title=self._get_title(show),
                    type=show.get("type", "series"),
                    origin_country=show.get("origin", {}).get("country"),
                    origin_language=show.get("origin", {}).get("language"),
                    last_video_id=last_watched.get("id") if last_watched else None,
                    last_watched_at=last_watched.get("updated_at") if last_watched else None,
                ))
            
            if not response.get("more", False):
                break
            
            page += 1
        
        logger.info(f"Fetched {len(items)} shows from Viki billboard")
        return items
    
    def get_episodes(self, viki_id: str) -> List[VikiEpisode]:
        """Fetch all episodes for a show.
        
        Episodes are fetched from the container endpoint, which returns video IDs.
        Each video is then fetched individually to get the full metadata including
        watch_marker and other fields.
        
        Args:
            viki_id: Viki container ID
            
        Returns:
            List of episodes with metadata
        """
        episodes = []
        page = 1
        per_page = 100
        
        # First, get list of video IDs from the container
        while True:
            try:
                response = self.client.get_episodes(viki_id, page=page, per_page=per_page)
            except Exception as e:
                logger.error(f"Failed to fetch episodes for {viki_id} page {page}: {e}")
                break
            
            eps = response.get("response", [])
            if not eps:
                break
            
            # The response is a list of video IDs or video objects
            # For each, we may need to fetch full details to get watch_marker
            for ep in eps:
                # If it's a string (just ID), we'll still create episode entry
                # with basic info and fetch watch marker separately
                if isinstance(ep, str):
                    video_id = ep
                    # We could fetch full video details here, but for now
                    # we create a basic entry and rely on get_watch_progress() for markers
                    episodes.append(VikiEpisode(
                        viki_video_id=video_id,
                        viki_id=viki_id,
                        episode_number=0,  # Will be updated from full video data
                        duration=0,  # Will be updated from full video data
                    ))
                else:
                    # It's a dict with episode data
                    episodes.append(VikiEpisode(
                        viki_video_id=ep.get("id", ""),
                        viki_id=viki_id,
                        episode_number=ep.get("number", 0),
                        duration=ep.get("duration", 0),
                        watched_seconds=ep.get("watch_marker", 0),  # Extract if present
                        credits_marker=ep.get("credits_marker"),
                    ))
            
            if not response.get("more", False):
                break
            
            page += 1
        
        logger.debug(f"Fetched {len(episodes)} episodes for {viki_id}")
        return episodes
    
    def get_watch_progress(self, from_timestamp: int = 1) -> Dict[str, Dict[str, int]]:
        """Fetch watch progress for all shows.
        
        Args:
            from_timestamp: Unix timestamp (seconds) to fetch markers from.
                           Default 1 fetches all history. Pass last sync timestamp
                           for incremental updates.
        
        Returns:
            Dict mapping container_id -> video_id -> watched_seconds
            
        The watch markers endpoint returns ALL markers >= from_timestamp in ONE call.
        This is NOT piecemeal - it's a single global list for the user.
            
        Raises:
            ValueError: If session is invalid or API fails
        """
        response = self.client.get_watch_markers(from_timestamp=from_timestamp)
        
        markers = response.get("markers", {})
        progress = {}
        
        for container_id, videos in markers.items():
            progress[container_id] = {}
            for video_id, marker in videos.items():
                # marker should have watch_marker field (seconds watched)
                if isinstance(marker, dict):
                    # The marker dict contains watch_marker (seconds viewed)
                    watched_seconds = marker.get("watch_marker")
                    if watched_seconds is None:
                        # Fallback to duration if watch_marker not available
                        watched_seconds = marker.get("duration", 0)
                    
                    progress[container_id][video_id] = watched_seconds
                else:
                    # Assume it's already the watch position
                    progress[container_id][video_id] = int(marker) if marker else 0
        
        logger.info(f"Fetched watch progress for {len(progress)} shows from timestamp {from_timestamp}")
        return progress
    
    def get_watch_status_with_metadata(self, from_timestamp: int = 1) -> tuple[Dict[str, Dict[str, Any]], int]:
        """PRIMARY METHOD: Fetch watch status with enriched metadata.
        
        This is the primary data source for the sync. Returns watch status
        (the SOURCE OF TRUTH) enriched with episode metadata.
        
        Args:
            from_timestamp: Unix timestamp to fetch markers from (1 = all history)
        
        Returns:
            Tuple of:
            - Dict mapping container_id -> video_id -> {
                "watched_seconds": int,
                "episode_number": int,
                "duration": int,
                "credits_marker": Optional[int]
              }
            - Current timestamp (to save for next incremental sync)
            
        Data flow:
          1. Fetch watch markers (PRIMARY - what's actually watched)
             - Uses ?from=<timestamp> parameter for incremental updates
             - Returns ALL markers >= timestamp in ONE global call
          2. For each watched video, fetch episode metadata
          3. Merge and return
        """
        # Capture timestamp BEFORE fetch to ensure we don't miss updates
        current_timestamp = int(time.time())
        
        # Step 1: Get watch status (SOURCE OF TRUTH) - ONE global call
        watch_markers = self.get_watch_progress(from_timestamp=from_timestamp)
        if not watch_markers:
            logger.info("No watch status found")
            return {}, current_timestamp
        
        # Step 2: Enrich with episode metadata
        result = {}
        
        for container_id, videos in watch_markers.items():
            result[container_id] = {}
            
            # Fetch episodes for this show to get metadata
            episodes = self.get_episodes(container_id)
            episode_by_id = {ep.viki_video_id: ep for ep in episodes}
            
            # Merge watch status with episode metadata
            for video_id, watched_seconds in videos.items():
                episode = episode_by_id.get(video_id)
                
                result[container_id][video_id] = {
                    "watched_seconds": watched_seconds,
                    "episode_number": episode.episode_number if episode else 0,
                    "duration": episode.duration if episode else 0,
                    "credits_marker": episode.credits_marker if episode else None,
                }
        
        logger.info(f"Watch status with metadata for {len(result)} shows")
        return result, current_timestamp
    
    def get_container(self, viki_id: str) -> Optional[Dict[str, Any]]:
        """Fetch container (show) metadata.
        
        Args:
            viki_id: Viki container ID
            
        Returns:
            Container data or None if not found
        """
        try:
            return self.client.get_container(viki_id)
        except Exception as e:
            logger.error(f"Failed to fetch container {viki_id}: {e}")
            return None
    
    def get_bookmarks(self) -> List[str]:
        """Fetch the user's Watch Later (bookmarked) show IDs.
        
        Returns:
            List of Viki container IDs
        """
        try:
            response = self.client.get_watchlaters(ids_only=True)
            return response.get("response", [])
        except Exception as e:
            logger.error(f"Failed to fetch bookmarks: {e}")
            return []
    
    def _get_title(self, show: Dict[str, Any]) -> str:
        """Extract best title from show data."""
        titles = show.get("titles", {})
        # Prefer English, then original
        return (
            titles.get("en") or 
            titles.get("en-us") or 
            show.get("title") or 
            next(iter(titles.values()), "Unknown")
        )
