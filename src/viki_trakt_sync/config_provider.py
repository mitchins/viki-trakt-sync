"""Configuration provider abstraction for dependency injection.

Provides a clean interface for accessing configuration that can be
injected, mocked in tests, and implemented differently (file, env, etc).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pathlib import Path


class ConfigProvider(ABC):
    """Abstract base for configuration providers.
    
    Allows configuration to be injected as a dependency,
    making code testable without file system dependencies.
    """
    
    @abstractmethod
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        
        Args:
            section: Config section (e.g., 'viki', 'trakt')
            key: Key within section
            default: Default value if not found
        
        Returns:
            Configuration value or default
        """
        pass
    
    @abstractmethod
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section.
        
        Args:
            section: Section name
        
        Returns:
            Section dict or empty dict
        """
        pass


class TomlConfigProvider(ConfigProvider):
    """Configuration provider that loads from settings.toml file.
    
    Searches standard locations:
    1. ~/.config/viki-trakt-sync/settings.toml (user home)
    2. /config/settings.toml (Docker)
    3. $XDG_CONFIG_HOME/viki-trakt-sync/settings.toml (XDG)
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize from TOML file.
        
        Args:
            config_path: Optional explicit path to settings.toml
        """
        from .config import Config
        
        self.config = Config(config_path=config_path)
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get configuration value from TOML."""
        return self.config.get(section, key, default)
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire section from TOML."""
        return self.config.get_section(section)


class MockConfigProvider(ConfigProvider):
    """Mock configuration provider for testing.
    
    Allows tests to provide configuration without file system dependencies.
    """
    
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        """Initialize with test data.
        
        Args:
            data: Dictionary of {section: {key: value}}
        """
        self.data = data or {}
    
    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get value from mock data."""
        return self.data.get(section, {}).get(key, default)
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get section from mock data."""
        return self.data.get(section, {})


def get_default_config_provider() -> ConfigProvider:
    """Get default configuration provider (loads from settings.toml).
    
    Returns:
        TomlConfigProvider instance with settings.toml
    """
    return TomlConfigProvider()
