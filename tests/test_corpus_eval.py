"""Corpus evaluation test - evaluate full Viki show catalog matching."""

import json
import logging
from pathlib import Path

import pytest

from viki_trakt_sync.matcher import ShowMatcher


@pytest.fixture
def corpus_data():
    """Load corpus from config directory."""
    corpus_path = Path.home() / ".config" / "viki-trakt-sync" / "match_corpus.json"
    if not corpus_path.exists():
        pytest.skip("Corpus file not found - run corpus extraction first")
    
    with open(corpus_path) as f:
        return json.load(f)


def test_corpus_match_rate(corpus_data, caplog):
    """Test that corpus matches at least 98% of shows."""
    shows = corpus_data.get("items", [])
    assert len(shows) > 0, "Corpus should have shows"
    
    caplog.set_level(logging.WARNING)
    
    matched = 0
    by_method = {}
    unmatched = []
    errors = []
    
    # Use context manager for matcher to ensure cleanup
    with ShowMatcher() as matcher:
        for show in shows:
            try:
                result = matcher.match(show)
                assert result is not None, f"Match returned None for {show}"
                
                if result.is_matched():
                    matched += 1
                    method = result.match_method or "unknown"
                    by_method[method] = by_method.get(method, 0) + 1
                else:
                    unmatched.append(show.get("titles", {}).get("en", "Unknown"))
            except Exception as e:
                errors.append((show.get("titles", {}).get("en", "Unknown"), str(e)))
    
    match_rate = matched / len(shows)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"CORPUS EVALUATION")
    print(f"{'='*60}")
    print(f"Total shows: {len(shows)}")
    print(f"Matched: {matched} ({100*match_rate:.1f}%)")
    print(f"Unmatched: {len(unmatched)} ({100*(1-match_rate):.1f}%)")
    
    if by_method:
        print(f"\nMatches by method:")
        for method, count in sorted(by_method.items(), key=lambda x: -x[1]):
            pct = 100 * count / matched
            print(f"  {method:20s}: {count:4d} ({pct:.1f}%)")
    
    if errors:
        print(f"\nErrors: {len(errors)}")
        for title, error in errors[:5]:
            print(f"  - {title}: {error}")
        if len(errors) > 5:
            print(f"  ... and {len(errors)-5} more")
    
    if unmatched:
        print(f"\nUnmatched ({len(unmatched)}):")
        for title in unmatched[:10]:
            if title and title != "Unknown":
                print(f"  - {title}")
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched)-10} more")
    
    # Assert minimum match rate
    assert match_rate >= 0.98, f"Expected 98%+ match rate, got {100*match_rate:.1f}%"
    assert len(errors) == 0, f"Should have no errors, got {len(errors)}"
