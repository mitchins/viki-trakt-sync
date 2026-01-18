"""Viki API client.

Built from working test.py code - uses exact same request structure.
"""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class VikiClient:
    """Client for Viki API."""

    BASE_URL = "https://www.viki.com"
    
    # Headers that work - copied exactly from test.py
    HEADERS = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en',
        'priority': 'u=1, i',
        'referer': 'https://www.viki.com/',
        'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
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
        
        # Verify we have the critical cookies
        required = ['session__id', '_viki_session']
        missing = [k for k in required if k not in cookies]
        if missing:
            logger.warning(f"Missing cookies that may be required: {missing}")

    def get_watch_markers(self, from_timestamp: int = 1) -> Dict[str, Any]:
        """Get watch markers - uses exact same pattern as test.py.
        
        Args:
            from_timestamp: Unix timestamp for incremental sync (1 = all history)
            
        Returns:
            Watch markers response dict
        """
        params = {'from': str(from_timestamp)}
        
        logger.debug(f"Calling watch_markers with {len(self.cookies)} cookies")
        
        # Exact same call pattern as test.py
        response = requests.get(
            'https://www.viki.com/api/vw_watch_markers',
            params=params,
            cookies=self.cookies,
            headers=self.HEADERS
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
        
        response = requests.get(url, params=params, headers=self.HEADERS)
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
        
        response = requests.get(url, params=params, headers=self.HEADERS)
        response.raise_for_status()
        return response.json()

    def get_video(self, video_id: str) -> Dict[str, Any]:
        """Get video (episode) details."""
        url = f"https://api.viki.io/v4/videos/{video_id}.json"
        params = {"app": "100000a"}
        
        response = requests.get(url, params=params, headers=self.HEADERS)
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
        
        response = requests.get(url, params=params, cookies=self.cookies, headers=self.HEADERS)
        response.raise_for_status()
        return response.json()
