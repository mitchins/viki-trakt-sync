"""Configuration management for Viki-Trakt Sync.

Loads configuration from TOML file in standard locations:
1. /config/settings.toml (Docker/container)
2. ~/.config/viki-trakt-sync/settings.toml (user home)
3. $XDG_CONFIG_HOME/viki-trakt-sync/settings.toml (XDG standard)
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from .viki_client import VikiClient
from .trakt_client import TraktClient

logger = logging.getLogger(__name__)


class Config:
    """Configuration loader and validator."""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize config from file.

        Args:
            config_path: Optional explicit path to settings.toml
        """
        self.config_path = config_path or self._find_config_file()
        self.data: Dict[str, Any] = {}

        if self.config_path and self.config_path.exists():
            self._load_from_file(self.config_path)
        else:
            error_msg = (
                "\n" + "="*70 + "\n"
                "ERROR: Config file not found!\n"
                "\n"
                "Expected settings.toml at one of these locations:\n"
                "  1. ~/.config/viki-trakt-sync/settings.toml (user config)\n"
                "  2. /config/settings.toml (Docker)\n"
                "  3. $XDG_CONFIG_HOME/viki-trakt-sync/settings.toml (XDG)\n"
                "\n"
                "If migrating from .env:\n"
                "  1. Copy settings.toml.example to ~/.config/viki-trakt-sync/settings.toml\n"
                "  2. Add your credentials from .env to the [viki] and [trakt] sections\n"
                "  3. Run again\n"
                "\n"
                "See settings.toml.example for format.\n"
                "="*70 + "\n"
            )
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

    @staticmethod
    def _find_config_file() -> Optional[Path]:
        """Find config file in standard locations.

        Returns:
            Path to config file, or None if not found
        """
        # 1. Docker/container path
        docker_path = Path("/config/settings.toml")
        if docker_path.exists():
            logger.info(f"Using Docker config: {docker_path}")
            return docker_path

        # 2. User home
        home_path = Path.home() / ".config" / "viki-trakt-sync" / "settings.toml"
        if home_path.exists():
            logger.info(f"Using user config: {home_path}")
            return home_path

        # 3. XDG_CONFIG_HOME
        xdg_config = os.getenv("XDG_CONFIG_HOME")
        if xdg_config:
            xdg_path = Path(xdg_config) / "viki-trakt-sync" / "settings.toml"
            if xdg_path.exists():
                logger.info(f"Using XDG config: {xdg_path}")
                return xdg_path

        return None

    def _load_from_file(self, path: Path) -> None:
        """Load config from TOML file.

        Args:
            path: Path to settings.toml
        """
        try:
            with open(path, "rb") as f:
                self.data = tomllib.load(f)
            logger.info(f"Loaded config from {path}")
        except Exception as e:
            logger.error(f"Failed to load config from {path}: {e}")
            raise

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get config value.

        Args:
            section: Section name (e.g., 'viki', 'trakt')
            key: Key name
            default: Default value if not found

        Returns:
            Config value or default
        """
        return self.data.get(section, {}).get(key, default)

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire config section.

        Args:
            section: Section name

        Returns:
            Section dict or empty dict
        """
        return self.data.get(section, {})

    def validate(self) -> tuple[bool, list[str]]:
        """Validate required config values.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        # Check Viki section
        viki = self.get_section("viki")
        if not viki.get("token"):
            errors.append("Missing [viki] token")
        if not viki.get("user_id"):
            errors.append("Missing [viki] user_id")
        if not viki.get("cookies_raw"):
            errors.append(
                "Missing [viki] cookies_raw (REQUIRED for complete watch history!)\n"
                "            Copy full cookie string from curl -b flag"
            )

        # Check Trakt section (optional for some operations)
        trakt = self.get_section("trakt")
        if not trakt.get("client_id"):
            logger.warning("Missing [trakt] client_id (required for matching)")
        if not trakt.get("client_secret"):
            logger.warning("Missing [trakt] client_secret (required for matching)")

        return len(errors) == 0, errors

    def get_viki_client(self) -> VikiClient:
        """Create and return authenticated VikiClient.

        Returns:
            Initialized VikiClient

        Raises:
            ValueError: If required credentials missing (including session!)
        """
        viki = self.get_section("viki")

        token = viki.get("token")
        user_id = viki.get("user_id")
        
        # Support two formats:
        # 1. cookies = { ... }  (TOML table/dict - preferred, matches test.py exactly)
        # 2. cookies_raw = "..." (semicolon-separated string from curl -b)
        cookies_dict = viki.get("cookies")  # Direct dict from TOML table
        cookies_raw = viki.get("cookies_raw")  # String to parse

        if not token:
            raise ValueError("Missing [viki] token in config")
        if not user_id:
            raise ValueError("Missing [viki] user_id in config")
        
        # Use cookies dict if provided, otherwise parse from string
        if cookies_dict and isinstance(cookies_dict, dict):
            logger.info(f"Using cookies dict with {len(cookies_dict)} cookies")
        elif cookies_raw:
            # Parse cookie string into dict
            cookies_dict = {}
            for part in cookies_raw.split("; "):
                if "=" in part:
                    key, value = part.split("=", 1)
                    cookies_dict[key] = value
            logger.info(f"Parsed {len(cookies_dict)} cookies from cookies_raw")
        else:
            error_msg = (
                "\n" + "="*70 + "\n"
                "ERROR: Missing [viki] cookies in config!\n"
                "\n"
                "Cookies are REQUIRED for accessing watch history.\n"
                "\n"
                "Config file: " + str(self.config_path) + "\n"
                "\n"
                "OPTION 1 - Use a TOML table (recommended):\n"
                "  [viki.cookies]\n"
                "  uuid = \"...\"\n"
                "  session__id = \"...\"\n"
                "  _viki_session = \"...\"\n"
                "  # etc\n"
                "\n"
                "OPTION 2 - Use raw string:\n"
                "  cookies_raw = \"uuid=...; session__id=...; ...\"\n"
                "\n"
                "TIP: Use curlconverter.com to convert curl command to Python,\n"
                "     then copy the cookies dict to your config.\n"
                "\n"
                "⚠️  Cookies expire quickly! Extract and run immediately.\n"
                "="*70 + "\n"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        return VikiClient(
            cookies=cookies_dict,
            token=token,
            user_id=user_id
        )

    def get_trakt_client(self) -> Optional[TraktClient]:
        """Create and return authenticated TraktClient.

        Returns:
            Initialized TraktClient or None if not configured

        Raises:
            ValueError: If credentials incomplete
        """
        trakt = self.get_section("trakt")

        client_id = trakt.get("client_id")
        client_secret = trakt.get("client_secret")

        if not client_id or not client_secret:
            logger.warning("Trakt not configured, some features unavailable")
            return None

        return TraktClient(client_id=client_id, client_secret=client_secret)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create global config instance.

    Returns:
        Config instance
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Reset global config instance (for testing)."""
    global _config
    _config = None
