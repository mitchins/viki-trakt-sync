"""HTTP caching layer for external API requests (Trakt, TVDB, etc).

Uses requests-cache to cache GET requests with configurable TTL.
Prevents repeated API calls during development and testing.
"""

import logging
from datetime import timedelta
import os
from pathlib import Path
from typing import Optional

import requests_cache

logger = logging.getLogger(__name__)


class CachedSession:
    """HTTP session with automatic caching for GET requests.

    Caches GET responses from external APIs:
    - Trakt API: 1 hour
    - TVDB API: 24 hours
    - Other: 1 hour

    Uses SQLite backend: ~/.config/viki-trakt-sync/http_cache.db
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cache_name: str = "http_cache",
        expire_after: Optional[timedelta] = None,
    ):
        """Initialize cached session.

        Args:
            cache_dir: Directory for cache database (default: ~/.config/viki-trakt-sync)
            cache_name: Name of cache database file (without extension)
            expire_after: How long to cache responses (default: 3600s = 1 hour)
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".config" / "viki-trakt-sync"

        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = cache_dir / cache_name

        if expire_after is None:
            expire_after = timedelta(hours=1)

        self.expire_after = expire_after

        # Create cached session
        self.session = requests_cache.CachedSession(
            str(self.cache_path),
            backend="sqlite",
            expire_after=expire_after,
            allowable_methods=("GET", "HEAD"),
            allowable_codes=(200, 404),
            stale_if_error=True,
        )

        logger.debug(
            f"Initialized HTTP cache at {self.cache_path} "
            f"(expire_after={expire_after.total_seconds()}s)"
        )

    def get(self, url: str, **kwargs) -> requests_cache.models.Response:
        """GET request with caching.

        Args:
            url: URL to request
            **kwargs: Passed to requests.get()

        Returns:
            Response object (from cache if available, fresh otherwise)
        """
        response = self.session.get(url, **kwargs)
        
        # Log cache hit/miss
        if hasattr(response, "from_cache"):
            source = "cache" if response.from_cache else "network"
            logger.debug(f"GET {url}: {source}")
        
        return response

    def get_json(self, url: str, **kwargs) -> dict:
        """GET request returning JSON, with caching.

        Args:
            url: URL to request
            **kwargs: Passed to requests.get()

        Returns:
            Parsed JSON response
        """
        response = self.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    def stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats
        """
        try:
            cache_size = 0
            if self.cache_path.exists():
                # SQLite cache file
                cache_file = self.cache_path.with_suffix(".sqlite")
                if cache_file.exists():
                    cache_size = cache_file.stat().st_size

            return {
                "cache_path": str(self.cache_path),
                "cache_size_mb": cache_size / (1024 * 1024),
                "expire_after_hours": self.expire_after.total_seconds() / 3600,
            }
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {}

    def clear(self) -> None:
        """Clear all cached responses."""
        try:
            self.session.cache.clear()
            logger.info("Cleared HTTP cache")
        except Exception as e:
            logger.error(f"Failed to clear HTTP cache: {e}")

    def close(self) -> None:
        """Close session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global cached session instances
_trakt_session: Optional[CachedSession] = None
_tvdb_session: Optional[CachedSession] = None


def get_trakt_session() -> CachedSession:
    """Get global Trakt API cached session.

    Caches for 1 hour (Trakt API rarely changes during that time).

    Returns:
        CachedSession configured for Trakt
    """
    global _trakt_session

    if _trakt_session is None:
        # Allow TTL override via env (hours)
        ttl_hours = float(os.getenv("TRAKT_CACHE_HOURS", "1"))
        _trakt_session = CachedSession(
            cache_name="http_cache_trakt",
            expire_after=timedelta(hours=ttl_hours),
        )

    return _trakt_session


def get_tvdb_session() -> CachedSession:
    """Get global TVDB API cached session.

    Caches for 24 hours (TVDB data is relatively stable).

    Returns:
        CachedSession configured for TVDB
    """
    global _tvdb_session

    if _tvdb_session is None:
        ttl_hours = float(os.getenv("TVDB_CACHE_HOURS", "24"))
        _tvdb_session = CachedSession(
            cache_name="http_cache_tvdb",
            expire_after=timedelta(hours=ttl_hours),
        )

    return _tvdb_session
