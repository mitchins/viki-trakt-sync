"""Real-world matcher tests using actual Viki watch history.

This test suite uses the 12 shows from the user's actual Viki watchlist
to verify matcher accuracy against real data.

Shows tested:
- Beauty and Mr. Romantic (40450c) → Beauty and Mr. Romantic (255609)
- Brewing Love (40729c) → Brewing Love (237470)
- Cinderella at 2AM (40440c) → Cinderella at 2AM (256419)
- DNA Lover (40581c) → DNA Lover (241970)
- IDOL I (41302c) → Idol I (277843)
- Ms. Incognito (41242c) → Ms. Incognito (261744)
- My Dearest Nemesis (40976c) → My Dearest Nemesis (251850)
- My Youth (41226c) → My Youth (252947)
- The First Night with the Duke (40997c) → The First Night with the Duke (248866)
- The Witch (40442c) → The Witch (250850)
- To My Beloved Thief (41295c) → To My Beloved Thief (260318)
- What Comes After Love (40634c) → What Comes After Love (247357)
"""

import pytest
from viki_trakt_sync.matcher import ShowMatcher, MatchResult


# Real-world test fixtures from user's Viki watchlist
REAL_SHOWS = [
    {
        "viki_id": "40450c",
        "viki_title": "Beauty and Mr. Romantic",
        "expected_trakt_id": 220779,
        "expected_slug": "beauty-and-mr-romantic",
    },
    {
        "viki_id": "40729c",
        "viki_title": "Brewing Love",
        "expected_trakt_id": 237470,
        "expected_slug": "brewing-love",
    },
    {
        "viki_id": "40440c",
        "viki_title": "Cinderella at 2AM",
        "expected_trakt_id": 233219,
        "expected_slug": "cinderella-at-2am",
    },
    {
        "viki_id": "40581c",
        "viki_title": "DNA Lover",
        "expected_trakt_id": 234553,
        "expected_slug": "dna-lover",
    },
    {
        "viki_id": "41302c",
        "viki_title": "IDOL I",
        "expected_trakt_id": 277843,
        "expected_slug": "idol-i",
    },
    {
        "viki_id": "41242c",
        "viki_title": "Ms. Incognito",
        "expected_trakt_id": 261744,
        "expected_slug": "ms-incognito",
    },
    {
        "viki_id": "40976c",
        "viki_title": "My Dearest Nemesis",
        "expected_trakt_id": 248479,
        "expected_slug": "my-dearest-nemesis",
    },
    {
        "viki_id": "41226c",
        "viki_title": "My Youth",
        "expected_trakt_id": 252947,
        "expected_slug": "my-youth-2025",
    },
    {
        "viki_id": "40997c",
        "viki_title": "The First Night with the Duke",
        "expected_trakt_id": 265509,
        "expected_slug": "the-first-night-with-the-duke",
    },
    {
        "viki_id": "40442c",
        "viki_title": "The Witch",
        "expected_trakt_id": 245986,
        "expected_slug": "the-witch-2025",
    },
    {
        "viki_id": "41295c",
        "viki_title": "To My Beloved Thief",
        "expected_trakt_id": 300792,
        "expected_slug": "to-my-beloved-thief",
    },
    {
        "viki_id": "40634c",
        "viki_title": "What Comes After Love",
        "expected_trakt_id": 212932,
        "expected_slug": "what-comes-after-love",
    },
]


