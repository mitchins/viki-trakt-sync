"""Viki API client."""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class VikiClient:
    """Client for Viki API."""

    BASE_URL = "https://www.viki.com"
    API_BASE_URL = "https://api.viki.io"
    APP_ID = "100000a"

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        session_cookie: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Initialize Viki client.
        
        Args:
            username: Viki username/email
            password: Viki password
            token: Pre-existing API token (avoids login)
            session_cookie: Pre-existing session cookie (avoids login)
            user_id: Viki user ID (can be extracted from token if not provided)
        """
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0",
            "Accept": "application/json",
        })
        self.token: Optional[str] = token
        self.user_id: Optional[str] = user_id
        
        # Try to extract user_id from token if not provided
        if token and not user_id:
            self.user_id = self._extract_user_id_from_token(token)
        
        # If session cookie provided, set it
        if session_cookie:
            self.session.cookies.set("session__id", session_cookie, domain=".viki.com")

    def _extract_user_id_from_token(self, token: str) -> Optional[str]:
        """Extract user ID from API token.
        
        Token format includes user ID. Example:
        ex1UPAVURALACKBR322BDBWJIO2MZSZS_2u0047157398uti00q1905x100000_djA0
                                              ^^^^^^^^
        
        Args:
            token: API token string
            
        Returns:
            User ID if extractable, None otherwise
        """
        import re
        match = re.search(r'_2u(\d+u)', token)
        if match:
            user_id = match.group(1)
            # Remove leading zeros but keep trailing 'u'
            # "0047157398u" -> "47157398u"
            numeric_part = user_id.rstrip('u')
            return numeric_part.lstrip('0') + 'u'
        return None

    def _get_csrf_token(self) -> str:
        """Get CSRF token for authentication.
        
        Returns:
            CSRF token string
        """
        url = urljoin(self.BASE_URL, "/api/csrf-token")
        response = self.session.get(url)
        response.raise_for_status()
        data = response.json()
        return data["token"]

    def login(
        self, username: Optional[str] = None, password: Optional[str] = None, language: str = "en"
    ) -> Dict[str, Any]:
        """Authenticate with Viki.
        
        NOTE: Viki requires reCAPTCHA for authentication. This method will fail with
        'recaptcha_error' if called programmatically. Instead:
        1. Login via browser once
        2. Extract session_cookie and token from browser
        3. Use those to initialize the client
        
        Args:
            username: Viki username/email (overrides instance value)
            password: Viki password (overrides instance value)
            language: Language code (default: "en")
            
        Returns:
            User object from API response
            
        Raises:
            ValueError: If credentials not provided
            requests.HTTPError: If authentication fails
            RuntimeError: If reCAPTCHA is required
        """
        username = username or self.username
        password = password or self.password
        
        if not username or not password:
            raise ValueError("Username and password required")
        
        # Get CSRF token
        csrf_token = self._get_csrf_token()
        
        # Sign in
        url = urljoin(self.BASE_URL, "/api/users/sign-in")
        self.session.headers["x-csrf-token"] = csrf_token
        
        payload = {
            "username": username,
            "password": password,
            "gRecaptchaResponse": "",
            "language": language,
        }
        
        response = self.session.post(url, json=payload)
        
        # Check for reCAPTCHA error
        if response.status_code == 400:
            try:
                error_data = response.json()
                if error_data.get("error") == "recaptcha_error":
                    raise RuntimeError(
                        "reCAPTCHA required. Please:\n"
                        "1. Login via browser at https://www.viki.com\n"
                        "2. Open DevTools → Application → Cookies\n"
                        "3. Copy 'session__id' cookie value\n"
                        "4. Set VIKI_SESSION_COOKIE environment variable or use --session-cookie flag"
                    )
            except (ValueError, KeyError):
                pass
        
        response.raise_for_status()
        
        data = response.json()
        self.token = data["token"]
        self.user_id = data["user"]["id"]
        
        logger.info(f"Logged in as {data['user']['username']} (ID: {self.user_id})")
        
        return data["user"]
    
    def get_current_user(self) -> Dict[str, Any]:
        """Get current user info (works with session cookie).
        
        This can be used to validate an existing session and extract user_id and token.
        
        Returns:
            User object
            
        Raises:
            ValueError: If not authenticated
            requests.HTTPError: If request fails
        """
        url = urljoin(self.BASE_URL, "/api/users/current")
        response = self.session.get(url)
        response.raise_for_status()
        
        data = response.json()
        self.user_id = data["id"]
        
        # Token might be in cookies or needs extraction
        logger.info(f"Current user: {data.get('username', 'Unknown')} (ID: {self.user_id})")
        
        return data

    def get_watch_markers(self, from_timestamp: int = 1) -> Dict[str, Any]:
        """Get watch markers (watch history with progress).
        
        NOTE: The /api/vw_watch_markers endpoint requires an active session cookie.
        This method attempts it but falls back to using the public API endpoint.
        
        Args:
            from_timestamp: Unix timestamp to fetch markers from (default: 1 for all)
            
        Returns:
            Watch markers response
        """
        url = "https://www.viki.com/api/vw_watch_markers"
        params = {"from": from_timestamp}
        
        response = self.session.get(url, params=params)
        
        # If we get 400 "User not signed in", the session expired
        # Fallback to using watchlist which works with token
        if response.status_code == 400:
            logger.warning("Session expired or inactive, using watchlist endpoint instead")
            return self._get_watch_history_from_watchlist()
        
        response.raise_for_status()
        return response.json()
    
    def _get_watch_history_from_watchlist(self) -> Dict[str, Any]:
        """Get watch history from watchlist endpoint (fallback).
        
        When vw_watch_markers isn't available, use the watchlist API which
        provides last_watched information.
        
        Returns:
            Formatted response matching vw_watch_markers structure
        """
        if not self.token or not self.user_id:
            raise ValueError("Token and user_id required. Try extracting fresh credentials from browser.")
        
        url = f"{self.API_BASE_URL}/v4/users/{self.user_id}/watchlist.json"
        
        # Transform watchlist format to match vw_watch_markers format
        # This is a simplified version that focuses on last_watched
        markers = {}
        
        # Paginate through all pages
        page = 1
        per_page = 100
        total_items = 0
        
        while True:
            params = {
                "token": self.token,
                "section_id": 2,  # Continue watching
                "page": page,
                "per_page": per_page,
                "app": self.APP_ID,
            }
            
            response = self.session.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            items = data.get("response", [])
            
            if not items:
                break
            
            total_items += len(items)
            
            for item in items:
                container_id = item.get("id")
                if not container_id:
                    continue
                
                # Use last_watched if available
                if item.get("last_watched"):
                    video = item["last_watched"]
                    video_id = video.get("id")
                    
                    markers[container_id] = {
                        video_id: {
                            "type": "watch_marker",
                            "video_id": video_id,
                            "container_id": container_id,
                            "episode": video.get("number"),
                            "duration": video.get("duration", 0),
                            "timestamp": video.get("updated_at") or video.get("created_at", ""),
                            "state": "normal",
                        }
                    }
            
            # Check if there are more pages
            if not data.get("more", False):
                break
            
            page += 1
            logger.debug(f"Fetching page {page} (current total: {len(markers)} shows)")
        
        logger.info(f"Fetched {total_items} items from {page} pages, got {len(markers)} unique shows")
        
        return {
            "updated_till": int(__import__("time").time()),
            "count": len(markers),
            "more": False,
            "markers": markers,
        }

    def get_watchlist(self, page: int = 1, per_page: int = 30) -> Dict[str, Any]:
        """Get user's watchlist (currently watching).
        
        Args:
            page: Page number (default: 1)
            per_page: Items per page (default: 30)
            
        Returns:
            Watchlist response with structure:
            {
                "more": bool,
                "count": int,
                "response": [
                    {
                        "id": str,
                        "type": str ("series" | "movie"),
                        "titles": {...},
                        "last_watched": {...},
                        ...
                    }
                ]
            }
        """
        if not self.token or not self.user_id:
            raise ValueError("Not authenticated. Call login() first.")
        
        url = urljoin(self.API_BASE_URL, f"/v4/users/{self.user_id}/watchlist.json")
        params = {
            "token": self.token,
            "page": page,
            "per_page": per_page,
            "section_id": 2,  # Continue watching section
            "app": self.APP_ID,
        }
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        
        return response.json()

    def get_watchlaters(self, ids_only: bool = True, page: int = 1, per_page: int = 100) -> Dict[str, Any]:
        """Get user's Watch Later (bookmarked) list.

        Args:
            ids_only: If True, request only IDs (faster). If False, returns full items.
            page: Page number
            per_page: Items per page

        Returns:
            Dict with keys: more, count, response (list)
        """
        if not self.token or not self.user_id:
            raise ValueError("Not authenticated. Token and user_id required")

        url = urljoin(self.API_BASE_URL, f"/v4/users/{self.user_id}/watchlaters.json")
        params = {
            "token": self.token,
            "ids": "true" if ids_only else "false",
            "page": page,
            "per_page": per_page,
            "app": self.APP_ID,
        }

        all_items = []
        current_page = page
        while True:
            params.update({"page": current_page, "per_page": per_page})
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                items = data
                all_items.extend(items)
                # If ids=true, API may not return 'more'; stop when page has fewer than requested
                if len(items) < per_page:
                    break
            else:
                items = data.get("response", [])
                all_items.extend(items)
                if not data.get("more", False):
                    break
            current_page += 1

        return {"more": False, "count": len(all_items), "response": all_items}

    def get_container(self, container_id: str) -> Dict[str, Any]:
        """Get container (series/movie) metadata.
        
        Args:
            container_id: Container ID (e.g., "41302c")
            
        Returns:
            Container metadata with titles, genres, origin, etc.
        """
        if not self.token:
            raise ValueError("Not authenticated. Call login() first.")
        
        url = urljoin(self.API_BASE_URL, f"/v4/containers/{container_id}.json")
        params = {
            "token": self.token,
            "app": self.APP_ID,
        }
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        
        return response.json()

    def get_episodes(self, container_id: str, page: int = 1, per_page: int = 100) -> Dict[str, Any]:
        """Get episodes for a container.
        
        Args:
            container_id: Container ID
            page: Page number (default: 1)
            per_page: Episodes per page (default: 100)
            
        Returns:
            Episodes response with structure:
            {
                "more": bool,
                "response": [
                    {
                        "id": str,
                        "number": int,
                        "duration": int,
                        ...
                    }
                ]
            }
        """
        if not self.token:
            raise ValueError("Not authenticated. Call login() first.")
        
        url = urljoin(self.API_BASE_URL, f"/v4/containers/{container_id}/episodes.json")
        params = {
            "token": self.token,
            "page": page,
            "per_page": per_page,
            "sort": "number",
            "direction": "asc",
            "app": self.APP_ID,
        }
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        
        return response.json()

    def is_episode_watched(self, watch_marker: int, duration: int, credits_marker: int) -> bool:
        """Determine if an episode is considered "watched".
        
        An episode is watched if:
        - Watch marker >= credits marker, OR
        - Watch marker >= 90% of duration
        
        Args:
            watch_marker: Current watch position (seconds)
            duration: Total duration (seconds)
            credits_marker: Credits start position (seconds)
            
        Returns:
            True if episode is considered watched
        """
        if watch_marker >= credits_marker:
            return True
        
        threshold = duration * 0.9
        return watch_marker >= threshold
