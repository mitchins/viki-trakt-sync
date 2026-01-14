import os
import pytest

from viki_trakt_sync.matcher import ShowMatcher


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    # Ensure env IDs are present for HTTP matching
    monkeypatch.setenv("TRAKT_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("TVDB_API_KEY", "test-tvdb-key")


def test_article_drop_match_requests_mock(requests_mock, tmp_path):
    # Trakt search returns a second result without the leading article
    query = "The Divorce Lawyer in Love"

    def _match_params(request):
        params = request.qs
        return params.get("type", [None])[0] == "show" and params.get("query", [None])[0] == query

    requests_mock.get(
        "https://api.trakt.tv/search",
        additional_matcher=_match_params,
        json=[
            {"type": "show", "show": {"title": "Other", "ids": {"trakt": 555, "slug": "other"}}},
            {
                "type": "show",
                "show": {
                    "title": "Divorce Lawyer in Love",
                    "ids": {"trakt": 204040, "slug": "divorce-lawyer-in-love"},
                },
            },
        ],
        status_code=200,
    )

    matcher = ShowMatcher(db_path=tmp_path / "matches.db")
    res = matcher.match({"id": "X", "titles": {"en": query}})

    assert res.is_matched()
    assert res.trakt_slug == "divorce-lawyer-in-love"
    assert res.match_method == "exact_trakt_article"
    assert res.match_confidence == 0.9


def test_tvdb_alias_crossref_requests_mock(requests_mock, tmp_path):
    # TVDB login
    requests_mock.post(
        "https://api4.thetvdb.com/v4/login",
        json={"data": {"token": "tvdb-token"}},
        status_code=200,
    )

    # TVDB search returns an alias that matches the Viki title
    viki_title = "Hello, My Twenties!"

    def _tvdb_params(request):
        params = request.qs
        return params.get("query", [None])[0] == viki_title and params.get("type", [None])[0] == "series"

    requests_mock.get(
        "https://api4.thetvdb.com/v4/search",
        additional_matcher=_tvdb_params,
        json={
            "data": [
                {
                    "id": 123456,
                    "name": "Age of Youth",
                    "aliases": ["Hello, My Twenties!"],
                }
            ]
        },
        status_code=200,
    )

    # Trakt lookup by TVDB id
    def _trakt_tvdb_params(request):
        params = request.qs
        return params.get("type", [None])[0] == "show"

    requests_mock.get(
        "https://api.trakt.tv/search/tvdb/123456",
        additional_matcher=_trakt_tvdb_params,
        json=[
            {
                "type": "show",
                "show": {
                    "title": "Age of Youth",
                    "ids": {"trakt": 108834, "slug": "age-of-youth"},
                },
            }
        ],
        status_code=200,
    )

    matcher = ShowMatcher(db_path=tmp_path / "matches.db")
    res = matcher.match({"id": "Y", "titles": {"en": viki_title}})

    assert res.is_matched()
    assert res.trakt_slug == "age-of-youth"
    assert res.match_method == "tvdb"
    assert res.match_confidence >= 0.95

