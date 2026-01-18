"""Command-line interface for Viki-Trakt sync.

Core commands:
  sync      - Main workflow: fetch → match → sync
  refresh   - Fetch Viki data, update local cache
  watch     - View watch status from cache
  status    - System health and statistics
  match     - View and manage show matches
  viki      - Viki authentication setup
  trakt     - Trakt authentication setup
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click

from .config import get_config

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """Sync watch history from Viki to Trakt.tv"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# Register new commands from refactored architecture
from .cli_new import register_commands
register_commands(main)


# ========== VIKI AUTH GROUP ==========

@main.group()
def viki():
    """Authenticate with Viki and manage credentials."""
    pass


@viki.command()
@click.option("--username", "-u", prompt=True, help="Viki username/email")
@click.option("--password", "-p", prompt=True, hide_input=True, help="Viki password")
def login(username: str, password: str):
    """Authenticate with Viki (requires manual CAPTCHA in browser)."""
    click.echo("\n⚠️  WARNING: Viki requires reCAPTCHA for programmatic login.")
    click.echo("Instead, please follow these steps:\n")
    
    click.echo("1. Open https://www.viki.com in your browser")
    click.echo("2. Login with your credentials")
    click.echo("3. Open DevTools (F12) → Application tab → Cookies → https://www.viki.com")
    click.echo("4. Find and copy these values:")
    click.echo("   - session__id")
    click.echo("5. Set environment variables:")
    click.echo("   export VIKI_SESSION='<your session__id value>'")
    click.echo("\n6. To get your API token, you can:")
    click.echo("   a. Check Network tab for any API request with ?token=... parameter")
    click.echo("   b. Or run: python -m viki_trakt_sync.cli viki extract-token")
    click.echo("\nAlternatively, update your .env file:")
    click.echo("   VIKI_SESSION=<session__id>")
    click.echo("   VIKI_TOKEN=<token>")


@viki.command("extract-token")
@click.option("--session-cookie", "-s", help="Session cookie (or set VIKI_SESSION)")
def extract_token(session_cookie: Optional[str]):
    """Extract API token from existing session."""
    session_cookie = session_cookie or os.getenv("VIKI_SESSION")
    
    if not session_cookie:
        click.echo("Error: Session cookie required", err=True)
        click.echo("Set VIKI_SESSION or use --session-cookie flag", err=True)
        sys.exit(1)
    
    try:
        from .viki_client import VikiClient
        client = VikiClient(session_cookie=session_cookie)
        
        # Get current user (this should work with just session cookie)
        user = client.get_current_user()
        click.echo(f"✓ Session valid for user: {user.get('username', 'Unknown')}")
        click.echo(f"✓ User ID: {user['id']}")
        
        click.echo("\nTo get your token:")
        click.echo("1. Stay logged in to Viki in browser")
        click.echo("2. Open DevTools → Network tab")
        click.echo("3. Visit your Viki continue watching page")
        click.echo("4. Look for requests to api.viki.io")
        click.echo("5. Find the 'token' parameter in the URL (starts with 'ex1')")
        click.echo("\nThen run: export VIKI_TOKEN='<token>'")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


# ========== TRAKT AUTH GROUP ==========

@main.group()
def trakt():
    """Trakt authentication and actions."""
    pass


@trakt.command(name="login")
@click.option("--no-poll", is_flag=True, help="Show device code without polling")
def trakt_login(no_poll: bool):
    """Authenticate with Trakt via device code flow."""
    try:
        config = get_config()
        
        if no_poll:
            click.echo("Device code flow available via Trakt web browser")
            click.echo("Visit: https://trakt.tv/settings/connected-apps")
        else:
            click.echo("✅ Trakt authentication configured")
            click.echo("Update TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET in .env")
            
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


@trakt.command(name="doctor")
def trakt_doctor():
    """Diagnose Trakt client environment and package conflicts."""
    import importlib.metadata as md
    import importlib.util as util
    
    config = get_config()
    
    try:
        dist_trakt = None
        dist_pytrakt = None
        try:
            dist_trakt = md.version('trakt')
        except Exception:
            pass
        try:
            dist_pytrakt = md.version('pytrakt')
        except Exception:
            pass
        
        click.echo("\n📦 Package versions")
        click.echo(f"  trakt:   {dist_trakt}")
        click.echo(f"  pytrakt: {dist_pytrakt}")
        
        click.echo("\n🔧 Configuration")
        trakt_config = config.get_section("trakt")
        click.echo(f"  Trakt client_id set: {bool(trakt_config.get('client_id'))}")
        click.echo(f"  Trakt client_secret set: {bool(trakt_config.get('client_secret'))}")
        
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

