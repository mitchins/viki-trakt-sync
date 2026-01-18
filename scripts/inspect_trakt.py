#!/usr/bin/env python3
"""Inspect trakt module structure."""

import sys

print("=== trakt module ===")
import trakt
print(f"trakt.__file__: {trakt.__file__}")
print(f"dir(trakt): {[x for x in dir(trakt) if not x.startswith('_')]}")

# Check trakt.core
try:
    from trakt import core
    print("\n=== trakt.core ===")
    print(f"trakt.core.__file__: {core.__file__}")
    print(f"dir(trakt.core): {[x for x in dir(core) if not x.startswith('_')]}")
except ImportError as e:
    print(f"\n=== trakt.core FAILED ===\n{e}")

# Check what's available in trakt
print("\n=== Trying common imports ===")
try:
    from trakt import Trakt
    print("✓ from trakt import Trakt")
except ImportError as e:
    print(f"✗ from trakt import Trakt: {e}")

try:
    from trakt.core import api
    print("✓ from trakt.core import api")
except ImportError as e:
    print(f"✗ from trakt.core import api: {e}")

try:
    import trakt.tv
    print("✓ import trakt.tv")
except ImportError as e:
    print(f"✗ import trakt.tv: {e}")

try:
    import trakt.movies
    print("✓ import trakt.movies")
except ImportError as e:
    print(f"✗ import trakt.movies: {e}")

try:
    from trakt.tv import TVShow
    print("✓ from trakt.tv import TVShow")
except ImportError as e:
    print(f"✗ from trakt.tv import TVShow: {e}")

print("\n=== Checking 4.4.0 compatible APIs ===")
try:
    from trakt.movies import Movie
    from trakt.tv import TVShow
    print("✓ Found Movie and TVShow (trakt.py 4.4.0 API)")
except ImportError as e:
    print(f"✗ Movie/TVShow: {e}")

# List what's in trakt module root
print("\n=== Full dir(trakt) ===")
import trakt
for attr in sorted(dir(trakt)):
    if not attr.startswith('_'):
        obj = getattr(trakt, attr)
        print(f"  {attr}: {type(obj).__name__}")
