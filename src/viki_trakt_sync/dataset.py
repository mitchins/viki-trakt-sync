"""Matching corpus builder for offline testing.

Collects Viki containers via browse endpoints, fetches Trakt search
results and slug lookups, runs the current matcher, and stores a corpus
JSON for repeatable offline tests without network.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .viki_client import VikiClient
from .http_cache import get_trakt_session
from .matcher import ShowMatcher, MatchResult

logger = logging.getLogger(__name__)


@dataclass
class CorpusItem:
    viki_id: str
    viki_titles: Dict[str, str]
    origin: Dict
    trakt_search: List[Dict]
    trakt_slug_fetch: Dict[str, Dict]  # slug -> show object
    matched: Dict  # MatchResult as dict


class MatchCorpusBuilder:
    def __init__(self, token: str, user_id: Optional[str] = None):
        self.viki = VikiClient(token=token, user_id=user_id)
        self.session = get_trakt_session()
        self.matcher = ShowMatcher()

    @staticmethod
    def default_path() -> Path:
        p = Path.home() / ".config" / "viki-trakt-sync" / "match_corpus.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _browse_containers(self, target: int = 300) -> List[str]:
        """Heuristically browse container IDs across countries/sorts."""
        ids: List[str] = []
        seen: Set[str] = set()

        # A few useful axes to diversify
        countries = ["kr", "cn", "jp", "tw"]
        sorts = ["views", "views_recent", "average_rating", "latest"]
        per_page = 50

        for country in countries:
            for sort in sorts:
                page = 1
                while len(ids) < target and page <= 10:
                    url = f"https://api.viki.io/v4/containers.json"
                    params = {
                        "token": self.viki.token,
                        "type": "series",
                        "origin_country": country,
                        "sort": sort,
                        "direction": "desc",
                        "per_page": per_page,
                        "page": page,
                        "app": self.viki.APP_ID,
                    }
                    r = self.viki.session.get(url, params=params)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    items = data.get("response", [])
                    if not items:
                        break
                    for it in items:
                        cid = it.get("id")
                        if cid and cid not in seen:
                            ids.append(cid)
                            seen.add(cid)
                    if not data.get("more", False):
                        break
                    page += 1

                if len(ids) >= target:
                    break
            if len(ids) >= target:
                break
        logger.info(f"Collected {len(ids)} container IDs across browse endpoints")
        return ids

    def _trakt_search(self, title: str) -> List[Dict]:
        params = {"type": "show", "query": title}
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": os.getenv("TRAKT_CLIENT_ID", ""),
        }
        r = self.session.get("https://api.trakt.tv/search", params=params, headers=headers)
        if r.status_code != 200:
            return []
        return r.json() or []

    def _trakt_slug_fetch(self, slug_candidates: List[str]) -> Dict[str, Dict]:
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": os.getenv("TRAKT_CLIENT_ID", ""),
        }
        out: Dict[str, Dict] = {}
        for slug in slug_candidates:
            if not slug:
                continue
            url = f"https://api.trakt.tv/shows/{slug}"
            r = self.session.get(url, headers=headers)
            if r.status_code == 200:
                out[slug] = r.json()
        return out

    def build(self, out_path: Optional[Path] = None, target: int = 300, pretty: bool = False) -> Path:
        out_path = out_path or self.default_path()

        ids = self._browse_containers(target=target)

        corpus: List[Dict] = []
        for idx, cid in enumerate(ids, 1):
            try:
                meta = self.viki.get_container(cid)
            except Exception:
                continue
            titles = meta.get("titles", {})
            title_en = titles.get("en") or next(iter(titles.values()), "")
            origin = meta.get("origin", {})

            # Gather Trakt context
            search = self._trakt_search(title_en)

            # Slug candidates from title normalization and common year suffixes
            import re
            slug_base = re.sub(r"[^a-z0-9]+", "-", title_en.lower()).strip("-")
            slug_candidates = [slug_base] + [f"{slug_base}-{y}" for y in (2024, 2025, 2026)]
            slug_fetch = self._trakt_slug_fetch(slug_candidates)

            # Current matcher result
            result: MatchResult = self.matcher.match({
                "id": cid,
                "titles": titles,
                "origin": origin,
            })

            corpus.append({
                "viki_id": cid,
                "viki_titles": titles,
                "origin": origin,
                "trakt_search": search,
                "trakt_slug_fetch": slug_fetch,
                "matched": result.to_dict(),
            })

            if idx % 25 == 0:
                logger.info(f"Processed {idx}/{len(ids)}")

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                {"count": len(corpus), "items": corpus},
                f,
                ensure_ascii=False,
                indent=2 if pretty else None,
                sort_keys=pretty,
            )
            if pretty:
                f.write("\n")

        logger.info(f"Wrote corpus: {out_path} ({len(corpus)} items)")
        return out_path

    @staticmethod
    def load(path: Optional[Path] = None) -> Dict:
        path = path or MatchCorpusBuilder.default_path()
        with open(path) as f:
            return json.load(f)
