"""MyDramaList integration for alias resolution.

Scrapes MyDramaList to find English aliases and Viki IDs that help
resolve unmatched shows via TVDB cross-reference.

Architecture:
  1. Search MDL (HTML scrape): /search?q={title}
  2. Extract first result link
  3. Load detail page (HTML scrape)
  4. Extract English aliases from JSON-LD structured data
  5. Search TVDB with extracted aliases to find TVDB ID
  6. Return aliases + Viki ID for caching
"""

from __future__ import annotations

from typing import Dict, Optional, List
import logging
import re
import requests
from bs4 import BeautifulSoup
import json

logger = logging.getLogger(__name__)


class MdlClient:
    """MyDramaList scraper for alias resolution."""

    def __init__(self):
        """Initialize MDL client."""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0'
        })
        self.base_url = "https://mydramalist.com"

    def search_alias(self, title: str, origin_country: Optional[str] = None) -> Optional[Dict]:
        """Search MDL for a show and extract aliases + Viki ID.

        Flow:
          1. Search MDL: GET /search?q={title}
          2. Get first result URL
          3. Load detail page
          4. Extract English aliases from JSON-LD
          5. Extract Viki ID from "where to watch" links

        Args:
            title: Show title to search for
            origin_country: ISO country code (unused, kept for API compatibility)

        Returns:
            Dict with:
              - english_aliases: List of English alternative titles
              - viki_id: Viki show ID if found
              - mdl_url: Link to MDL page
              - mdl_id: MDL show ID
            Or None if not found
        """
        try:
            # Step 1: Search MDL
            logger.debug(f"Searching MDL for: {title}")
            search_url = f"{self.base_url}/search"
            resp = self.session.get(search_url, params={"q": title}, timeout=10)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.content, 'html.parser')
            
            # Step 2: Find first result
            result_box = soup.find('div', class_='box')
            if not result_box:
                logger.debug(f"MDL: No results for {title}")
                return None

            result_link = result_box.find('a')
            if not result_link or not result_link.get('href'):
                logger.debug(f"MDL: No link in first result")
                return None

            mdl_path = result_link.get('href')
            # Extract MDL ID from URL like /712567-chilly-cohabitation
            mdl_id_match = re.match(r'/(\d+)', mdl_path)
            mdl_id = mdl_id_match.group(1) if mdl_id_match else None

            detail_url = f"{self.base_url}{mdl_path}"
            logger.debug(f"Loading MDL detail: {detail_url}")

            # Step 3: Load detail page
            detail_resp = self.session.get(detail_url, timeout=10)
            detail_resp.raise_for_status()

            detail_soup = BeautifulSoup(detail_resp.content, 'html.parser')

            # Step 4: Extract English aliases from JSON-LD
            english_aliases = []
            scripts = detail_soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    alt_names = data.get('alternateName', [])
                    if alt_names:
                        # Filter to English aliases (heuristic: no CJK characters)
                        for name in alt_names:
                            if not re.search(r'[\u4e00-\u9fff\uac00-\ud7af\u3040-\u309f]', name):
                                english_aliases.append(name)
                        logger.debug(f"Extracted aliases from JSON-LD: {english_aliases}")
                        break
                except (json.JSONDecodeError, TypeError):
                    continue

            # Step 5: Extract Viki ID
            viki_id = None
            for link in detail_soup.find_all('a'):
                href = link.get('href', '')
                if 'viki' in href.lower():
                    # URL format: /redirect?q=https%3A%2F%2Fwww.viki.com%2Ftv%2F38670c-my-chilling-roommate
                    viki_match = re.search(r'/tv/([a-z0-9]+)', href)
                    if viki_match:
                        viki_id = viki_match.group(1)
                        logger.debug(f"Extracted Viki ID: {viki_id}")
                        break

            if not english_aliases and not viki_id:
                logger.debug(f"MDL {title}: No aliases or Viki ID found")
                return None

            logger.debug(f"MDL {title}: {len(english_aliases)} aliases, Viki ID: {viki_id}")
            return {
                "english_aliases": english_aliases,
                "viki_id": viki_id,
                "mdl_url": detail_url,
                "mdl_id": mdl_id,
            }

        except requests.RequestException as e:
            logger.debug(f"MDL search error for {title}: {e}")
            return None
        except Exception as e:
            logger.debug(f"MDL parse error for {title}: {e}")
            return None

    def search_title(self, title: str) -> Optional[Dict]:
        """Alias for search_alias() for backward compatibility."""
        return self.search_alias(title)

            logger.debug(f"MDL search found results but no TVDB ID for: {title}")
            return None

        except requests.RequestException as e:
            logger.debug(f"MDL API error for '{title}': {e}")
            return None
        except Exception as e:
            logger.error(f"MDL search error for '{title}': {e}")
            return None

    def search_title(self, title: str) -> Optional[Dict]:
        """Simple title search without country filtering.

        Returns the first matching show's basic info.
        """
        return self.search_alias(title, origin_country=None)


