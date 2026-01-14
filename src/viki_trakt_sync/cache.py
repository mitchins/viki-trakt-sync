"""Caching layer for watch history to avoid repeated API calls during development."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class WatchHistoryCache:
    """Local cache of watch history from Viki.

    Stores full watch markers JSON to avoid repeatedly hitting Viki API
    during development and testing.

    File format: ~/.config/viki-trakt-sync/watch_history_cache.json
    Schema:
    {
        "cached_at": "...",
        "data": {
            "markers": { ... },
            "shows": {
                "41302c": { show_details },
                ...
            }
        },
        "metadata": { ... }
    }
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """Initialize cache.

        Args:
            cache_path: Path to cache file (default: ~/.config/viki-trakt-sync/watch_history_cache.json)
        """
        if cache_path is None:
            cache_path = (
                Path.home()
                / ".config"
                / "viki-trakt-sync"
                / "watch_history_cache.json"
            )

        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> Optional[Dict]:
        """Get cached watch history.

        Returns:
            Watch markers dict if cache exists and valid, None otherwise
        """
        if not self.cache_path.exists():
            logger.debug("No watch history cache found")
            return None

        try:
            with open(self.cache_path) as f:
                data = json.load(f)

            # Check if cache is fresh (has timestamp)
            if "cached_at" in data:
                cached_time = datetime.fromisoformat(data["cached_at"])
                age_hours = (datetime.utcnow() - cached_time).total_seconds() / 3600
                logger.info(f"Using cached watch history (age: {age_hours:.1f}h)")
            else:
                logger.info("Using cached watch history (age unknown)")

            return data.get("data")

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load watch history cache: {e}")
            return None

    def save(self, watch_markers: Dict, shows: Optional[Dict] = None, metadata: Optional[Dict] = None) -> None:
        """Save watch history to cache.

        Args:
            watch_markers: Watch markers data from Viki API
            shows: Optional dict of show details {viki_id: show_data}
            metadata: Optional metadata (number of shows, etc.)
        """
        cache_data_content = {
            "markers": watch_markers,
        }
        
        if shows:
            cache_data_content["shows"] = shows

        cache_data = {
            "cached_at": datetime.utcnow().isoformat(),
            "data": cache_data_content,
            "metadata": metadata or {},
        }

        try:
            with open(self.cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)

            show_count = len(watch_markers.get("markers", {}))
            logger.info(f"Cached watch history: {show_count} shows")

        except IOError as e:
            logger.error(f"Failed to save watch history cache: {e}")

    def clear(self) -> None:
        """Clear the cache."""
        if self.cache_path.exists():
            self.cache_path.unlink()
            logger.info("Cleared watch history cache")


class ShowMetadataCache:
    """Cache for show metadata from external sources (TVDB, MyDramaList, etc).

    Stores enriched metadata to avoid hitting external APIs multiple times
    for the same show during development.

    File format: ~/.config/viki-trakt-sync/show_metadata_cache.json
    Schema:
    {
        "viki_id": {
            "tvdb_id": 123456,
            "tvdb_aliases": ["My Secret Romance", "Dear Bandit"],
            "mdl_id": 779214,
            "mdl_url": "https://mydramalist.com/779214-my-secret-romance",
            "mdl_aliases": ["My Secret Romance", "Dear Bandit"],
            "sources": ["tvdb", "mdl"],
            "cached_at": "2026-01-13T06:44:58.127Z"
        }
    }
    """

    def __init__(self, cache_path: Optional[Path] = None):
        """Initialize metadata cache.

        Args:
            cache_path: Path to cache file
        """
        if cache_path is None:
            cache_path = (
                Path.home()
                / ".config"
                / "viki-trakt-sync"
                / "show_metadata_cache.json"
            )

        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path) as f:
                    self.cache = json.load(f)
                logger.debug(f"Loaded metadata cache: {len(self.cache)} shows")
            except (json.JSONDecodeError, IOError):
                logger.warning("Failed to load metadata cache, starting fresh")
                self.cache = {}
        else:
            self.cache = {}

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_path, "w") as f:
                json.dump(self.cache, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save metadata cache: {e}")

    def get(self, viki_id: str) -> Optional[Dict]:
        """Get cached metadata for a show.

        Args:
            viki_id: Viki show ID

        Returns:
            Cached metadata dict if exists, None otherwise
        """
        return self.cache.get(viki_id)

    def save_metadata(
        self,
        viki_id: str,
        tvdb_id: Optional[int] = None,
        tvdb_aliases: Optional[List[str]] = None,
        mdl_id: Optional[int] = None,
        mdl_url: Optional[str] = None,
        mdl_aliases: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
    ) -> None:
        """Save metadata for a show.

        Args:
            viki_id: Viki show ID
            tvdb_id: TVDB show ID
            tvdb_aliases: List of aliases from TVDB
            mdl_id: MyDramaList show ID
            mdl_url: MyDramaList show URL
            mdl_aliases: List of aliases from MyDramaList
            sources: List of sources where data came from
        """
        self.cache[viki_id] = {
            "tvdb_id": tvdb_id,
            "tvdb_aliases": tvdb_aliases or [],
            "mdl_id": mdl_id,
            "mdl_url": mdl_url,
            "mdl_aliases": mdl_aliases or [],
            "sources": sources or [],
            "cached_at": datetime.utcnow().isoformat(),
        }

        self._save()
        logger.debug(f"Cached metadata for {viki_id}")

    def stats(self) -> Dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats
        """
        stats = {
            "total": len(self.cache),
            "with_tvdb": sum(1 for v in self.cache.values() if v.get("tvdb_id")),
            "with_mdl": sum(1 for v in self.cache.values() if v.get("mdl_id")),
        }
        return stats

    def clear(self) -> None:
        """Clear all cached metadata."""
        self.cache = {}
        self._save()
        logger.info("Cleared show metadata cache")
