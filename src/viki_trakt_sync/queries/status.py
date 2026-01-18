"""Status Query - system health and sync status.

Provides an overview of the sync system state including
statistics, last sync info, and any issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from ..repository import Repository


@dataclass
class SyncStats:
    """Statistics about the sync system."""
    total_shows: int
    matched_shows: int
    unmatched_shows: int
    total_episodes: int
    watched_episodes: int
    synced_episodes: int
    pending_sync: int
    last_sync: Optional[datetime]
    last_sync_status: Optional[str]
    
    @property
    def match_rate(self) -> float:
        """Percentage of shows matched."""
        if self.total_shows == 0:
            return 0.0
        return (self.matched_shows / self.total_shows) * 100
    
    @property
    def sync_rate(self) -> float:
        """Percentage of watched episodes synced."""
        if self.watched_episodes == 0:
            return 0.0
        return (self.synced_episodes / self.watched_episodes) * 100


@dataclass
class SyncIssue:
    """A potential issue with the sync system."""
    severity: str  # "warning", "error"
    message: str
    context: Optional[str] = None


class StatusQuery:
    """Query for system status and health."""
    
    def __init__(self, repository: Optional[Repository] = None):
        """Initialize query.
        
        Args:
            repository: Data repository (default: new instance)
        """
        self.repo = repository or Repository()
    
    def get_stats(self) -> SyncStats:
        """Get sync system statistics.
        
        Returns:
            SyncStats with all metrics
        """
        stats = self.repo.get_stats()
        
        return SyncStats(
            total_shows=stats.get('total_shows', 0),
            matched_shows=stats.get('matched_shows', 0),
            unmatched_shows=stats.get('unmatched_shows', 0),
            total_episodes=stats.get('total_episodes', 0),
            watched_episodes=stats.get('watched_episodes', 0),
            synced_episodes=stats.get('synced_episodes', 0),
            pending_sync=stats.get('pending_sync', 0),
            last_sync=stats.get('last_sync'),
            last_sync_status=stats.get('last_sync_status'),
        )
    
    def get_issues(self) -> List[SyncIssue]:
        """Check for potential issues with the sync system.
        
        Returns:
            List of identified issues
        """
        issues = []
        stats = self.get_stats()
        
        # Check for unmatched shows
        if stats.unmatched_shows > 0:
            issues.append(SyncIssue(
                severity="warning",
                message=f"{stats.unmatched_shows} show(s) not matched to Trakt",
                context="Run 'match list' to see unmatched shows",
            ))
        
        # Check for pending sync
        if stats.pending_sync > 0:
            issues.append(SyncIssue(
                severity="warning",
                message=f"{stats.pending_sync} episode(s) watched but not synced",
                context="Run 'sync' to sync to Trakt",
            ))
        
        # Check last sync status
        if stats.last_sync_status and stats.last_sync_status != "success":
            issues.append(SyncIssue(
                severity="error",
                message=f"Last sync status: {stats.last_sync_status}",
                context="Check logs for details",
            ))
        
        # Check if never synced
        if stats.last_sync is None and stats.total_shows > 0:
            issues.append(SyncIssue(
                severity="warning",
                message="No sync has been run yet",
                context="Run 'sync' to start syncing",
            ))
        
        return issues
    
    def health_check(self) -> Dict:
        """Perform a health check.
        
        Returns:
            Dict with overall health status
        """
        stats = self.get_stats()
        issues = self.get_issues()
        
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        
        if errors:
            status = "unhealthy"
        elif warnings:
            status = "degraded"
        else:
            status = "healthy"
        
        return {
            "status": status,
            "stats": stats,
            "issues": issues,
            "errors": len(errors),
            "warnings": len(warnings),
        }