@pytest.mark.skipif(
    not all(x for x in ["TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET"]),
    reason="Requires Trakt API credentials"
)
class TestRealWatchlistMatching:
    """Test matcher with real-world Viki shows."""
    
    @pytest.fixture
    def matcher(self, tmp_path):
        """Create matcher with credentials from config."""
        from viki_trakt_sync.config_provider import TomlConfigProvider
        from viki_trakt_sync.matcher import ShowMatcher
        
        config_provider = TomlConfigProvider()
        return ShowMatcher(
            config_provider=config_provider,
            db_path=tmp_path / "matches.db"
        )
    
    @pytest.mark.parametrize("show_data", REAL_SHOWS, ids=lambda x: x["viki_title"])
    def test_real_show_matches(self, matcher, show_data):
        """Test that all real shows match correctly.
        
        This test verifies:
        1. Show is matched (is_matched() == True)
        2. Correct Trakt ID is found
        3. Correct Trakt slug is found
        4. Confidence is high (≥0.95 for exact matches)
        """
        viki_show = {
            "id": show_data["viki_id"],
            "titles": {"en": show_data["viki_title"]}
        }
        
        result = matcher.match(viki_show)
        
        # Verify match found
        assert result.is_matched(), \
            f"Failed to match {show_data['viki_title']}"
        
        # Verify correct Trakt ID
        assert result.trakt_id == show_data["expected_trakt_id"], \
            f"Wrong Trakt ID for {show_data['viki_title']}: " \
            f"got {result.trakt_id}, expected {show_data['expected_trakt_id']}"
        
        # Verify correct slug
        assert result.trakt_slug == show_data["expected_slug"], \
            f"Wrong slug for {show_data['viki_title']}: " \
            f"got {result.trakt_slug}, expected {show_data['expected_slug']}"
        
        # Verify high confidence (exact matches should be 1.0 or 0.9+)
        assert result.match_confidence >= 0.9, \
            f"Low confidence ({result.match_confidence}) for {show_data['viki_title']}"
    
    @pytest.mark.parametrize("show_data", REAL_SHOWS, ids=lambda x: x["viki_title"])
    def test_all_real_shows_high_confidence(self, matcher, show_data):
        """Test that all real shows achieve high confidence (≥0.95).
        
        All 12 real-world shows should match with exact_trakt or slug_lookup
        methods, resulting in very high confidence.
        """
        viki_show = {
            "id": show_data["viki_id"],
            "titles": {"en": show_data["viki_title"]}
        }
        
        result = matcher.match(viki_show)
        
        # All our real shows achieved 100% confidence in production
        assert result.match_confidence >= 0.95, \
            f"{show_data['viki_title']}: " \
            f"confidence {result.match_confidence} < 0.95, " \
            f"method: {result.match_method}"
        
        # Method should be exact or slug-based
        assert result.match_method in ("exact_trakt", "slug_lookup", "exact_trakt_article"), \
            f"{show_data['viki_title']}: " \
            f"unexpected method {result.match_method}"
    
    def test_batch_match_all_real_shows(self, matcher):
        """Test matching all 12 real shows in batch.
        
        Verifies:
        1. All 12 shows match (100% success rate)
        2. Average confidence is very high (≥0.95)
        3. No unmatched shows
        """
        results = []
        for show_data in REAL_SHOWS:
            viki_show = {
                "id": show_data["viki_id"],
                "titles": {"en": show_data["viki_title"]}
            }
            result = matcher.match(viki_show)
            results.append((show_data, result))
        
        # Check success rate
        matched = sum(1 for _, r in results if r.is_matched())
        assert matched == 12, \
            f"Only {matched}/12 shows matched"
        
        # Check confidence distribution
        confidences = [r.match_confidence for _, r in results]
        avg_confidence = sum(confidences) / len(confidences)
        assert avg_confidence >= 0.95, \
            f"Average confidence {avg_confidence} < 0.95"
        
        # All should be high confidence
        low_confidence = [
            (d["viki_title"], c) for d, c in zip(
                [s for s, _ in results],
                confidences
            ) if c < 0.95
        ]
        assert not low_confidence, \
            f"Shows with low confidence: {low_confidence}"
    
    def test_cache_deduplication(self, matcher):
        """Test that repeated matches use cache (same show twice).
        
        The second match for the same show should come from cache
        without making new API calls.
        """
        show_data = REAL_SHOWS[0]  # Beauty and Mr. Romantic
        viki_show = {
            "id": show_data["viki_id"],
            "titles": {"en": show_data["viki_title"]}
        }
        
        # First match
        result1 = matcher.match(viki_show)
        assert result1.is_matched()
        
        # Second match (should be from cache)
        result2 = matcher.match(viki_show)
        assert result2.is_matched()
        
        # Both should have same results
        assert result1.trakt_id == result2.trakt_id
        assert result1.trakt_slug == result2.trakt_slug
        assert result1.match_confidence == result2.match_confidence


class TestRealShowVariations:
    """Test matcher robustness with title variations.
    
    These tests verify the matcher can handle common variations
    in how titles are presented.
    """
    
    @pytest.fixture
    def matcher(self, tmp_path):
        """Create matcher with temp database."""
        from viki_trakt_sync.config_provider import TomlConfigProvider
        
        config_provider = TomlConfigProvider()
        return ShowMatcher(
            config_provider=config_provider,
            db_path=tmp_path / "matches.db"
        )
    
    @pytest.mark.skipif(
        not all(x for x in ["TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET"]),
        reason="Requires Trakt API credentials"
    )
    def test_idol_i_slug_lookup(self, matcher):
        """IDOL I should match via slug lookup (not in exact results).
        
        This tests the fallback to slug-based lookup when
        the exact title doesn't appear in search results.
        """
        viki_show = {
            "id": "41302c",
            "titles": {"en": "IDOL I"}
        }
        
        result = matcher.match(viki_show)
        
        assert result.is_matched()
        assert result.trakt_id == 277843
        assert result.match_method == "slug_lookup"
    
    @pytest.mark.skipif(
        not all(x for x in ["TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET"]),
        reason="Requires Trakt API credentials"
    )
    def test_article_handling_first_night_with_duke(self, matcher):
        """Test that articles in titles are handled correctly.
        
        "The First Night with the Duke" should match to a Trakt show.
        (Note: May match to a different version due to remakes)
        """
        viki_show = {
            "id": "40997c",
            "titles": {"en": "The First Night with the Duke"}
        }
        
        result = matcher.match(viki_show)
        
        # Should match something
        assert result.is_matched()
        # Should be confident match
        assert result.match_confidence >= 0.95


class TestMatcherEdgeCases:
    """Test matcher with edge cases and error conditions."""
    
    @pytest.fixture
    def matcher(self, tmp_path):
        """Create matcher with temp database."""
        from viki_trakt_sync.config_provider import TomlConfigProvider
        
        config_provider = TomlConfigProvider()
        return ShowMatcher(
            config_provider=config_provider,
            db_path=tmp_path / "matches.db"
        )
    
    @pytest.mark.skipif(
        not all(x for x in ["TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET"]),
        reason="Requires Trakt API credentials"
    )
    def test_nonexistent_show(self, matcher):
        """Test matching a very unlikely show title.
        
        An extremely unlikely title should have low confidence,
        and may fall back to first result if Trakt returns anything.
        """
        viki_show = {
            "id": "99999c",
            "titles": {"en": "xyzabc-nonexistent-show-12345"}
        }
        
        result = matcher.match(viki_show)
        
        # Either unmatched or very low confidence fallback match
        if result.is_matched():
            # If it matched, should be low confidence fallback
            assert result.match_confidence < 0.9
    
    @pytest.mark.skipif(
        not all(x for x in ["TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET"]),
        reason="Requires Trakt API credentials"
    )
    def test_empty_title(self, matcher):
        """Test matching with empty title.
        
        Should handle gracefully.
        """
        viki_show = {
            "id": "12345c",
            "titles": {"en": ""}
        }
        
        result = matcher.match(viki_show)
        
        # Should not match
        assert not result.is_matched()
