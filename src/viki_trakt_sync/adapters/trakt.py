"""Trakt API Adapter.

Provides a clean interface to Trakt's API for searching shows,
fetching metadata, and syncing watch history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class TraktShow:
    """A show from Trakt."""
    trakt_id: int
    slug: str
    title: str
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None


@dataclass
class TraktSearchResult:
    """A search result from Trakt."""
    show: TraktShow
    score: float = 0.0


@dataclass
class TraktEpisode:
    """An episode reference for Trakt sync."""
    show_trakt_id: int
    season: int
    episode: int
    watched_at: Optional[datetime] = None


class TraktClientProtocol(Protocol):
    """Protocol defining what we need from a Trakt client."""
    
    def search_shows(self, title: str) -> List[Dict[str, Any]]: ...
    def get_show_by_slug(self, slug: str) -> Optional[Dict[str, Any]]: ...
    def get_show_by_tvdb(self, tvdb_id: int) -> Optional[Dict[str, Any]]: ...


class TraktAdapter:
    """Adapter for Trakt API interactions.
    
    Wraps TraktClient to provide a clean domain-focused interface.
    """
    
    def __init__(self, client: TraktClientProtocol):
        """Initialize adapter with a Trakt client.
        
        Args:
            client: TraktClient instance (or mock for testing)
        """
        self.client = client
    
    def search(self, title: str) -> List[TraktSearchResult]:
        """Search for shows by title.
        
        Args:
            title: Show title to search for
            
        Returns:
            List of matching shows with scores
        """
        try:
            results = self.client.search_shows(title)
        except Exception as e:
            logger.error(f"Trakt search failed for '{title}': {e}")
            return []
        
        search_results = []
        for item in results:
            show_data = item.get("show", {})
            ids = show_data.get("ids", {})
            
            if not ids.get("trakt"):
                continue
            
            search_results.append(TraktSearchResult(
                show=TraktShow(
                    trakt_id=ids.get("trakt"),
                    slug=ids.get("slug", ""),
                    title=show_data.get("title", ""),
                    year=show_data.get("year"),
                    tvdb_id=ids.get("tvdb"),
                    imdb_id=ids.get("imdb"),
                ),
                score=item.get("score", 0.0),
            ))
        
        logger.debug(f"Found {len(search_results)} Trakt results for '{title}'")
        return search_results
    
    def get_show(self, slug: str) -> Optional[TraktShow]:
        """Get show details by slug.
        
        Args:
            slug: Trakt show slug
            
        Returns:
            TraktShow or None if not found
        """
        try:
            data = self.client.get_show_by_slug(slug)
        except Exception as e:
            logger.error(f"Failed to get Trakt show {slug}: {e}")
            return None
        
        if not data:
            return None
        
        ids = data.get("ids", {})
        return TraktShow(
            trakt_id=ids.get("trakt"),
            slug=ids.get("slug", slug),
            title=data.get("title", ""),
            year=data.get("year"),
            tvdb_id=ids.get("tvdb"),
            imdb_id=ids.get("imdb"),
        )
    
    def get_show_by_tvdb(self, tvdb_id: int) -> Optional[TraktShow]:
        """Get show by TVDB ID.
        
        Args:
            tvdb_id: TVDB ID
            
        Returns:
            TraktShow or None if not found
        """
        try:
            data = self.client.get_show_by_tvdb(tvdb_id)
        except Exception as e:
            logger.error(f"Failed to get Trakt show by TVDB {tvdb_id}: {e}")
            return None
        
        if not data:
            return None
        
        ids = data.get("ids", {})
        return TraktShow(
            trakt_id=ids.get("trakt"),
            slug=ids.get("slug", ""),
            title=data.get("title", ""),
            year=data.get("year"),
            tvdb_id=tvdb_id,
        )
    
    def sync_watched(self, episodes: List[TraktEpisode]) -> Dict[str, int]:
        """Sync watched episodes to Trakt.
        
        Args:
            episodes: List of episodes to mark as watched
            
        Returns:
            Dict with 'added', 'existing', 'failed' counts
        """
        if not episodes:
            return {"added": 0, "existing": 0, "failed": 0}
        
        # Group episodes by show for batch sync
        shows_data = {}
        for ep in episodes:
            if ep.show_trakt_id not in shows_data:
                shows_data[ep.show_trakt_id] = []
            shows_data[ep.show_trakt_id].append({
                "season": ep.season,
                "episode": ep.episode,
                "watched_at": self._format_datetime(ep.watched_at),
            })
        
        # Build sync payload
        payload = {
            "shows": [
                {
                    "ids": {"trakt": trakt_id},
                    "seasons": self._group_episodes_by_season(eps)
                }
                for trakt_id, eps in shows_data.items()
            ]
        }
        
        # Call Trakt sync/history endpoint
        try:
            result = self._post_sync_history(payload)
            return {
                "added": result.get("added", {}).get("episodes", 0),
                "existing": result.get("existing", {}).get("episodes", 0),  # FIXED: was 'not_found'
                "failed": 0,
            }
        except Exception as e:
            logger.error(f"Failed to sync {len(episodes)} episodes to Trakt: {e}")
            return {"added": 0, "existing": 0, "failed": len(episodes)}
        """Format a datetime object or string to ISO format.
        
        Args:
            dt: datetime object, string, or None
            
        Returns:
            ISO format string or None
        """
        if dt is None:
            return None
        if isinstance(dt, str):
            return dt
        if hasattr(dt, 'isoformat'):
            return dt.isoformat()
        return str(dt)
        
        # Build sync payload
        payload = {
            "shows": [
                {
                    "ids": {"trakt": trakt_id},
                    "seasons": self._group_episodes_by_season(eps)
                }
                for trakt_id, eps in shows_data.items()
            ]
        }
        
        # Call Trakt sync/history endpoint
        try:
            result = self._post_sync_history(payload)
            return {
                "added": result.get("added", {}).get("episodes", 0),
                "existing": result.get("not_found", {}).get("episodes", 0),
                "failed": 0,
            }
        except Exception as e:
            logger.error(f"Failed to sync {len(episodes)} episodes to Trakt: {e}")
            return {"added": 0, "existing": 0, "failed": len(episodes)}
    
    def _group_episodes_by_season(self, episodes: List[Dict]) -> List[Dict]:
        """Group episodes by season for Trakt API."""
        seasons = {}
        for ep in episodes:
            s = ep["season"]
            if s not in seasons:
                seasons[s] = {"number": s, "episodes": []}
            seasons[s]["episodes"].append({
                "number": ep["episode"],
                "watched_at": ep.get("watched_at"),
            })
        return list(seasons.values())
    
    def _post_sync_history(self, payload: Dict) -> Dict:
        """Post to Trakt sync/history endpoint.
        
        Uses direct HTTP since we need the sync endpoint.
        """
        import requests
        
        # Get credentials from client
        client_id = getattr(self.client, 'client_id', None)
        access_token = getattr(self.client, 'access_token', None)
        
        if not client_id:
            raise RuntimeError("Trakt client_id not available")
        if not access_token:
            raise RuntimeError("Trakt access_token required for sync")
        
        headers = {
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': client_id,
            'Authorization': f'Bearer {access_token}',
        }
        
        url = "https://api.trakt.tv/sync/history"
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        
        return resp.json()
