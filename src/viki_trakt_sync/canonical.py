"""Canonical watch format for syncing between Viki and Trakt."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CanonicalizedWatch:
    """Canonical representation of a watch event.

    This format bridges Viki → Trakt with common structure.
    """

    # Show identifiers
    viki_id: str
    trakt_id: int
    trakt_slug: str

    # Show info
    show_title: str
    show_year: Optional[int] = None

    # Episode identifiers
    episode_number: int
    season_number: int = 1  # Viki doesn't use seasons, default to 1

    # Watch data
    watched_at: datetime = None
    watched_seconds: int = 0  # How many seconds of the episode watched
    total_seconds: int = 0  # Total episode duration
    is_watched: bool = False  # True if >= 90% watched or past credits

    # Progress (for Phase 2)
    progress_percent: float = 0.0  # 0-100
    credits_start_seconds: Optional[int] = None  # When credits start

    # Metadata
    match_confidence: float = 1.0  # 0-1, how confident is the match
    source: str = "viki"  # Source app (for debugging)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/transmission."""
        return {
            "viki_id": self.viki_id,
            "trakt_id": self.trakt_id,
            "trakt_slug": self.trakt_slug,
            "show_title": self.show_title,
            "show_year": self.show_year,
            "episode_number": self.episode_number,
            "season_number": self.season_number,
            "watched_at": self.watched_at.isoformat() if self.watched_at else None,
            "watched_seconds": self.watched_seconds,
            "total_seconds": self.total_seconds,
            "is_watched": self.is_watched,
            "progress_percent": self.progress_percent,
            "credits_start_seconds": self.credits_start_seconds,
            "match_confidence": self.match_confidence,
            "source": self.source,
        }

    @classmethod
    def from_viki(
        cls,
        viki_watch: dict,
        trakt_id: int,
        trakt_slug: str,
        match_confidence: float = 1.0,
    ) -> "CanonicalizedWatch":
        """Create canonical watch from Viki watch marker.

        Args:
            viki_watch: Watch marker from Viki (contains video, duration, etc.)
            trakt_id: Matched Trakt show ID
            trakt_slug: Matched Trakt show slug
            match_confidence: How confident is the match (0-1)

        Returns:
            CanonicalizedWatch
        """
        # Determine if watched (>= 90% or past credits)
        watch_marker = viki_watch.get("watch_marker", 0)
        duration = viki_watch.get("duration", 0)
        credits_marker = viki_watch.get("credits_marker", duration)

        is_watched = (
            watch_marker >= credits_marker or 
            (duration > 0 and watch_marker >= duration * 0.9)
        )

        progress_percent = (watch_marker / duration * 100) if duration > 0 else 0

        return cls(
            viki_id=viki_watch.get("container_id", ""),
            trakt_id=trakt_id,
            trakt_slug=trakt_slug,
            show_title=viki_watch.get("show_title", "Unknown"),
            show_year=viki_watch.get("show_year"),
            episode_number=viki_watch.get("episode", 1),
            season_number=1,  # Viki doesn't use seasons
            watched_at=datetime.fromisoformat(viki_watch["timestamp"])
            if "timestamp" in viki_watch
            else None,
            watched_seconds=watch_marker,
            total_seconds=duration,
            is_watched=is_watched,
            progress_percent=progress_percent,
            credits_start_seconds=credits_marker,
            match_confidence=match_confidence,
            source="viki",
        )
