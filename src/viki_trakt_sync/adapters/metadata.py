"""Metadata Adapter.

Provides access to external metadata sources (TVDB, MDL) for
show matching when direct Trakt search fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


@dataclass
class MetadataResult:
    """Result from a metadata lookup."""
    tvdb_id: Optional[int] = None
    title: Optional[str] = None
    year: Optional[int] = None
    aliases: List[str] = None
    
    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []


class TVDBSessionProtocol(Protocol):
    """Protocol for TVDB HTTP session."""
    def get(self, url: str, **kwargs) -> Any: ...


class MetadataAdapter:
    """Adapter for external metadata services.
    
    Provides lookups via TVDB and potentially MDL (MyDramaList)
    for Asian drama matching.
    """
    
    def __init__(self, tvdb_session: Optional[TVDBSessionProtocol] = None):
        """Initialize adapter.
        
        Args:
            tvdb_session: HTTP session for TVDB API (with caching)
        """
        self._tvdb_session = tvdb_session
    
    @property
    def tvdb_session(self):
        """Lazy-load TVDB session."""
        if self._tvdb_session is None:
            from ..http_cache import get_tvdb_session
            self._tvdb_session = get_tvdb_session()
        return self._tvdb_session
    
    def search_tvdb(self, title: str) -> List[MetadataResult]:
        """Search TVDB for shows by title.
        
        Args:
            title: Show title to search for
            
        Returns:
            List of metadata results
        """
        try:
            url = f"https://api4.thetvdb.com/v4/search?query={title}&type=series"
            response = self.tvdb_session.get(url)
            
            if hasattr(response, 'json'):
                data = response.json()
            else:
                data = response
            
            results = []
            for item in data.get("data", []):
                results.append(MetadataResult(
                    tvdb_id=int(item.get("tvdb_id", 0)) or None,
                    title=item.get("name"),
                    year=item.get("year"),
                    aliases=[a.get("name") for a in item.get("aliases", []) if a.get("name")],
                ))
            
            logger.debug(f"Found {len(results)} TVDB results for '{title}'")
            return results
            
        except Exception as e:
            logger.error(f"TVDB search failed for '{title}': {e}")
            return []
    
    def get_tvdb_show(self, tvdb_id: int) -> Optional[MetadataResult]:
        """Get show details from TVDB.
        
        Args:
            tvdb_id: TVDB series ID
            
        Returns:
            MetadataResult or None
        """
        try:
            url = f"https://api4.thetvdb.com/v4/series/{tvdb_id}"
            response = self.tvdb_session.get(url)
            
            if hasattr(response, 'json'):
                data = response.json()
            else:
                data = response
            
            show = data.get("data", {})
            if not show:
                return None
            
            return MetadataResult(
                tvdb_id=tvdb_id,
                title=show.get("name"),
                year=show.get("year"),
                aliases=[a.get("name") for a in show.get("aliases", []) if a.get("name")],
            )
            
        except Exception as e:
            logger.error(f"TVDB lookup failed for {tvdb_id}: {e}")
            return None
    
    def search_tvdb_by_remote(self, remote_id: str, site: str = "mdl") -> Optional[MetadataResult]:
        """Search TVDB using a remote ID from another site.
        
        This is useful for MDL (MyDramaList) lookups where we have an MDL ID
        and want to find the corresponding TVDB entry.
        
        Args:
            remote_id: ID on the remote site
            site: Site identifier (e.g., "mdl" for MyDramaList)
            
        Returns:
            MetadataResult or None
        """
        try:
            # TVDB allows searching by remote_id
            url = f"https://api4.thetvdb.com/v4/search?remote_id={remote_id}"
            response = self.tvdb_session.get(url)
            
            if hasattr(response, 'json'):
                data = response.json()
            else:
                data = response
            
            items = data.get("data", [])
            if not items:
                return None
            
            item = items[0]
            return MetadataResult(
                tvdb_id=int(item.get("tvdb_id", 0)) or None,
                title=item.get("name"),
                year=item.get("year"),
            )
            
        except Exception as e:
            logger.debug(f"TVDB remote lookup failed for {remote_id}: {e}")
            return None
