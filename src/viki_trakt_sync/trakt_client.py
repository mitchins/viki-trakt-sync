"""Trakt.tv API client using PyTrakt library.

Uses the documented PyTrakt 4.2.1+ API for OAuth and PIN authentication,
plus PyTrakt's built-in methods for searching and fetching show metadata.
"""

from __future__ import annotations

import logging
import os
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class TraktClient:
    """Trakt.tv API client using PyTrakt library."""
    
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        """Initialize Trakt client with credentials.
        
        Args:
            client_id: Trakt API client ID (from settings.toml)
            client_secret: Trakt API client secret (from settings.toml)
        """
        # Credentials MUST come from config, not environment variables
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None  # Set via configure_oauth_token() if needed
        
        if not self.client_id or not self.client_secret:
            raise RuntimeError("TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET are required in settings.toml [trakt] section")
        
        # Configure PyTrakt with credentials
        try:
            import trakt
            # Set module-level vars that PyTrakt expects
            trakt.CLIENT_ID = self.client_id
            trakt.CLIENT_SECRET = self.client_secret
            
            if self.access_token:
                # If we have a token, set it directly
                trakt.OAUTH_TOKEN = self.access_token
                logger.debug("Configured PyTrakt with stored OAuth token")
            else:
                logger.debug("Configured PyTrakt client credentials (no token yet)")
            
            # Import the actual API classes we'll use
            from trakt.tv import TVShow
            from trakt.movies import Movie
            
            self._TVShow = TVShow
            self._Movie = Movie
            self._trakt_module = trakt
            
        except Exception as e:
            raise RuntimeError(f"Failed to initialize PyTrakt: {e}") from e

    def device_login(self, poll: bool = True, timeout: int = 600) -> Dict:
        """Run device-code login flow via OAuth.
        
        This uses PyTrakt's device auth flow.
        """
        raise NotImplementedError("Device login not implemented yet. Use PIN auth via CLI.")

    def oauth_login(self, username: str = None, store: bool = True) -> Dict:
        """Run OAuth login flow.
        
        Args:
            username: Trakt username (optional)
            store: Whether to store credentials to ~/.pytrakt.json
            
        Returns:
            Auth result dict
        """
        from trakt import init
        
        try:
            # Run the interactive OAuth flow
            result = init(username or '', store=store, client_id=self.client_id, client_secret=self.client_secret)
            logger.info("OAuth authentication successful")
            return result or {}
        except Exception as e:
            logger.error(f"OAuth login failed: {e}")
            raise

    def search_shows(self, title: str) -> List[Dict]:
        """Search Trakt for shows by title.
        
        Tries PyTrakt first, falls back to HTTP API if needed.
        
        Args:
            title: Show title to search for
            
        Returns:
            List of show results matching Trakt API format
        """
        # PyTrakt requires OAuth/PIN auth, but we can still use HTTP API directly
        # with just the client ID (no auth required for public search)
        import requests
        
        try:
            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': '2',
                'trakt-api-key': self.client_id,
            }
            if self.access_token:
                headers['Authorization'] = f'Bearer {self.access_token}'
            
            url = f"https://api.trakt.tv/search?type=show&query={title}"
            resp = requests.get(url, headers=headers, params=None, timeout=30)
            resp.raise_for_status()
            
            results = resp.json() or []
            logger.debug(f"Found {len(results)} shows for '{title}'")
            return results
            
        except Exception as e:
            logger.error(f"Search failed for '{title}': {e}")
            return []

    def get_show_by_slug(self, slug: str) -> Optional[Dict]:
        """Get show details by slug.
        
        Uses HTTP API directly for compatibility.
        
        Args:
            slug: Trakt show slug
            
        Returns:
            Show data dict with full metadata, or None if not found
        """
        import requests
        
        try:
            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': '2',
                'trakt-api-key': self.client_id,
            }
            if self.access_token:
                headers['Authorization'] = f'Bearer {self.access_token}'
            
            url = f"https://api.trakt.tv/shows/{slug}?extended=full"
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            show = resp.json()
            if not show:
                return None
            
            return {
                'title': show.get('title'),
                'year': show.get('year'),
                'ids': {
                    'trakt': show.get('ids', {}).get('trakt'),
                    'slug': show.get('ids', {}).get('slug'),
                    'tvdb': show.get('ids', {}).get('tvdb'),
                    'imdb': show.get('ids', {}).get('imdb'),
                },
                'overview': show.get('overview'),
                'genres': show.get('genres', []),
                'status': show.get('status'),
                'network': show.get('network'),
            }
        except Exception as e:
            logger.debug(f"get_show_by_slug failed for {slug}: {e}")
            return None

    def get_show_by_tvdb(self, tvdb_id: int | str) -> Optional[Dict]:
        """Get show by TVDB ID using PyTrakt.
        
        Args:
            tvdb_id: TVDB ID for the show
            
        Returns:
            Show data dict with ids, or None if not found
        """
        try:
            # PyTrakt can search by TVDB ID via the search by id method
            # This is a bit of a workaround since PyTrakt doesn't have direct TVDB lookup
            # We'll use the HTTP API approach as fallback
            import requests
            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': '2',
                'trakt-api-key': self.client_id,
            }
            if self.access_token:
                headers['Authorization'] = f'Bearer {self.access_token}'
            
            url = f"https://api.trakt.tv/search/tvdb/{tvdb_id}?type=show"
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            results = resp.json()
            if not results:
                return None
            
            item = results[0]
            show = item.get('show', {})
            
            return {
                'title': show.get('title'),
                'ids': {
                    'trakt': show.get('ids', {}).get('trakt'),
                    'slug': show.get('ids', {}).get('slug'),
                }
            }
        except Exception as e:
            logger.debug(f"get_show_by_tvdb failed for {tvdb_id}: {e}")
            return None
