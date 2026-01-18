"""Match Query - view and manage show matches.

Provides read operations for viewing match state
and helper functions for manual matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from ..repository import Repository
from ..models import Show, Match


@dataclass
class MatchInfo:
    """Information about a show's match status."""
    viki_id: str
    viki_title: str
    trakt_id: Optional[int]
    trakt_slug: Optional[str]
    trakt_title: Optional[str]
    match_source: Optional[str]  # AUTO, MANUAL, NONE
    match_confidence: Optional[float]
    match_method: Optional[str]
    
    @property
    def is_matched(self) -> bool:
        """Check if show has a valid match."""
        return self.trakt_id is not None and self.match_source != "NONE"


class MatchQuery:
    """Query for viewing match information."""
    
    def __init__(self, repository: Optional[Repository] = None):
        """Initialize query.
        
        Args:
            repository: Data repository (default: new instance)
        """
        self.repo = repository or Repository()
    
    def get_match(self, viki_id: str) -> Optional[MatchInfo]:
        """Get match info for a specific show.
        
        Args:
            viki_id: Viki container ID
            
        Returns:
            MatchInfo or None if show not found
        """
        show = self.repo.get_show(viki_id)
        if not show:
            return None
        
        return MatchInfo(
            viki_id=str(show.viki_id),
            viki_title=str(show.title) if show.title else "Unknown",
            trakt_id=int(show.trakt_id) if show.trakt_id else None,
            trakt_slug=str(show.trakt_slug) if show.trakt_slug else None,
            trakt_title=str(show.trakt_title) if show.trakt_title else None,
            match_source=str(show.match_source) if show.match_source else None,
            match_confidence=float(show.match_confidence) if show.match_confidence else None,
            match_method=str(show.match_method) if show.match_method else None,
        )
    
    def list_unmatched(self) -> List[MatchInfo]:
        """Get all shows without a Trakt match.
        
        Returns:
            List of unmatched shows
        """
        shows = self.repo.get_unmatched_shows()
        
        return [
            MatchInfo(
                viki_id=str(s.viki_id),
                viki_title=str(s.title) if s.title else "Unknown",
                trakt_id=None,
                trakt_slug=None,
                trakt_title=None,
                match_source=str(s.match_source) if s.match_source else None,
                match_confidence=None,
                match_method=None,
            )
            for s in shows
        ]
    
    def list_matched(self) -> List[MatchInfo]:
        """Get all shows with a Trakt match.
        
        Returns:
            List of matched shows
        """
        shows = self.repo.get_matched_shows()
        
        return [
            MatchInfo(
                viki_id=str(s.viki_id),
                viki_title=str(s.title) if s.title else "Unknown",
                trakt_id=int(s.trakt_id) if s.trakt_id else None,
                trakt_slug=str(s.trakt_slug) if s.trakt_slug else None,
                trakt_title=str(s.trakt_title) if s.trakt_title else None,
                match_source=str(s.match_source) if s.match_source else None,
                match_confidence=float(s.match_confidence) if s.match_confidence else None,
                match_method=str(s.match_method) if s.match_method else None,
            )
            for s in shows
        ]
    
    def set_manual_match(
        self,
        viki_id: str,
        trakt_id: int,
        trakt_slug: Optional[str] = None,
        trakt_title: Optional[str] = None,
    ) -> bool:
        """Set a manual match for a show.
        
        Args:
            viki_id: Viki container ID
            trakt_id: Trakt show ID
            trakt_slug: Trakt slug (optional)
            trakt_title: Trakt title (optional)
            
        Returns:
            True if successful
        """
        show = self.repo.get_show(viki_id)
        if not show:
            return False
        
        self.repo.save_match(
            viki_id=viki_id,
            trakt_id=trakt_id,
            trakt_slug=trakt_slug,
            trakt_title=trakt_title,
            source="MANUAL",
            confidence=1.0,
            method="manual",
            notes="Manually matched by user",
        )
        
        return True
    
    def clear_match(self, viki_id: str) -> bool:
        """Clear the match for a show.
        
        Args:
            viki_id: Viki container ID
            
        Returns:
            True if successful
        """
        show = self.repo.get_show(viki_id)
        if not show:
            return False
        
        self.repo.clear_match(viki_id)
        return True
