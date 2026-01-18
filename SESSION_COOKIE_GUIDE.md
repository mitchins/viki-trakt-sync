# Viki Session Cookies - Critical Setup Guide

## The Problem

Viki requires **TWO active session cookies** for the sync to work. These cookies expire **within minutes**, so you need to extract them fresh from your browser immediately before running the sync.

## Why Two Cookies?

The `vw_watch_markers` API endpoint (which provides complete watch history) requires:
- `session__id`: Identifies your session
- `_viki_session`: Authenticates your session

Without BOTH cookies, you get a 400 "User not signed in" error, and syncing fails completely.

## How to Extract Fresh Cookies

### Step 1: Open Viki in Your Browser
Go to https://www.viki.com and make sure you're **logged in**.

### Step 2: Open Developer Tools
Press **F12** (or right-click → Inspect → Application tab)

### Step 3: Navigate to Cookies
In DevTools:
- **Chrome**: Application → Cookies → https://www.viki.com
- **Firefox**: Storage → Cookies → https://www.viki.com

### Step 4: Find the Two Cookies
Look for these exact cookie names:
1. `session__id` - looks like: `100000a-1768380923637-2611fadb-52b2-4127-8672-73ffa543330a`
2. `_viki_session` - looks like: `Y2QycTNGbXVsdTByRjBU...` (very long base64 string)

### Step 5: Copy the Values
Click each cookie and copy its **Value** (not the name or other columns).

### Step 6: Update settings.toml
Edit `~/.config/viki-trakt-sync/settings.toml` and update:

```toml
[viki]
token = "your_token_here"
user_id = "your_user_id"
session_id = "100000a-1768380923637-2611fadb-52b2-4127-8672-73ffa543330a"
viki_session = "Y2QycTNGbXVzdTByRjBUTHdBOE..."
```

### Step 7: Run Sync IMMEDIATELY
Run the sync right after updating the config:

```bash
python -m viki_trakt_sync sync
```

**DO NOT DELAY** - sessions expire within minutes!

## Why Sessions Expire So Quickly

Viki sessions are designed to be short-lived for security. The expiration time is not encoded in the cookie itself, so you can't validate offline—you have to attempt the API call to know if it's expired.

## Tips for Success

1. **Keep browser open** - Leaving your Viki tab open may help extend session validity
2. **Don't delay** - Extract and run immediately, within 1-2 minutes
3. **Use same network** - Extract and run from the same internet connection
4. **Check error messages** - If you get "User not signed in", the session already expired - extract fresh ones and try again immediately

## What If Sync Is Slow?

If the sync takes more than a few minutes, the session may expire while syncing. Keep your browser tab open to help maintain the session.

## Testing the Cookies

You can test if your cookies work with curl:

```bash
curl https://www.viki.com/api/vw_watch_markers \
  -b 'session__id=YOUR_SESSION_ID' \
  -b '_viki_session=YOUR_VIKI_SESSION' \
  -H 'accept: application/json'
```

If it returns JSON data (not 400 error), your cookies are valid!
