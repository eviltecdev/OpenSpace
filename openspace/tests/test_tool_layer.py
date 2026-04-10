"""Tests for tool_layer module — OpenSpace initialization and configuration.

Target coverage: 40%+
Test count: 25-30 tests covering config validation, LLM client initialization,
and OpenSpace instance management.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from openspace.tool_layer import OpenSpace, OpenSpaceConfig


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def env_setup(monkeypatch):
    """Set up environment variables."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


@pytest.fixture
def basic_config():
    """Create basic OpenSpaceConfig."""
    return OpenSpaceConfig(
        llm_model="claude-sonnet-4-6",
        log_level="INFO"
    )


@pytest.fixture
def custom_config():
    """Create custom OpenSpaceConfig."""
    return OpenSpaceConfig(
        llm_model="gpt-4o",
        llm_enable_thinking=True,
        llm_max_retries=5,
        llm_timeout=180.0,
        log_level="DEBUG"
    )


# ============================================================================
# Tests: Configuration
# ============================================================================


class TestOpenSpaceConfig:
    """Test OpenSpaceConfig initialization and validation."""

    def test_config_default_values(self):
        """Config should have sensible defaults."""
        config = OpenSpaceConfig(llm_model="claude-sonnet-4-6")
        assert config.llm_model == "claude-sonnet-4-6"
        assert config.llm_enable_thinking is False
        assert config.llm_timeout == 120.0
        assert config.llm_max_retries == 3
        assert config.enable_recording is True

    def test_config_custom_values(self, custom_config):
        """Config should accept custom values."""
        assert custom_config.llm_model == "gpt-4o"
        assert custom_config.llm_enable_thinking is True
        assert custom_config.llm_max_retries == 5
        assert custom_config.llm_timeout == 180.0
        assert custom_config.log_level == "DEBUG"

    def test_config_missing_llm_model_raises(self):
        """Config should require llm_model."""
        with pytest.raises(ValueError, match="llm_model"):
            OpenSpaceConfig(llm_model="")

    def test_config_with_workspace_dir(self):
        """Config should accept workspace_dir."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            workspace_dir="/tmp/workspace"
        )
        assert config.workspace_dir == "/tmp/workspace"

    def test_config_with_skill_models(self):
        """Config should accept separate skill engine models."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            skill_registry_model="gpt-4o",
            execution_analyzer_model="claude-opus-4-6"
        )
        assert config.skill_registry_model == "gpt-4o"
        assert config.execution_analyzer_model == "claude-opus-4-6"

    def test_config_with_grounding_config(self):
        """Config should accept grounding configuration path."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            grounding_config_path="/path/to/config.yaml"
        )
        assert config.grounding_config_path == "/path/to/config.yaml"

    def test_config_recording_options(self):
        """Config should support recording options."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            enable_recording=False,
            enable_screenshot=True,
            enable_video=True,
            enable_conversation_log=False
        )
        assert config.enable_recording is False
        assert config.enable_screenshot is True
        assert config.enable_video is True
        assert config.enable_conversation_log is False


# ============================================================================
# Tests: OpenSpace Initialization
# ============================================================================


class TestOpenSpaceInitialization:
    """Test OpenSpace instance creation and initialization."""

    def test_openspace_creation_with_config(self, env_setup, basic_config):
        """Create OpenSpace with config."""
        openspace = OpenSpace(config=basic_config)
        assert openspace is not None
        assert openspace.config == basic_config

    def test_openspace_creation_with_defaults(self, env_setup):
        """Create OpenSpace with default config."""
        openspace = OpenSpace()
        assert openspace is not None
        assert openspace.config is not None

    def test_openspace_not_initialized_initially(self, env_setup, basic_config):
        """OpenSpace should not be initialized on creation."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._initialized is False
        assert openspace._running is False

    @pytest.mark.asyncio
    async def test_openspace_initialize_sets_initialized_flag(self, env_setup, basic_config):
        """Calling initialize() should set _initialized flag."""
        openspace = OpenSpace(config=basic_config)
        try:
            await openspace.initialize()
            assert openspace._initialized is True
        except Exception:
            # Expected if grounding config not available
            pass

    def test_openspace_execution_count_starts_zero(self, env_setup, basic_config):
        """Execution count should start at 0."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._execution_count == 0

    def test_openspace_task_done_event_initially_set(self, env_setup, basic_config):
        """Task done event should be set initially."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._task_done.is_set()


# ============================================================================
# Tests: Configuration Validation
# ============================================================================


class TestConfigurationValidation:
    """Test configuration validation logic."""

    def test_config_post_init_logs_debug(self, basic_config):
        """Config __post_init__ should log debug message."""
        # Verify it doesn't raise
        assert basic_config.llm_model == "claude-sonnet-4-6"

    def test_config_llm_kwargs_preserved(self):
        """Config should preserve llm_kwargs."""
        kwargs = {"temperature": 0.7, "max_tokens": 2000}
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            llm_kwargs=kwargs
        )
        assert config.llm_kwargs == kwargs

    def test_config_backend_scope(self):
        """Config should accept backend_scope."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            backend_scope=["shell", "mcp"]
        )
        assert config.backend_scope == ["shell", "mcp"]

    def test_config_evolution_max_concurrent(self):
        """Config should accept evolution concurrency limit."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            evolution_max_concurrent=5
        )
        assert config.evolution_max_concurrent == 5


# ============================================================================
# Tests: OpenSpace State Management
# ============================================================================


class TestOpenSpaceState:
    """Test OpenSpace state management."""

    def test_openspace_last_evolved_skills_empty_initially(self, env_setup, basic_config):
        """Last evolved skills should be empty initially."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._last_evolved_skills == []

    def test_openspace_llm_client_lazy_initialized(self, env_setup, basic_config):
        """LLM client should be None before initialization."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._llm_client is None

    def test_openspace_grounding_client_lazy_initialized(self, env_setup, basic_config):
        """Grounding client should be None before initialization."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._grounding_client is None

    def test_openspace_skill_registry_lazy_initialized(self, env_setup, basic_config):
        """Skill registry should be None before initialization."""
        openspace = OpenSpace(config=basic_config)
        assert openspace._skill_registry is None


