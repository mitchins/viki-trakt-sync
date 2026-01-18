"""Viki → Trakt show matching system.

Matches Viki shows to Trakt.tv shows using multi-tier strategy:
  Tier 1: Local cache (instant)
  Tier 2: Exact Trakt search (fast)
  Tier 3: TVDB intermediary (reliable)
  Tier 4: Fuzzy matching (fallback)
"""

import logging
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

import requests

from .http_cache import get_trakt_session
from .http_cache import get_tvdb_session
from .trakt_client import TraktClient

if TYPE_CHECKING:
    from .config_provider import ConfigProvider

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of matching a Viki show to Trakt."""

    viki_id: str
    viki_title: str
    trakt_id: Optional[int] = None
    trakt_slug: Optional[str] = None
    trakt_title: Optional[str] = None
    match_confidence: float = 0.0  # 0.0 to 1.0
    match_method: Optional[str] = None  # "cache", "exact_trakt", "tvdb", "fuzzy", "manual"
    tvdb_id: Optional[int] = None
    matched_at: Optional[datetime] = None
    notes: str = ""

    def is_matched(self) -> bool:
        """Check if show was successfully matched."""
        return self.trakt_id is not None and self.match_confidence > 0.0

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        data = asdict(self)
        if data["matched_at"]:
            data["matched_at"] = data["matched_at"].isoformat()
        return data


class MatchDB:
    """Local SQLite database for caching Viki→Trakt matches."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize match database.

        Args:
            db_path: Path to SQLite database (default: ~/.config/viki-trakt-sync/matches.db)
        """
        if db_path is None:
            db_path = Path.home() / ".config" / "viki-trakt-sync" / "matches.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS viki_trakt_matches (
                    viki_id TEXT PRIMARY KEY,
                    viki_title TEXT NOT NULL,
                    trakt_id INTEGER,
                    trakt_slug TEXT,
                    trakt_title TEXT,
                    tvdb_id INTEGER,
                    confidence REAL,
                    method TEXT,
                    matched_at TEXT,
                    notes TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.commit()

    def get(self, viki_id: str) -> Optional[MatchResult]:
        """Get cached match for Viki show.

        Args:
            viki_id: Viki show ID

        Returns:
            MatchResult if cached, None otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM viki_trakt_matches WHERE viki_id = ?",
                (viki_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        (
            viki_id,
            viki_title,
            trakt_id,
            trakt_slug,
            trakt_title,
            tvdb_id,
            confidence,
            method,
            matched_at,
            notes,
            _updated_at,
        ) = row

        if matched_at:
            matched_at = datetime.fromisoformat(matched_at)

        return MatchResult(
            viki_id=viki_id,
            viki_title=viki_title,
            trakt_id=trakt_id,
            trakt_slug=trakt_slug,
            trakt_title=trakt_title,
            tvdb_id=tvdb_id,
            match_confidence=confidence,
            match_method=method,
            matched_at=matched_at,
            notes=notes,
        )

    def save(self, result: MatchResult) -> None:
        """Save match result to database.

        Args:
            result: MatchResult to save
        """
        now = datetime.now(timezone.utc).isoformat()
        matched_at = result.matched_at.isoformat() if result.matched_at else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO viki_trakt_matches
                (viki_id, viki_title, trakt_id, trakt_slug, trakt_title, tvdb_id,
                 confidence, method, matched_at, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.viki_id,
                    result.viki_title,
                    result.trakt_id,
                    result.trakt_slug,
                    result.trakt_title,
                    result.tvdb_id,
                    result.match_confidence,
                    result.match_method,
                    matched_at,
                    result.notes,
                    now,
                ),
            )
            conn.commit()

        logger.info(
            f"Saved match: {result.viki_id} → {result.trakt_id} "
            f"({result.match_confidence:.0%}, {result.match_method})"
        )

    def list_unmatched(self, limit: int = 10) -> List[str]:
        """Get list of unmatched Viki IDs.

        Args:
            limit: Maximum number to return

        Returns:
            List of unmatched Viki IDs
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT viki_id FROM viki_trakt_matches WHERE trakt_id IS NULL LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()

        return [row[0] for row in rows]

    def stats(self) -> Dict[str, int]:
        """Get database statistics.

        Returns:
            Dict with total, matched, unmatched counts
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*), SUM(CASE WHEN trakt_id IS NOT NULL THEN 1 ELSE 0 END) "
                "FROM viki_trakt_matches"
            )
            total, matched = cursor.fetchone()

        return {
            "total": total or 0,
            "matched": matched or 0,
            "unmatched": (total or 0) - (matched or 0),
        }


