"""Viki API client.

Built from working test.py code - uses exact same request structure.
"""

import logging
from typing import Any, Dict, List, Optional

import requests

from .http_utils import API_TIMEOUT

logger = logging.getLogger(__name__)

# Initialize user agent once per process with fallback
# Constrained to Chrome/macOS for consistency and modern browser support
_USER_AGENT: str = ""
try:
    from fake_useragent import UserAgent
    _ua = UserAgent(browsers=['chrome'], os=['macos'], platforms=['pc'], min_version=120)
    _USER_AGENT = _ua.random
except Exception as e:
    logger.debug(f"fake-useragent initialization failed, using fallback: {e}")
    _USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"

logger.debug(f"Using user agent: {_USER_AGENT[:50]}...")


class VikiClient:
    """Client for Viki API."""

    BASE_URL = "https://www.viki.com"
    
    # Base headers (user-agent added per instance)
    # Note: sec-ch-ua headers omitted to avoid mismatch with UA string
    HEADERS = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en',
        'priority': 'u=1, i',
        'referer': 'https://www.viki.com/',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'x-viki-app-ver': '26.1.3-4.43.1',
        'x-viki-device-id': '276378550d',
    }

    def __init__(self, cookies: Dict[str, str], token: Optional[str] = None, user_id: Optional[str] = None):
        """Initialize Viki client.
        
        Args:
            cookies: Dict of cookies (exactly like test.py uses)
            token: API token (optional, for other endpoints)
            user_id: User ID (optional)
        """
        self.cookies = cookies
        self.token = token
        self.user_id = user_id
        
        # Create request headers with persistent user agent
        self.headers = self.HEADERS.copy()
        self.headers['user-agent'] = _USER_AGENT
        
        # Verify we have the critical cookies
        required = ['session__id', '_viki_session']
        missing = [k for k in required if k not in cookies]
        if missing:
            raise ValueError(f"Missing required cookies: {missing}")

    def get_watch_history(self, from_timestamp: int = 0) -> Dict[str, Any]:
        """Get user's watch history.
        
        This is the main entry point - mimics test.py exactly.
        
        Args:
            from_timestamp: Unix timestamp to fetch history from
            
        Returns:
            Response dict with watch markers/history data
        """
        params = {'from': str(from_timestamp)}
        
        logger.debug(f"Calling watch_markers with {len(self.cookies)} cookies")
        
        # Exact same call pattern as test.py
        response = requests.get(
            'https://www.viki.com/api/vw_watch_markers',
            params=params,
            cookies=self.cookies,
            headers=self.headers,
            timeout=API_TIMEOUT
        )
        
        logger.debug(f"Response status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"API error (HTTP {response.status_code}): {response.text[:300]}")
            raise ValueError(f"API request failed with status {response.status_code}: {response.text[:100]}")
        
        return response.json()

    def get_container(self, container_id: str) -> Dict[str, Any]:
        """Get container (show) details."""
        url = f"https://api.viki.io/v4/containers/{container_id}.json"
        params = {"app": "100000a"}
        
        response = requests.get(url, params=params, headers=self.headers, timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def get_episodes(self, container_id: str, page: int = 1, per_page: int = 50) -> Dict[str, Any]:
        """Get episodes for a container."""
        url = f"https://api.viki.io/v4/containers/{container_id}/episodes.json"
        params = {
            "app": "100000a",
            "page": page,
            "per_page": per_page,
            "direction": "asc",
        }
        
        response = requests.get(url, params=params, headers=self.headers, timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def get_video(self, video_id: str) -> Dict[str, Any]:
        """Get video (episode) details."""
        url = f"https://api.viki.io/v4/videos/{video_id}.json"
        params = {"app": "100000a"}
        
        response = requests.get(url, params=params, headers=self.headers, timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def get_watchlist(self, page: int = 1, per_page: int = 30) -> Dict[str, Any]:
        """Get user's watchlist."""
        if not self.user_id:
            raise ValueError("user_id required for watchlist")
        
        url = f"https://api.viki.io/v4/users/{self.user_id}/watchlist.json"
        params = {
            "app": "100000a",
            "page": page,
            "per_page": per_page,
        }
        
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()
