#!/usr/bin/env python3
"""Helper script to extract Viki session and token from browser."""

import sys

print("""
╔════════════════════════════════════════════════════════════════╗
║        Extract Viki Session Credentials from Browser          ║
╚════════════════════════════════════════════════════════════════╝

Since Viki requires reCAPTCHA, we need to extract credentials from
an active browser session.

📋 STEP-BY-STEP GUIDE:

1. Open Firefox or Chrome
   
2. Go to https://www.viki.com and LOGIN
   
3. Open DevTools:
   - Firefox: Right-click → Inspect (Q)
   - Chrome: Right-click → Inspect
   
4. Click the "Application" tab (Chrome) or "Storage" tab (Firefox)
   
5. In left sidebar: Cookies → https://www.viki.com
   
6. Find and copy these values:
   
   ┌─────────────────┬──────────────────────────────────────┐
   │ Cookie Name     │ Example Value                        │
   ├─────────────────┼──────────────────────────────────────┤
   │ session__id     │ 100000a-1768276288931-3cb7cc70...   │
   └─────────────────┴──────────────────────────────────────┘
   
7. Now click the "Network" tab in DevTools
   
8. Visit your "Continue Watching" page on Viki
   
9. Look for requests to "api.viki.io" in the Network tab
   
10. Click on any api.viki.io request
   
11. Look at the request URL - find the "token" parameter
    
    Example URL:
    https://api.viki.io/v4/users/47157398u/watchlist.json?token=ex1OTVGX...
                                                              ^^^^^^^^^^
    Copy everything after "token=" (starts with "ex1")
    
12. Update your .env file:
    
    VIKI_SESSION=<paste session__id value here>
    VIKI_TOKEN=<paste token value here>
    
13. Test it:
    
    python -m viki_trakt_sync.cli viki list -n 5

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 TIPS:

- Session expires after ~30 minutes of inactivity
- Token is tied to your session
- You'll need to re-extract if session expires
- Keep your browser tab open while testing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔒 SECURITY:

- Never commit .env file to git (already in .gitignore)
- These credentials grant full access to your Viki account
- Treat them like passwords

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ready? Press any key after you've updated .env...
""")

try:
    input()
except KeyboardInterrupt:
    print("\n\nCancelled.")
    sys.exit(0)

print("\n✓ Great! Now testing your credentials...\n")

# Try to load and validate
try:
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    session = os.getenv("VIKI_SESSION")
    token = os.getenv("VIKI_TOKEN")
    
    if not session or not token:
        print("❌ Error: VIKI_SESSION or VIKI_TOKEN not found in .env")
        print("\nMake sure your .env file contains:")
        print("VIKI_SESSION=<your session id>")
        print("VIKI_TOKEN=<your token>")
        sys.exit(1)
    
    print(f"✓ Found VIKI_SESSION: {session[:30]}...")
    print(f"✓ Found VIKI_TOKEN: {token[:30]}...")
    
    print("\n🚀 Running test command...\n")
    
    import subprocess
    result = subprocess.run(
        ["python", "-m", "viki_trakt_sync.cli", "viki", "list", "-n", "5"],
        capture_output=False
    )
    
    if result.returncode == 0:
        print("\n✅ SUCCESS! Your credentials are working.")
        print("\nYou can now use the CLI normally:")
        print("  python -m viki_trakt_sync.cli viki list")
        print("  python -m viki_trakt_sync.cli viki show 41302c")
    else:
        print("\n❌ Credentials invalid or expired.")
        print("Please extract fresh credentials from your browser.")
        sys.exit(1)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
