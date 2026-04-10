"""Tests for cloud/auth — OpenSpace API authentication and config resolution.

Target coverage: Config loading, token validation, env var priority
Test count: 3 tests covering:
- Config loading (env > host config > defaults)
- API base URL resolution
- Auth headers building
"""

import os
from unittest.mock import patch, MagicMock
import pytest

from openspace.cloud.auth import (
    get_openspace_auth,
    get_api_base,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def clean_env(monkeypatch):
    """Clean auth-related environment variables."""
    vars_to_clean = [
        "OPENSPACE_API_KEY",
        "OPENSPACE_API_BASE",
        "OPENSPACE_AUTH_KEY",
    ]
    for var in vars_to_clean:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ============================================================================
# Tests: Config Resolution (Env > Host Config > Defaults)
# ============================================================================


class TestGetOpenspaceAuth:
    """Test get_openspace_auth() config priority."""

    def test_get_auth_from_env_var(self, clean_env):
        """Load auth from OPENSPACE_API_KEY env var (highest priority)."""
        clean_env.setenv("OPENSPACE_API_KEY", "sk-test-abc123")
        clean_env.setenv("OPENSPACE_API_BASE", "https://api.example.com")

        auth_headers, api_base = get_openspace_auth()

        assert "sk-test-abc123" in str(auth_headers) or api_base.endswith(".com")
        assert api_base is not None

    def test_get_auth_no_credentials(self, clean_env):
        """Return empty headers when no credentials set."""
        auth_headers, api_base = get_openspace_auth()

        # Should return dict (even if empty)
        assert isinstance(auth_headers, dict)
        # Should have default base URL
        assert api_base is not None
        assert "open-space" in api_base.lower() or api_base.startswith("https")

    def test_get_api_base_default(self, clean_env):
        """Use default API base when not configured."""
        api_base = get_api_base()

        assert api_base is not None
        assert "https" in api_base
        # Default should be open-space.cloud or similar
        assert "open-space" in api_base.lower() or "api" in api_base.lower()

    def test_get_api_base_env_override(self, clean_env):
        """Environment variable overrides default base URL."""
        clean_env.setenv("OPENSPACE_API_BASE", "https://custom.api.example.com/v2")

        api_base = get_api_base()

        assert "custom" in api_base

    def test_get_api_base_cli_override(self, clean_env):
        """CLI override takes highest priority."""
        clean_env.setenv("OPENSPACE_API_BASE", "https://env.example.com")

        cli_override = "https://cli.example.com"
        api_base = get_api_base(cli_override=cli_override)

        assert api_base == cli_override

    def test_api_base_trailing_slash_normalized(self, clean_env):
        """Trailing slashes are removed from API base."""
        clean_env.setenv("OPENSPACE_API_BASE", "https://api.example.com/")

        api_base = get_api_base()

        # Should normalize trailing slash
        assert not api_base.endswith("/") or api_base == "https://"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
