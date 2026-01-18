"""Adapters package - thin wrappers around external services.

Implements the Adapter pattern to provide a clean, consistent interface
for interacting with external APIs (Viki, Trakt, metadata providers).
"""

from .viki import VikiAdapter
from .trakt import TraktAdapter
from .metadata import MetadataAdapter

__all__ = ['VikiAdapter', 'TraktAdapter', 'MetadataAdapter']
