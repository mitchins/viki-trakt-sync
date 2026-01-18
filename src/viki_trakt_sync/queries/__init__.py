"""Queries package - read-only operations for viewing state.

Provides query objects for reading local data without
modifying state. Used by CLI for 'watch' and 'status' commands.
"""

from .watch import WatchQuery
from .status import StatusQuery
from .match import MatchQuery

__all__ = ['WatchQuery', 'StatusQuery', 'MatchQuery']
