#!/usr/bin/env python3
import requests
import sys
from pathlib import Path

sys.path.insert(0, '/Users/mitchellcurrie/Projects/viki-trakt-sync/src')
from viki_trakt_sync.config import Config

config = Config(Path.home() / '.config' / 'viki-trakt-sync' / 'settings.toml')
client = config.get_viki_client()

print("=== Using session from VikiClient ===")
print(f"Session cookies dict: {dict(client.session.cookies)}")
print()

# Try the request
resp1 = client.session.get("https://www.viki.com/api/vw_watch_markers?from=1768474054")
print(f"VikiClient session result: {resp1.status_code}")
print()

print("=== Using plain requests with same cookies ===")
# Now try the same thing but with a fresh session + the same cookies
fresh_session = requests.Session()
fresh_session.cookies.update(dict(client.session.cookies))
fresh_session.headers.update(client.session.headers)

print(f"Fresh session cookies dict: {dict(fresh_session.cookies)}")
print()

resp2 = fresh_session.get("https://www.viki.com/api/vw_watch_markers?from=1768474054")
print(f"Fresh session result: {resp2.status_code}")
