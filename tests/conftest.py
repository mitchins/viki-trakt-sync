"""Shared test fixtures for dependency injection testing."""

import pytest
from viki_trakt_sync.config_provider import MockConfigProvider, TomlConfigProvider


@pytest.fixture
def mock_config_provider():
    """Provide a mock configuration provider for testing.
    
    Returns a MockConfigProvider with test Trakt credentials.
    """
    return MockConfigProvider(data={
        "trakt": {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        }
    })


@pytest.fixture
def real_config_provider():
    """Provide the real configuration provider (loads from settings.toml).
    
    Use when tests need to run against actual configuration.
    """
    return TomlConfigProvider()
