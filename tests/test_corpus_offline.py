import json
import os
from pathlib import Path
import pytest

from viki_trakt_sync.matcher import ShowMatcher


class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, items):
        # items: list from corpus with trakt_search and trakt_slug_fetch
        self._by_query = {}
        self._by_slug = {}
        for it in items:
            title = it.get("viki_titles", {}).get("en") or next(iter(it.get("viki_titles", {}).values()), "")
            if title:
                self._by_query[title] = it.get("trakt_search") or []
            for slug, data in (it.get("trakt_slug_fetch") or {}).items():
                self._by_slug[slug] = data

    def get(self, url, params=None, headers=None):
        if url.startswith("https://api.trakt.tv/search"):
            q = (params or {}).get("query")
            data = self._by_query.get(q, [])
            return FakeResponse(200, data)
        if url.startswith("https://api.trakt.tv/shows/"):
            slug = url.rsplit("/", 1)[-1]
            if slug in self._by_slug:
                return FakeResponse(200, self._by_slug[slug])
            return FakeResponse(404, {})
        return FakeResponse(404, {})


def monkeypatch_trakt_session(monkeypatch, items):
    from viki_trakt_sync import matcher as matcher_mod

    def _fake_get_trakt_session():
        return FakeSession(items)

    monkeypatch.setattr(matcher_mod, "get_trakt_session", _fake_get_trakt_session, raising=True)


@pytest.mark.skipif(not (Path.home() / ".config" / "viki-trakt-sync" / "match_corpus.json").exists(),
                    reason="offline corpus not found; build with CLI dataset build")
def test_offline_corpus_repro(monkeypatch):
    # Load corpus once; ensure matcher reproduces stored results using offline responses
    path = Path.home() / ".config" / "viki-trakt-sync" / "match_corpus.json"
    data = json.loads(path.read_text())
    items = data.get("items", [])
    assert items, "empty corpus"

    monkeypatch_trakt_session(monkeypatch, items)

    matcher = ShowMatcher()

    # Evaluate a reasonable subset to keep test time low
    subset = items[:50]
    mismatches = []
    for it in subset:
        viki_show = {"id": it["viki_id"], "titles": it.get("viki_titles", {}), "origin": it.get("origin", {})}
        got = matcher.match(viki_show).to_dict()
        exp = it.get("matched", {})
        # Compare key aspects
        if (got.get("trakt_id"), got.get("trakt_slug")) != (exp.get("trakt_id"), exp.get("trakt_slug")):
            mismatches.append((it["viki_id"], exp.get("trakt_slug"), got.get("trakt_slug")))

    assert not mismatches, f"reproduction mismatches: {mismatches[:5]} (showing first 5)"

