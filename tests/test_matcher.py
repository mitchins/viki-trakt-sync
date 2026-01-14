import os
from pathlib import Path

import types

from viki_trakt_sync.matcher import ShowMatcher
from viki_trakt_sync import matcher as matcher_mod
import pytest


@pytest.fixture(autouse=True)
def _ensure_trakt_env(monkeypatch):
    # Ensure matcher enables Trakt HTTP search branch during tests
    monkeypatch.setenv("TRAKT_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("TRAKT_CLIENT_SECRET", "test-client-secret")


def monkeypatch_trakt_search(monkeypatch, results, slug_map=None):
    class FakeTC:
        def __init__(self, *_args, **_kwargs):
            pass

        def search_shows(self, title: str):
            return results

        def get_show_by_slug(self, slug: str):
            if slug_map and slug in slug_map:
                return slug_map[slug]
            return None

    monkeypatch.setattr(matcher_mod, "TraktClient", FakeTC, raising=True)


def test_exact_title_match(monkeypatch, tmp_path):
    # Arrange: search results include an exact title match not at index 0
    def is_search(url, params, headers):
        return url.startswith("https://api.trakt.tv/search") and params and params.get("query") == "Ms. Incognito"

    def handle_search(url, params, headers):
        return FakeResponse(200, [
            {"type": "show", "show": {"title": "Some Other", "ids": {"trakt": 1, "slug": "some-other"}}},
            {"type": "show", "show": {"title": "Ms. Incognito", "ids": {"trakt": 261744, "slug": "ms-incognito"}}},
        ])

    results = [
        {"type": "show", "show": {"title": "Some Other", "ids": {"trakt": 1, "slug": "some-other"}}},
        {"type": "show", "show": {"title": "Ms. Incognito", "ids": {"trakt": 261744, "slug": "ms-incognito"}}},
    ]
    monkeypatch_trakt_search(monkeypatch, results)

    matcher = ShowMatcher(db_path=tmp_path / "matches.db")

    viki_show = {"id": "X", "titles": {"en": "Ms. Incognito"}}
    result = matcher.match(viki_show)

    assert result.is_matched()
    assert result.trakt_id == 261744
    assert result.trakt_slug == "ms-incognito"
    assert result.match_confidence == 1.0
    assert result.match_method in ("exact_trakt", "exact_trakt_first")


def test_slug_lookup_fallback(monkeypatch, tmp_path):
    # Arrange: search for "IDOL I" returns no exact; slug lookup returns the show
    def is_search(url, params, headers):
        return url.startswith("https://api.trakt.tv/search") and params and params.get("query") == "IDOL I"

    def handle_search(url, params, headers):
        return FakeResponse(200, [
            {"type": "show", "show": {"title": "Weekly Idol", "ids": {"trakt": 72872, "slug": "weekly-idol"}}},
            {"type": "show", "show": {"title": "New Zealand Idol", "ids": {"trakt": 277090, "slug": "new-zealand-idol"}}},
        ])

    def is_slug(url, params, headers):
        return url == "https://api.trakt.tv/shows/idol-i"

    def handle_slug(url, params, headers):
        return FakeResponse(200, {"title": "Idol I", "ids": {"trakt": 277843, "slug": "idol-i"}})

    results = [
        {"type": "show", "show": {"title": "Weekly Idol", "ids": {"trakt": 72872, "slug": "weekly-idol"}}},
        {"type": "show", "show": {"title": "New Zealand Idol", "ids": {"trakt": 277090, "slug": "new-zealand-idol"}}},
    ]
    slug_map = {"idol-i": {"title": "Idol I", "ids": {"trakt": 277843, "slug": "idol-i"}}}
    monkeypatch_trakt_search(monkeypatch, results, slug_map)

    matcher = ShowMatcher(db_path=tmp_path / "matches.db")
    viki_show = {"id": "Y", "titles": {"en": "IDOL I"}}
    result = matcher.match(viki_show)

    assert result.is_matched()
    assert result.trakt_slug == "idol-i"
    assert result.match_method == "slug_lookup"
    assert result.match_confidence == 1.0


def test_first_result_fallback_when_no_slug(monkeypatch, tmp_path):
    # Arrange: search returns results, no exact match; slug lookups return 404
    query = "Some Title"

    def is_search(url, params, headers):
        return url.startswith("https://api.trakt.tv/search") and params and params.get("query") == query

    def handle_search(url, params, headers):
        return FakeResponse(200, [
            {"type": "show", "show": {"title": "Other", "ids": {"trakt": 111, "slug": "other"}}},
            {"type": "show", "show": {"title": "Different", "ids": {"trakt": 222, "slug": "different"}}},
        ])

    def is_any_slug(url, params, headers):
        return url.startswith("https://api.trakt.tv/shows/")

    def handle_404(url, params, headers):
        return FakeResponse(404, {})

    results = [
        {"type": "show", "show": {"title": "Other", "ids": {"trakt": 111, "slug": "other"}}},
        {"type": "show", "show": {"title": "Different", "ids": {"trakt": 222, "slug": "different"}}},
    ]
    monkeypatch_trakt_search(monkeypatch, results)

    matcher = ShowMatcher(db_path=tmp_path / "matches.db")
    viki_show = {"id": "Z", "titles": {"en": query}}
    result = matcher.match(viki_show)

    assert result.is_matched()
    assert result.trakt_id == 111  # first item chosen
    assert result.match_confidence == 0.8
    assert result.match_method == "exact_trakt_first"


def test_article_drop_match(monkeypatch, tmp_path):
    # Query: "The Divorce Lawyer in Love" should match Trakt "Divorce Lawyer in Love"
    query = "The Divorce Lawyer in Love"

    def is_search(url, params, headers):
        return url.startswith("https://api.trakt.tv/search") and params and params.get("query") == query

    def handle_search(url, params, headers):
        return FakeResponse(200, [
            {"type": "show", "show": {"title": "Other", "ids": {"trakt": 555, "slug": "other"}}},
            {"type": "show", "show": {"title": "Divorce Lawyer in Love", "ids": {"trakt": 204040, "slug": "divorce-lawyer-in-love"}}},
        ])

    results = [
        {"type": "show", "show": {"title": "Other", "ids": {"trakt": 555, "slug": "other"}}},
        {"type": "show", "show": {"title": "Divorce Lawyer in Love", "ids": {"trakt": 204040, "slug": "divorce-lawyer-in-love"}}},
    ]
    monkeypatch_trakt_search(monkeypatch, results)

    matcher = ShowMatcher(db_path=tmp_path / "matches.db")
    viki_show = {"id": "DLIL", "titles": {"en": query}}
    result = matcher.match(viki_show)

    assert result.is_matched()
    assert result.trakt_slug == "divorce-lawyer-in-love"
    assert result.match_method == "exact_trakt_article"
    assert result.match_confidence == 0.9
