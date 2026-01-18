#!/usr/bin/env python3
import requests
import sys
from pathlib import Path

sys.path.insert(0, '/Users/mitchellcurrie/Projects/viki-trakt-sync/src')
from viki_trakt_sync.config import Config

config = Config(Path.home() / '.config' / 'viki-trakt-sync' / 'settings.toml')
client = config.get_viki_client()

# Use EXACT same approach as test.py
cookies = client.cookies_dict
headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en',
    'priority': 'u=1, i',
    'referer': 'https://www.viki.com/tv/41302c-idol-i',
    'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'x-viki-app-ver': '26.1.3-4.43.1',
    'x-viki-device-id': '276378550d',
}

params = {
    'from': '1768474054',
}

# Use plain requests, no session
response = requests.get('https://www.viki.com/api/vw_watch_markers', params=params, cookies=cookies, headers=headers)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    import json
    data = response.json()
    print(f"Got {data.get('count', 0)} markers")
    print(json.dumps(data, indent=2)[:500])
else:
    print(f"Error: {response.text[:300]}")