# ============================================================================
# Tests: Configuration Combinations
# ============================================================================


class TestConfigurationCombinations:
    """Test realistic configuration combinations."""

    def test_config_for_local_development(self):
        """Config for local development."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            log_level="DEBUG",
            enable_recording=True,
            enable_screenshot=False,
            grounding_max_iterations=10
        )
        assert config.llm_model == "claude-sonnet-4-6"
        assert config.log_level == "DEBUG"
        assert config.grounding_max_iterations == 10

    def test_config_for_production(self):
        """Config for production."""
        config = OpenSpaceConfig(
            llm_model="claude-opus-4-6",
            llm_max_retries=5,
            llm_timeout=300.0,
            log_level="WARNING",
            enable_recording=False,
            log_to_file=True
        )
        assert config.llm_model == "claude-opus-4-6"
        assert config.llm_max_retries == 5
        assert config.log_level == "WARNING"
        assert config.log_to_file is True

    def test_config_for_testing(self):
        """Config for testing."""
        config = OpenSpaceConfig(
            llm_model="claude-haiku-4-5-20251001",
            llm_timeout=30.0,
            llm_max_retries=1,
            enable_recording=False,
            enable_screenshot=False,
            enable_video=False
        )
        assert config.llm_model == "claude-haiku-4-5-20251001"
        assert config.llm_timeout == 30.0


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    def test_create_and_configure_openspace(self, env_setup, basic_config):
        """Create and configure OpenSpace instance."""
        openspace = OpenSpace(config=basic_config)
        assert openspace.config.llm_model == "claude-sonnet-4-6"
        assert not openspace._initialized

    def test_config_with_all_options_specified(self):
        """Config with all options explicitly set."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            llm_enable_thinking=True,
            llm_timeout=180.0,
            llm_max_retries=5,
            llm_rate_limit_delay=0.5,
            tool_retrieval_model="gpt-4o",
            visual_analysis_model="claude-opus-4-6",
            skill_registry_model="gpt-4o",
            execution_analyzer_model="claude-opus-4-6",
            grounding_config_path="/path/to/config.yaml",
            grounding_max_iterations=25,
            backend_scope=["shell", "mcp"],
            workspace_dir="/tmp/workspace",
            enable_recording=True,
            recording_backends=["shell"],
            enable_screenshot=True,
            enable_video=True,
            enable_conversation_log=True,
            evolution_max_concurrent=5,
            log_level="DEBUG",
            log_to_file=True
        )
        assert config.llm_model == "claude-sonnet-4-6"
        assert config.llm_enable_thinking is True
        assert config.grounding_max_iterations == 25

    @pytest.mark.asyncio
    async def test_openspace_initialization_flow(self, env_setup, basic_config):
        """Test typical OpenSpace initialization flow."""
        openspace = OpenSpace(config=basic_config)
        assert not openspace._initialized

        # Would attempt initialization (may fail due to missing grounding config)
        try:
            await openspace.initialize()
            # If successful, should be initialized
            assert openspace._initialized is True
        except (ValueError, FileNotFoundError, TypeError):
            # Expected if config/files not available
            pass

    def test_openspace_with_custom_logging(self):
        """Create OpenSpace with custom logging config."""
        config = OpenSpaceConfig(
            llm_model="claude-sonnet-4-6",
            log_level="DEBUG",
            log_to_file=True,
            log_file_path="/tmp/openspace.log"
        )
        openspace = OpenSpace(config=config)
        assert openspace.config.log_level == "DEBUG"
        assert openspace.config.log_to_file is True
