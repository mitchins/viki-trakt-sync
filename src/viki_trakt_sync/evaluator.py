"""Matching evaluation and detailed comparison tool.

Evaluates matching results in three tiers:
1. Exact matches (confidence >= 0.95)
2. Close fuzzy matches (0.70-0.95)
3. No matches (< 0.70 or unmatched)

Useful for debugging and reviewing match quality.
"""

import logging
from typing import Dict, List, Optional, Tuple

from .cache import WatchHistoryCache
from .matcher import ShowMatcher, MatchResult

logger = logging.getLogger(__name__)


class MatchingEvaluator:
    """Evaluate matching results and categorize by confidence."""

    def __init__(self):
        """Initialize evaluator."""
        self.watch_cache = WatchHistoryCache()
        self.matcher = ShowMatcher()

    def get_watch_shows(self) -> Dict[str, Dict]:
        """Get watch history shows from cache.

        Returns:
            Dict of {viki_id: show_data}
        """
        cache_data = self.watch_cache.get()
        if not cache_data:
            raise RuntimeError("Watch history not cached. Run: cache init")

        # Try to get show details from cache (shows dict)
        if "shows" in cache_data:
            return cache_data.get("shows", {})

        # Fallback to just markers (old cache format)
        markers = cache_data.get("markers", {})
        return {viki_id: {"id": viki_id} for viki_id in markers.keys()}

    def evaluate_all(
        self, limit: Optional[int] = None, verbose: bool = False
    ) -> Tuple[List[MatchResult], List[MatchResult], List[MatchResult]]:
        """Evaluate all shows and categorize by confidence.

        Args:
            limit: Max shows to evaluate (None = all)
            verbose: Print debug info during evaluation

        Returns:
            Tuple of (exact_matches, close_matches, no_matches)
        """
        shows = self.get_watch_shows()

        if limit:
            show_items = list(shows.items())[:limit]
        else:
            show_items = list(shows.items())

        exact_matches: List[MatchResult] = []
        close_matches: List[MatchResult] = []
        no_matches: List[MatchResult] = []

        for idx, (viki_id, show_data) in enumerate(show_items, 1):
            if verbose:
                print(f"[{idx}/{len(show_items)}] {show_data.get('name', viki_id)}")

        for idx, (viki_id, show_data) in enumerate(show_items, 1):
            if verbose:
                show_title = show_data.get("titles", {}).get("en") or show_data.get("name")
                if not show_title:
                    show_title = show_data.get("title") or f"Unknown ({viki_id})"
                print(f"[{idx}/{len(show_items)}] {show_title}")

            try:
                # Build show dict for matcher
                show_title = show_data.get("titles", {}).get("en") or show_data.get("name")
                if not show_title:
                    # Try to extract from other fields
                    show_title = show_data.get("title") or f"Unknown ({viki_id})"

                viki_show = {
                    "id": viki_id,
                    "viki_id": viki_id,
                    "titles": {
                        "en": show_title,
                    },
                }

                # Get match
                result = self.matcher.match(viki_show)

                # Categorize
                if result.is_matched():
                    if result.match_confidence >= 0.95:
                        exact_matches.append(result)
                    else:
                        close_matches.append(result)
                else:
                    no_matches.append(result)

            except Exception as e:
                logger.error(f"Error matching {viki_id}: {e}")
                show_title = show_data.get("titles", {}).get("en") or show_data.get("name") or f"Unknown ({viki_id})"
                no_matches.append(
                    MatchResult(
                        viki_id=viki_id,
                        viki_title=show_title,
                        notes=f"Error: {str(e)}",
                    )
                )

        return exact_matches, close_matches, no_matches

    @staticmethod
    def format_match(result: MatchResult) -> str:
        """Format match result for display.

        Args:
            result: MatchResult to format

        Returns:
            Formatted string
        """
        if result.is_matched():
            return (
                f"{result.viki_title}\n"
                f"  → Trakt: {result.trakt_title} (ID: {result.trakt_id})\n"
                f"  Confidence: {result.match_confidence:.1%} [{result.match_method}]"
            )
        else:
            return f"{result.viki_title}\n  ✗ No match{' (Error: ' + result.notes + ')' if result.notes else ''}"

    def print_results(
        self,
        exact: List[MatchResult],
        close: List[MatchResult],
        no_match: List[MatchResult],
    ) -> None:
        """Print evaluation results in formatted table.

        Args:
            exact: Exact matches (confidence >= 0.95)
            close: Close matches (0.70-0.95)
            no_match: No matches (< 0.70 or unmatched)
        """
        total = len(exact) + len(close) + len(no_match)

        print("\n" + "=" * 80)
        print("MATCHING EVALUATION RESULTS")
        print("=" * 80)

        print(
            f"\nTotal Shows: {total} | "
            f"Exact: {len(exact)} ({len(exact)/total*100:.1f}%) | "
            f"Close: {len(close)} ({len(close)/total*100:.1f}%) | "
            f"No Match: {len(no_match)} ({len(no_match)/total*100:.1f}%)"
        )

        # Tier 1: Exact Matches
        print("\n" + "-" * 80)
        print(f"TIER 1: EXACT MATCHES ({len(exact)})")
        print("-" * 80)
        if exact:
            for i, result in enumerate(exact, 1):
                print(f"\n{i}. {self.format_match(result)}")
        else:
            print("(none)")

        # Tier 2: Close Matches
        print("\n" + "-" * 80)
        print(f"TIER 2: CLOSE MATCHES ({len(close)})")
        print("-" * 80)
        if close:
            for i, result in enumerate(close, 1):
                print(f"\n{i}. {self.format_match(result)}")
        else:
            print("(none)")

        # Tier 3: No Matches
        print("\n" + "-" * 80)
        print(f"TIER 3: NO MATCHES ({len(no_match)})")
        print("-" * 80)
        if no_match:
            for i, result in enumerate(no_match, 1):
                print(f"\n{i}. {self.format_match(result)}")
        else:
            print("(none)")

        print("\n" + "=" * 80)

    def get_summary(
        self, exact: List[MatchResult], close: List[MatchResult], no_match: List[MatchResult]
    ) -> Dict:
        """Get summary statistics.

        Args:
            exact: Exact matches
            close: Close matches
            no_match: No matches

        Returns:
            Dict with statistics
        """
        total = len(exact) + len(close) + len(no_match)

        return {
            "total": total,
            "exact": len(exact),
            "exact_pct": len(exact) / total * 100 if total > 0 else 0,
            "close": len(close),
            "close_pct": len(close) / total * 100 if total > 0 else 0,
            "unmatched": len(no_match),
            "unmatched_pct": len(no_match) / total * 100 if total > 0 else 0,
            "total_matched": len(exact) + len(close),
            "total_matched_pct": (len(exact) + len(close)) / total * 100 if total > 0 else 0,
        }


