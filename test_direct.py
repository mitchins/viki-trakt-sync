#!/usr/bin/env python3
import requests
from pathlib import Path
import sys

# Load config
sys.path.insert(0, '/Users/mitchellcurrie/Projects/viki-trakt-sync/src')
from viki_trakt_sync.config import Config

config = Config(Path.home() / '.config' / 'viki-trakt-sync' / 'settings.toml')
client = config.get_viki_client()

print(f"Cookies loaded: {len(client.session.cookies)}")
print(f"Headers: {dict(client.session.headers)}")
print()

# Test the request
url = "https://www.viki.com/api/vw_watch_markers"
params = {"from": 1}

response = client.session.get(url, params=params)
print(f"Status: {response.status_code}")
print(f"Response: {response.text[:500]}")
print()
print(f"Response headers: {dict(response.headers)}")