class ShowMatcher:
    """Match Viki shows to Trakt shows using multi-tier strategy."""

    def __init__(
        self,
        trakt_client_id: Optional[str] = None,
        trakt_client_secret: Optional[str] = None,
        db_path: Optional[Path] = None,
        config_provider: Optional['ConfigProvider'] = None,
    ):
        """Initialize matcher.

        Args:
            trakt_client_id: Trakt API client ID (overrides config)
            trakt_client_secret: Trakt API client secret (overrides config)
            db_path: Path to matches database
            config_provider: Configuration provider (injected dependency)
        """
        self.db = MatchDB(db_path)

        # Get credentials from explicit parameters or config provider
        client_id = trakt_client_id
        client_secret = trakt_client_secret
        
        if not client_id and config_provider:
            trakt_config = config_provider.get_section("trakt")
            client_id = trakt_config.get("client_id")
            client_secret = trakt_config.get("client_secret")

        # Configure Trakt via pytrakt (hard requirement for full sync)
        if not client_id:
            logger.warning("Trakt matching disabled: missing TRAKT_CLIENT_ID")
            self.trakt_available = False
            self.trakt = None
        else:
            self.trakt_available = True
            self.trakt = TraktClient(client_id, client_secret)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        # Ensure HTTP sessions are closed
        try:
            session = get_trakt_session()
            if hasattr(session, 'close'):
                session.close()
        except Exception:
            pass
        
        try:
            session = get_tvdb_session()
            if hasattr(session, 'close'):
                session.close()
        except Exception:
            pass
        
        return False

    def match(self, viki_show: Dict) -> MatchResult:
        """Match Viki show to Trakt show.

        Uses multi-tier matching strategy:
          1. Local cache (instant)
          2. Exact Trakt search (fast)
          3. TVDB search (reliable)
          4. Fuzzy matching (fallback)

        Args:
            viki_show: Dict with Viki show data:
                - viki_id: Show ID
                - titles: Dict of {lang: title}
                - origin: Dict with country/language
                - (optional) year: Show year

        Returns:
            MatchResult with match details
        """
        viki_id = viki_show.get("id") or viki_show.get("viki_id")
        if not viki_id:
            raise ValueError("viki_show missing 'id' or 'viki_id' field")

        # Get English title
        titles = viki_show.get("titles", {})
        viki_title = titles.get("en") or next(iter(titles.values()), f"Unknown ({viki_id})")

        logger.info(f"Matching: {viki_title} (Viki ID: {viki_id})")

        # Tier 1: Check local cache
        cached = self.db.get(viki_id)
        if cached and cached.is_matched():
            logger.debug(f"Cache hit: {viki_id} → {cached.trakt_id}")
            return cached
        elif cached:
            logger.debug(f"Cache has previous no-match for {viki_id}; retrying match")

        # Tier 2: Try exact Trakt search (HTTP). This does not require python-trakt.
        result = self._tier_exact_trakt(viki_show, viki_title)
        # Only return early if confidence is high (0.9+).
        # If confidence is exactly 0.8 (exact_trakt_first fallback), continue to other tiers.
        if result.is_matched() and result.match_confidence > 0.85:
            self.db.save(result)
            return result

        # Tier 3: Try TVDB search
        result = self._tier_tvdb(viki_show, viki_title)
        if result.is_matched() and result.match_confidence > 0.7:
            self.db.save(result)
            return result

        # Tier 3b: Try TVDB alias matching (enhanced)
        result = self._tier_tvdb_aliases(viki_show, viki_title)
        if result.is_matched() and result.match_confidence > 0.65:
            self.db.save(result)
            return result

        # Tier 4: Try MyDramaList alias resolution
        # This helps when Trakt search was uncertain (0.8 confidence exact_trakt_first)
        result = self._tier_mdl(viki_show, viki_title)
        if result.is_matched() and result.match_confidence > 0.6:
            self.db.save(result)
            return result

        # Fallback to Tier 2 result if no better match found
        # (allows low-confidence Trakt matches when no better match available)
        result = self._tier_exact_trakt(viki_show, viki_title)
        if result.is_matched() and result.match_confidence >= 0.8:
            self.db.save(result)
            return result

        # No match found
        result = MatchResult(
            viki_id=viki_id,
            viki_title=viki_title,
            match_confidence=0.0,
            match_method="no_match",
            notes="No matching show found",
        )
        self.db.save(result)
        return result

    def _tier_exact_trakt(
        self, viki_show: Dict, viki_title: str
    ) -> MatchResult:
        """Tier 2: Exact Trakt API search using HTTP requests.

        Args:
            viki_show: Viki show data
            viki_title: Title in English

        Returns:
            MatchResult
        """
        viki_id = viki_show.get("id") or viki_show.get("viki_id")

        if not self.trakt_available or not self.trakt:
            return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="Trakt not configured")

        # Search via pytrakt wrapper (returns list of dicts like HTTP search)
        results = self.trakt.search_shows(viki_title)
        logger.debug(f"Trakt results count={len(results)} for '{viki_title}'")
        if not results:
            logger.debug(f"No Trakt results for: {viki_title}")
            return MatchResult(viki_id=viki_id, viki_title=viki_title)

        # Prefer slug match or normalized title match (with leading-article handling)
        import re

        def _norm(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

        def _norm_no_article(s: str) -> str:
            ns = _norm(s)
            return re.sub(r"^(the|a|an)\s+", "", ns)

        def _slugify(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

        norm_query = _norm(viki_title)
        norm_query_wo = _norm_no_article(viki_title)
        slug_query = _slugify(viki_title)
        slug_query_wo = _slugify(re.sub(r"^(the|a|an)\s+", "", viki_title, flags=re.IGNORECASE))

        chosen = None
        chosen_article = None
        matched_via_article = False
        # 1) One-pass scan: prefer exact normalized, otherwise remember article-dropped match
        for item in results:
            show = item.get("show", {})
            title = show.get("title") or ""
            t_norm = _norm(title)
            if t_norm == norm_query:
                chosen = item
                break
            if chosen_article is None:
                t_norm_wo = _norm_no_article(title)
                if t_norm_wo == norm_query_wo:
                    chosen_article = item
        if chosen is None and chosen_article is not None:
            chosen = chosen_article
            matched_via_article = True
        # 2) Slug startswith match (handles year-suffixed slugs like my-youth-2025)
        if chosen is None:
            for item in results:
                show = item.get("show", {})
                slug = show.get("ids", {}).get("slug") or ""
                if slug.startswith(slug_query):
                    chosen = item
                    break
        # 2b) Slug startswith after dropping leading article
        if chosen is None and slug_query_wo != slug_query:
            for item in results:
                show = item.get("show", {})
                slug = show.get("ids", {}).get("slug") or ""
                if slug.startswith(slug_query_wo):
                    chosen = item
                    matched_via_article = True
                    break
        if chosen is None:
            # 3) Try direct slug lookup via pytrakt (handles shows not indexed by search)
            for slug_try in [slug_query, f"{slug_query}-2025", f"{slug_query}-2024", f"{slug_query}-2026"]:
                data = getattr(self.trakt, "get_show_by_slug", lambda s: None)(slug_try)
                if data:
                    ids = data.get("ids", {})
                    return MatchResult(
                        viki_id=viki_id,
                        viki_title=viki_title,
                        trakt_id=ids.get("trakt"),
                        trakt_slug=ids.get("slug"),
                        trakt_title=data.get("title"),
                        match_confidence=1.0,
                        match_method="slug_lookup",
                        matched_at=datetime.now(timezone.utc),
                    )

            # 4) As last resort, fall back to first search result
            chosen = results[0]

        show_data = chosen.get("show", {})
        trakt_id = show_data.get("ids", {}).get("trakt")
        trakt_slug = show_data.get("ids", {}).get("slug")
        trakt_title = show_data.get("title")

        if _norm(trakt_title) == norm_query or (trakt_slug or "").startswith(slug_query):
            confidence = 1.0
            method = "exact_trakt"
        elif matched_via_article or _norm_no_article(trakt_title) == norm_query_wo or (trakt_slug or "").startswith(slug_query_wo):
            confidence = 0.9
            method = "exact_trakt_article"
        else:
            confidence = 0.8
            method = "exact_trakt_first"

        logger.debug(
            f"Trakt match: {viki_title} → {trakt_title} (ID: {trakt_id}, conf={confidence})"
        )

        return MatchResult(
            viki_id=viki_id,
            viki_title=viki_title,
            trakt_id=trakt_id,
            trakt_slug=trakt_slug,
            trakt_title=trakt_title,
            match_confidence=confidence,
            match_method=method,
            matched_at=datetime.now(timezone.utc),
        )

        

    def _tier_tvdb(self, viki_show: Dict, viki_title: str) -> MatchResult:
        """Tier 3: TVDB search + Trakt lookup by TVDB ID.

        Flow:
          1) Login to TVDB v4 with API key to get bearer token
          2) Search TVDB by viki_title (type=series)
          3) Pick best result (exact normalized match preferred)
          4) Call Trakt: /search/tvdb/{id}?type=show
          5) If found, return MatchResult(method="tvdb")
        """
        viki_id = viki_show.get("id") or viki_show.get("viki_id")

        api_key = os.getenv("TVDB_API_KEY")
        if not api_key:
            return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="Missing TVDB_API_KEY")

        try:
            tvdb = get_tvdb_session()

            # Login to get token
            token_resp = tvdb.session.post(
                "https://api4.thetvdb.com/v4/login",
                json={"apikey": api_key},
                timeout=15,
            )
            if token_resp.status_code != 200:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="TVDB login failed")
            token = token_resp.json().get("data", {}).get("token")
            if not token:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="TVDB token missing")

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            # Search series
            params = {"query": viki_title, "type": "series"}
            search_resp = tvdb.get("https://api4.thetvdb.com/v4/search", params=params, headers=headers)
            if search_resp.status_code != 200:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="TVDB search failed")
            results = search_resp.json().get("data", [])
            if not results:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="TVDB no results")

            import re

            def _norm(s: str) -> str:
                return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

            norm_query = _norm(viki_title)

            # Pick best: normalized name or aliases match
            chosen = None
            for r in results:
                name = r.get("name") or r.get("seriesName") or r.get("title")
                if _norm(name) == norm_query:
                    chosen = r
                    break
                for a in r.get("aliases", []) or []:
                    if _norm(a) == norm_query:
                        chosen = r
                        break
                if chosen:
                    break
            if chosen is None:
                chosen = results[0]

            # TVDB v4 returns "tvdb_id" for some search result items; fallback to "id"
            tvdb_id = chosen.get("tvdb_id") or chosen.get("id")
            if not tvdb_id:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="TVDB id not found")

            # Cross-reference to Trakt by TVDB id via pytrakt
            if not self.trakt:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="Trakt not configured")
            t_show = self.trakt.get_show_by_tvdb(tvdb_id)
            if not t_show:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="Trakt no result for TVDB id")
            ids = t_show.get("ids", {})
            trakt_id = ids.get("trakt")
            trakt_slug = ids.get("slug")
            trakt_title = t_show.get("title")
            if not trakt_id:
                return MatchResult(viki_id=viki_id, viki_title=viki_title, notes="Trakt show missing ids")

            return MatchResult(
                viki_id=viki_id,
                viki_title=viki_title,
                trakt_id=trakt_id,
                trakt_slug=trakt_slug,
                trakt_title=trakt_title,
                tvdb_id=int(tvdb_id) if isinstance(tvdb_id, (int, str)) and str(tvdb_id).isdigit() else None,
                match_confidence=0.95,
                match_method="tvdb",
                matched_at=datetime.now(timezone.utc),
            )

        except requests.RequestException as e:
            logger.debug(f"TVDB/Trakt HTTP error: {e}")
            return MatchResult(viki_id=viki_id, viki_title=viki_title, notes=str(e))

    def _tier_tvdb_aliases(self, viki_show: Dict, viki_title: str) -> MatchResult:
        """Tier 3b: Enhanced TVDB alias matching.

        This tier goes deeper into TVDB's alias list to find matches
        that the initial search might have missed. Useful for shows with
        alternative English titles, romanized titles, etc.

        Flow:
          1) Login to TVDB v4 with API key
          2) Search TVDB broadly by viki_title
          3) For each result, fetch full show details (including aliases)
          4) Check all aliases for normalized matches
          5) Return best match with confidence based on alias type
        """
        viki_id = viki_show.get("id") or viki_show.get("viki_id")

        api_key = os.getenv("TVDB_API_KEY")
        if not api_key:
            return MatchResult(viki_id=viki_id, viki_title=viki_title)

        try:
            tvdb = get_tvdb_session()

            # Login to get token
            token_resp = tvdb.session.post(
                "https://api4.thetvdb.com/v4/login",
                json={"apikey": api_key},
                timeout=15,
            )
            if token_resp.status_code != 200:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            token = token_resp.json().get("data", {}).get("token")
            if not token:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

            # Normalization functions
            import re
            def _norm(s: str) -> str:
                return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

            def _norm_no_article(s: str) -> str:
                ns = _norm(s)
                return re.sub(r"^(the|a|an)\s+", "", ns)

            norm_query = _norm(viki_title)
            norm_query_wo = _norm_no_article(viki_title)

            # Search TVDB
            params = {"query": viki_title, "type": "series"}
            search_resp = tvdb.get("https://api4.thetvdb.com/v4/search", params=params, headers=headers)
            if search_resp.status_code != 200:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            results = search_resp.json().get("data", [])
            if not results:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)

            # For each search result, fetch full details to get aliases
            best_match = None
            best_confidence = 0.0

            for result in results[:10]:  # Check top 10 results
                tvdb_id = result.get("tvdb_id") or result.get("id")
                if not tvdb_id:
                    continue

                # Fetch full series details
                try:
                    detail_resp = tvdb.get(
                        f"https://api4.thetvdb.com/v4/series/{tvdb_id}",
                        headers=headers,
                        timeout=10
                    )
                    if detail_resp.status_code != 200:
                        continue
                    detail_data = detail_resp.json().get("data", {})
                except Exception:
                    continue

                # Check primary name
                primary_name = detail_data.get("name")
                if primary_name and _norm(primary_name) == norm_query:
                    best_match = (tvdb_id, detail_data.get("name"), 0.95, "tvdb_alias_primary")
                    break
                elif primary_name and _norm_no_article(primary_name) == norm_query_wo:
                    if best_confidence < 0.85:
                        best_match = (tvdb_id, primary_name, 0.85, "tvdb_alias_primary_article")
                        best_confidence = 0.85

                # Check aliases
                aliases = detail_data.get("aliases", [])
                if aliases:
                    for alias_item in aliases:
                        alias_name = alias_item.get("language") == "eng" and alias_item.get("name")
                        if alias_name:
                            if _norm(alias_name) == norm_query:
                                best_match = (tvdb_id, alias_name, 0.92, "tvdb_alias_match")
                                break
                            elif _norm_no_article(alias_name) == norm_query_wo:
                                if best_confidence < 0.82:
                                    best_match = (tvdb_id, alias_name, 0.82, "tvdb_alias_match_article")
                                    best_confidence = 0.82

                if best_match and best_match[2] >= 0.92:
                    break

            if not best_match:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)

            tvdb_id, matched_name, confidence, method = best_match

            # Cross-reference to Trakt by TVDB id
            if not self.trakt:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            
            t_show = self.trakt.get_show_by_tvdb(tvdb_id)
            if not t_show:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            
            ids = t_show.get("ids", {})
            trakt_id = ids.get("trakt")
            trakt_slug = ids.get("slug")
            trakt_title = t_show.get("title")
            if not trakt_id:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)

            logger.debug(
                f"TVDB alias match: {viki_title} → {trakt_title} "
                f"(TVDB: {tvdb_id}, Trakt: {trakt_id}, conf={confidence}, via={method})"
            )

            return MatchResult(
                viki_id=viki_id,
                viki_title=viki_title,
                trakt_id=trakt_id,
                trakt_slug=trakt_slug,
                trakt_title=trakt_title,
                tvdb_id=int(tvdb_id) if isinstance(tvdb_id, (int, str)) and str(tvdb_id).isdigit() else None,
                match_confidence=confidence,
                match_method=method,
                matched_at=datetime.now(timezone.utc),
            )

        except requests.RequestException as e:
            logger.debug(f"TVDB alias tier HTTP error: {e}")
            return MatchResult(viki_id=viki_id, viki_title=viki_title)

    def _tier_mdl(self, viki_show: Dict, viki_title: str) -> MatchResult:
        """Tier 4: MyDramaList alias resolution.

        Scrapes MDL to find English aliases + Viki ID,
        then searches TVDB with those aliases for TVDB ID,
        then cross-references to Trakt.

        Flow:
          1) Search MDL by viki_title (HTML scrape)
          2) Load MDL detail page
          3) Extract English aliases from page
          4) Search TVDB with each alias (decreasing confidence)
          5) Cross-reference to Trakt by TVDB ID
          6) Cache Viki ID from MDL for future use
        """
        viki_id = viki_show.get("id") or viki_show.get("viki_id")
        
        try:
            from .mdl_client import MdlClient
            mdl = MdlClient()
            
            # Step 1-3: Search MDL, load detail, extract aliases
            mdl_data = mdl.search_alias(viki_title)
            if not mdl_data:
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            
            english_aliases = mdl_data.get("english_aliases", [])
            mdl_viki_id = mdl_data.get("viki_id")
            
            logger.debug(
                f"MDL found {viki_title}: "
                f"{len(english_aliases)} aliases, Viki ID: {mdl_viki_id}"
            )
            
            if not english_aliases:
                logger.debug(f"MDL {viki_title}: No English aliases found")
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            
            # Step 4: Try to match each alias to TVDB
            api_key = os.getenv("TVDB_API_KEY")
            if not api_key:
                logger.debug("MDL tier: Missing TVDB_API_KEY")
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
            
            try:
                tvdb = get_tvdb_session()
                
                # Try each English alias with decreasing confidence
                for i, alias in enumerate(english_aliases):
                    confidence_boost = 0.95 - (i * 0.03)  # 0.95, 0.92, 0.89, ...
                    
                    search_resp = tvdb.session.get(
                        f"{tvdb.base_url}/search",
                        params={"query": alias, "type": "series"},
                        headers=tvdb.headers,
                        timeout=10
                    )
                    
                    if search_resp.status_code != 200:
                        continue
                    
                    results = search_resp.json().get("data", [])
                    if not results:
                        continue
                    
                    # Use first TVDB result
                    tvdb_id = results[0].get("tvdb_id")
                    tvdb_name = results[0].get("name")
                    
                    if not tvdb_id:
                        continue
                    
                    # Cross-reference to Trakt
                    if not self.trakt:
                        continue
                    
                    t_show = self.trakt.get_show_by_tvdb(tvdb_id)
                    if not t_show:
                        continue
                    
                    ids = t_show.get("ids", {})
                    trakt_id = ids.get("trakt")
                    trakt_slug = ids.get("slug")
                    trakt_title = t_show.get("title")
                    
                    if not trakt_id:
                        continue
                    
                    logger.debug(
                        f"MDL match: {viki_title} → {trakt_title} "
                        f"(via MDL alias: {alias}, TVDB: {tvdb_id})"
                    )
                    
                    return MatchResult(
                        viki_id=viki_id,
                        viki_title=viki_title,
                        trakt_id=trakt_id,
                        trakt_slug=trakt_slug,
                        trakt_title=trakt_title,
                        tvdb_id=tvdb_id,
                        match_confidence=confidence_boost,
                        match_method="mdl",
                        matched_at=datetime.now(timezone.utc),
                    )
                
                # No alias matched to Trakt
                logger.debug(f"MDL {viki_title}: Aliases found but no Trakt match")
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
                
            except Exception as e:
                logger.debug(f"MDL TVDB lookup error: {e}")
                return MatchResult(viki_id=viki_id, viki_title=viki_title)
                
        except Exception as e:
            logger.debug(f"MDL tier error: {e}")
            return MatchResult(viki_id=viki_id, viki_title=viki_title)

