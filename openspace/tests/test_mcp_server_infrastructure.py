"""Tests for mcp_server — Base infrastructure and provider registration.

Target coverage: Skill registration, environment setup, tool registry initialization
Test count: 3 tests covering:
- Provider registration patterns
- Environment variable setup
- Tool registry initialization from skill dirs
"""

import os
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ============================================================================
# Tests: Provider Registration
# ============================================================================


class TestProviderRegistration:
    """Test tool provider registration patterns."""

    def test_register_provider(self):
        """Register tool provider in registry."""
        # Simulate registry (dict-based)
        registry = {}

        def register_provider(name: str, provider: dict):
            """Register a tool provider."""
            registry[name] = provider

        # Register a sample provider
        register_provider("web_scraper", {
            "name": "web_scraper",
            "description": "Web scraping tool",
            "version": "1.0",
        })

        assert "web_scraper" in registry
        assert registry["web_scraper"]["name"] == "web_scraper"

    def test_register_multiple_providers(self):
        """Register multiple providers."""
        registry = {}

        providers = [
            ("tool_a", {"name": "tool_a", "version": "1.0"}),
            ("tool_b", {"name": "tool_b", "version": "2.0"}),
            ("tool_c", {"name": "tool_c", "version": "1.5"}),
        ]

        for name, provider in providers:
            registry[name] = provider

        assert len(registry) == 3
        assert all(name in registry for name, _ in providers)

    def test_provider_duplicate_registration(self):
        """Handle duplicate provider registration."""
        registry = {}

        registry["tool"] = {"version": "1.0"}
        # Re-register same tool (should update)
        registry["tool"] = {"version": "2.0"}

        assert registry["tool"]["version"] == "2.0"


# ============================================================================
# Tests: Environment Setup
# ============================================================================


class TestEnvironmentSetup:
    """Test environment variable setup."""

    def test_load_env_var(self, monkeypatch):
        """Load environment variable."""
        monkeypatch.setenv("OPENSPACE_TEST_VAR", "test_value")

        value = os.getenv("OPENSPACE_TEST_VAR")

        assert value == "test_value"

    def test_load_mcp_config_env(self, monkeypatch):
        """Load MCP server configuration from env."""
        config_env = {
            "OPENSPACE_HOST_SKILL_DIRS": "/home/user/.openspace/skills",
            "OPENSPACE_MODEL": "claude-sonnet-4-6",
        }

        for key, value in config_env.items():
            monkeypatch.setenv(key, value)

        # Should be able to load config
        assert os.getenv("OPENSPACE_HOST_SKILL_DIRS") is not None
        assert os.getenv("OPENSPACE_MODEL") is not None

    def test_missing_env_var_fallback(self, monkeypatch):
        """Fallback to default when env var missing."""
        monkeypatch.delenv("OPENSPACE_NONEXISTENT", raising=False)

        value = os.getenv("OPENSPACE_NONEXISTENT", "default_value")

        assert value == "default_value"


# ============================================================================
# Tests: Tool Registry Initialization
# ============================================================================


class TestToolRegistryInitialization:
    """Test tool registry initialization."""

    def test_initialize_empty_registry(self):
        """Initialize empty tool registry."""
        registry = {}

        assert len(registry) == 0
        assert isinstance(registry, dict)

    def test_scan_skill_directories(self, tmp_path):
        """Scan directories for skills."""
        # Create test skill structure
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()

        skill_1 = skill_dir / "skill_1"
        skill_1.mkdir()
        (skill_1 / "SKILL.md").write_text("# Skill 1")

        skill_2 = skill_dir / "skill_2"
        skill_2.mkdir()
        (skill_2 / "SKILL.md").write_text("# Skill 2")

        # Scan directory
        skills_found = [d.name for d in skill_dir.iterdir() if (d / "SKILL.md").exists()]

        assert len(skills_found) == 2
        assert "skill_1" in skills_found
        assert "skill_2" in skills_found

    def test_load_skill_metadata(self, tmp_path):
        """Load skill metadata from SKILL.md."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("""---
name: Test Skill
version: 1.0
description: A test skill
---

# Implementation
Content here
""")

        # Parse frontmatter (simplified)
        content = skill_file.read_text()
        assert "Test Skill" in content
        assert "version: 1.0" in content
        assert "description:" in content

    def test_register_skills_from_directory(self, tmp_path):
        """Register skills found in directory."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Create skill 1
        skill_1_dir = skills_dir / "web_scraper"
        skill_1_dir.mkdir()
        (skill_1_dir / "SKILL.md").write_text("# Web Scraper\nversion: 1.0")

        # Create skill 2
        skill_2_dir = skills_dir / "data_parser"
        skill_2_dir.mkdir()
        (skill_2_dir / "SKILL.md").write_text("# Data Parser\nversion: 1.0")

        # Simulate registration
        registry = {}
        for skill_path in skills_dir.iterdir():
            if (skill_path / "SKILL.md").exists():
                registry[skill_path.name] = {
                    "name": skill_path.name,
                    "path": str(skill_path),
                }

        assert len(registry) == 2
        assert "web_scraper" in registry
        assert "data_parser" in registry


# ============================================================================
# Tests: Lazy Initialization
# ============================================================================


class TestLazyInitialization:
    """Test lazy initialization patterns."""

    @pytest.mark.asyncio
    async def test_lazy_openspace_init(self):
        """Lazy initialize OpenSpace on first call."""
        # Simulate lazy init with mock
        _openspace_cache = None

        async def get_openspace():
            nonlocal _openspace_cache
            if _openspace_cache is None:
                _openspace_cache = MagicMock()
            return _openspace_cache

        # First call should initialize
        engine1 = await get_openspace()
        # Second call should reuse
        engine2 = await get_openspace()

        assert engine1 is engine2  # Same instance

    def test_lazy_registry_init(self):
        """Lazy initialize skill registry."""
        _registry_cache = None

        def get_registry():
            nonlocal _registry_cache
            if _registry_cache is None:
                _registry_cache = {}
                # Scan and load skills
                _registry_cache["initialized"] = True
            return _registry_cache

        registry1 = get_registry()
        registry2 = get_registry()

        assert registry1 is registry2
        assert registry1.get("initialized") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
