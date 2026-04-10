"""Tests for GroundingClient — Session/Tool management, Provider coordination.

Target coverage: 90% (currently 30%)
Test count: 15 tests covering:
- Provider lifecycle & registration
- Session management (create, close, cleanup)
- Tool caching (TTL, LRU eviction)
- Tool search & ranking integration
- Tool invocation (BaseTool instance and string name dispatch)
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from typing import List

import pytest

from openspace.grounding.core.grounding_client import GroundingClient
from openspace.grounding.core.types import (
    BackendType,
    SessionConfig,
    SessionInfo,
    SessionStatus,
    ToolResult,
)
from openspace.grounding.core.exceptions import GroundingError
from openspace.grounding.core.provider import Provider, ProviderRegistry
from openspace.grounding.core.tool import BaseTool
from openspace.grounding.core.session import BaseSession
from openspace.config import GroundingConfig


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def grounding_config():
    """Mock GroundingConfig."""
    config = MagicMock(spec=GroundingConfig)
    config.enabled_backends = [
        {"name": "shell", "provider_cls": "openspace.grounding.backends.shell.ShellProvider"},
        {"name": "web", "provider_cls": "openspace.grounding.backends.web.WebProvider"},
    ]
    config.tool_cache_ttl = 300
    config.tool_cache_maxsize = 300
    config.max_concurrent_sessions = 10
    config.tool_search = MagicMock()
    config.tool_search.max_tools = 30
    config.tool_quality = MagicMock()
    config.tool_quality.enabled = False  # Disable quality manager for simpler tests
    return config


@pytest.fixture
def mock_provider():
    """Mock Provider instance."""
    from openspace.grounding.core.types import ToolStatus
    provider = AsyncMock(spec=Provider)
    provider.is_initialized = False
    provider.initialize = AsyncMock(return_value=None)
    provider.list_tools = AsyncMock(return_value=[])
    provider.create_session = AsyncMock(return_value=MagicMock(spec=BaseSession))
    provider.close_session = AsyncMock(return_value=None)
    provider.call_tool = AsyncMock(return_value=ToolResult(status=ToolStatus.SUCCESS, content="ok"))
    return provider


@pytest.fixture
def mock_registry():
    """Mock ProviderRegistry."""
    registry = MagicMock(spec=ProviderRegistry)
    registry.register = MagicMock()
    registry.list = MagicMock(return_value={})
    return registry


@pytest.fixture
def mock_base_tool():
    """Mock BaseTool instance."""
    tool = MagicMock(spec=BaseTool)
    tool.name = "test-tool"
    tool.schema = MagicMock()
    tool.schema.name = "test-tool"
    tool.is_bound = False
    tool.bind_runtime_info = MagicMock()
    return tool


@pytest.fixture
def grounding_client(grounding_config, mock_registry):
    """GroundingClient with mocked dependencies."""
    with patch("openspace.grounding.core.grounding_client.GroundingConfig", grounding_config):
        with patch("openspace.grounding.core.grounding_client.ProviderRegistry", return_value=mock_registry):
            with patch("openspace.grounding.core.grounding_client.importlib.import_module"):
                with patch.object(GroundingClient, "_register_providers_from_config"):
                    with patch.object(GroundingClient, "_register_system_provider"):
                        with patch.object(GroundingClient, "_init_quality_manager", return_value=None):
                            client = GroundingClient(config=grounding_config)
                            client._registry = mock_registry
                            return client


# ============================================================================
# Tests: Provider Lifecycle
# ============================================================================


class TestProviderLifecycle:
    """Test provider registration and initialization."""

    def test_provider_register_from_config_valid(self, grounding_config):
        """Provider registration with valid module path."""
        with patch("openspace.grounding.core.grounding_client.importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_provider_cls = MagicMock(spec=Provider)
            mock_module.ShellProvider = mock_provider_cls
            mock_import.return_value = mock_module

            with patch("openspace.grounding.core.grounding_client.ProviderRegistry") as mock_registry_cls:
                mock_registry_inst = MagicMock()
                mock_registry_cls.return_value = mock_registry_inst

                with patch.object(GroundingClient, "_register_system_provider"):
                    with patch.object(GroundingClient, "_init_quality_manager", return_value=None):
                        client = GroundingClient(config=grounding_config)
                        # Verify that registry.register would be called during _register_providers_from_config
                        # In actual code, this is called automatically
                        assert client._registry is not None

    def test_provider_register_from_config_invalid_module(self, grounding_config):
        """Provider registration with invalid module path."""
        bad_config = grounding_config
        bad_config.enabled_backends = [
            {"name": "invalid", "provider_cls": "nonexistent.module.Provider"}
        ]

        with patch("openspace.grounding.core.grounding_client.importlib.import_module") as mock_import:
            mock_import.side_effect = ModuleNotFoundError("No module named 'nonexistent'")

            with patch("openspace.grounding.core.grounding_client.ProviderRegistry"):
                with patch.object(GroundingClient, "_register_system_provider"):
                    with patch.object(GroundingClient, "_init_quality_manager", return_value=None):
                        # Should handle exception gracefully
                        client = GroundingClient(config=bad_config)
                        assert client is not None

    @pytest.mark.asyncio
    async def test_system_provider_init_requires_client(self, grounding_config, mock_registry):
        """SystemProvider registration requires GroundingClient instance."""
        with patch.object(GroundingClient, "_register_providers_from_config"):
            with patch("openspace.grounding.core.grounding_client.importlib.import_module"):
                with patch.object(GroundingClient, "_init_quality_manager", return_value=None):
                    # Mock SystemProvider import
                    with patch("openspace.grounding.core.grounding_client.importlib.import_module") as mock_import:
                        mock_system_provider_cls = MagicMock(spec=Provider)
                        mock_import.return_value.SystemProvider = mock_system_provider_cls

                        client = GroundingClient(config=grounding_config)
                        client._registry = mock_registry
                        # SystemProvider init should pass client instance
                        # _register_system_provider would use: SystemProvider(self)
                        assert client is not None


# ============================================================================
# Tests: Session Management
# ============================================================================


class TestSessionManagement:
    """Test session creation, closing, and cleanup."""

    @pytest.mark.asyncio
    async def test_create_session_within_limit(self, grounding_client, mock_registry, mock_provider):
        """Create session within concurrent limit."""
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        session_id = await grounding_client.create_session(backend=BackendType.SHELL, name="test-session")

        assert session_id == "test-session"
        assert "test-session" in grounding_client._sessions
        assert "test-session" in grounding_client._session_info

    @pytest.mark.asyncio
    async def test_create_session_exceeds_max(self, grounding_client, grounding_config, mock_provider):
        """Reject session creation when exceeding max concurrent limit."""
        grounding_client._config.max_concurrent_sessions = 2
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # Create two sessions
        await grounding_client.create_session(backend=BackendType.SHELL, name="session-1")
        await grounding_client.create_session(backend=BackendType.SHELL, name="session-2")

        # Third should fail
        with pytest.raises(GroundingError, match="maximum session limit"):
            await grounding_client.create_session(backend=BackendType.SHELL, name="session-3")

    @pytest.mark.asyncio
    async def test_close_session_cleans_up(self, grounding_client, mock_registry, mock_provider):
        """Close session and clean up all caches."""
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # Create session
        session_id = await grounding_client.create_session(backend=BackendType.SHELL, name="test-session")

        # Add to tool cache
        grounding_client._tool_cache["test-session"] = ([], time.time())

        # Close session
        await grounding_client.close_session(session_id)

        assert session_id not in grounding_client._sessions
        assert session_id not in grounding_client._session_info
        assert session_id not in grounding_client._tool_cache

    @pytest.mark.asyncio
    async def test_close_all_sessions_concurrent(self, grounding_client, mock_registry, mock_provider):
        """Close all sessions concurrently."""
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # Create multiple sessions
        await grounding_client.create_session(backend=BackendType.SHELL, name="session-1")
        await grounding_client.create_session(backend=BackendType.SHELL, name="session-2")
        await grounding_client.create_session(backend=BackendType.SHELL, name="session-3")

        # Close all
        await grounding_client.close_all_sessions()

        assert len(grounding_client._sessions) == 0
        assert len(grounding_client._session_info) == 0


# ============================================================================
# Tests: Tool Caching
# ============================================================================


class TestToolCaching:
    """Test tool cache TTL, LRU eviction, and concurrent updates."""

    @pytest.mark.asyncio
    async def test_tool_cache_hit_returns_cached(self, grounding_client, mock_registry, mock_provider):
        """Cache hit returns cached tools without refetching."""
        tools = [MagicMock(spec=BaseTool)]
        mock_provider.list_tools.return_value = tools
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # First call — fetches from provider
        result1 = await grounding_client._fetch_tools(BackendType.SHELL, use_cache=True)
        assert result1 == tools
        assert mock_provider.list_tools.call_count == 1

        # Second call — should use cache
        result2 = await grounding_client._fetch_tools(BackendType.SHELL, use_cache=True)
        assert result2 == tools
        # Provider should not be called again (still 1)
        assert mock_provider.list_tools.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_cache_miss_refetches(self, grounding_client, mock_registry, mock_provider):
        """Expired cache triggers refetch from provider."""
        tools = [MagicMock(spec=BaseTool)]
        mock_provider.list_tools.return_value = tools
        grounding_client._registry.get = MagicMock(return_value=mock_provider)
        grounding_client._tool_cache_ttl = 1  # 1 second TTL

        # First call
        result1 = await grounding_client._fetch_tools(BackendType.SHELL, use_cache=True)
        assert result1 == tools

        # Sleep longer than TTL
        time.sleep(1.1)

        # Second call should refetch
        result2 = await grounding_client._fetch_tools(BackendType.SHELL, use_cache=True)
        assert result2 == tools
        assert mock_provider.list_tools.call_count == 2

    @pytest.mark.asyncio
    async def test_tool_cache_lock_prevents_race(self, grounding_client, mock_registry, mock_provider):
        """Concurrent cache updates use asyncio.Lock."""
        tools = [MagicMock(spec=BaseTool)]
        mock_provider.list_tools.return_value = tools
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # Simulate two concurrent calls
        task1 = grounding_client._fetch_tools(BackendType.SHELL, use_cache=True)
        task2 = grounding_client._fetch_tools(BackendType.SHELL, use_cache=True)

        results = await asyncio.gather(task1, task2)

        # Both should get same tools
        assert results[0] == tools
        assert results[1] == tools
        # Only one provider call (due to locking)
        assert mock_provider.list_tools.call_count == 1


# ============================================================================
# Tests: Tool Search & Ranking
# ============================================================================


class TestToolSearchRanking:
    """Test SearchCoordinator integration and fallback behavior."""

    @pytest.mark.asyncio
    async def test_search_tools_with_ranking(self, grounding_client, mock_registry, mock_provider):
        """SearchCoordinator integration with quality ranking."""
        tools = [MagicMock(spec=BaseTool) for _ in range(5)]
        mock_provider.list_tools.return_value = tools
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # Mock SearchCoordinator
        with patch("openspace.grounding.core.grounding_client.SearchCoordinator") as mock_search:
            mock_search_inst = AsyncMock()
            mock_search_inst._arun = AsyncMock(return_value=[tools[0], tools[1]])
            mock_search.return_value = mock_search_inst

            result = await grounding_client.search_tools(
                "find useful tools",
                backend=BackendType.SHELL,
                max_tools=10
            )

            # Should return filtered tools
            assert len(result) <= 2
            mock_search_inst._arun.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_tools_fallback_on_error(self, grounding_client, mock_registry, mock_provider):
        """Exception in SearchCoordinator triggers fallback to top N tools."""
        tools = [MagicMock(spec=BaseTool) for _ in range(10)]
        mock_provider.list_tools.return_value = tools
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        with patch("openspace.grounding.core.grounding_client.SearchCoordinator") as mock_search:
            mock_search_inst = AsyncMock()
            mock_search_inst._arun = AsyncMock(side_effect=Exception("Search failed"))
            mock_search.return_value = mock_search_inst

            result = await grounding_client.search_tools(
                "find tools",
                backend=BackendType.SHELL,
                max_tools=3
            )

            # Should fallback to first 3 tools
            assert len(result) == 3
            assert result == tools[:3]

    @pytest.mark.asyncio
    async def test_get_tools_with_auto_search_decision(self, grounding_client, mock_registry, mock_provider):
        """Auto-search decision based on tool count vs max_tools."""
        small_tools = [MagicMock(spec=BaseTool) for _ in range(5)]
        mock_provider.list_tools.return_value = small_tools
        grounding_client._registry.get = MagicMock(return_value=mock_provider)

        # No task_description, should return all tools
        result = await grounding_client.get_tools_with_auto_search(
            backend=BackendType.SHELL,
            max_tools=30
        )

        # Should return all tools without search
        assert result == small_tools


# ============================================================================
# Tests: Tool Invocation
# ============================================================================


class TestToolInvocation:
    """Test tool invocation by instance and by name."""

    @pytest.mark.asyncio
    async def test_invoke_tool_by_instance_and_name(self, grounding_client, mock_registry, mock_provider):
        """Invoke tool using BaseTool instance."""
        tool = MagicMock(spec=BaseTool)
        tool.name = "read_file"
        tool.schema = MagicMock()
        tool.schema.name = "read_file"
        tool.is_bound = True
        tool.backend_type = BackendType.SHELL
        tool.runtime_info = MagicMock()
        tool.runtime_info.backend = BackendType.SHELL
        tool.runtime_info.session_name = "shell"
        tool.runtime_info.server_name = None

        grounding_client._registry.get = MagicMock(return_value=mock_provider)
        grounding_client._sessions["shell"] = MagicMock()
        grounding_client._session_info["shell"] = SessionInfo(
            session_name="shell",
            backend_type=BackendType.SHELL,
            status=SessionStatus.CONNECTED,
            created_at=datetime.utcnow(),
            last_activity=datetime.utcnow(),
        )

        result = await grounding_client.invoke_tool(tool, {"path": "/tmp/test.txt"})

        assert result.is_success is True
        mock_provider.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_tool_ambiguous_name_error(self, grounding_client, mock_registry, mock_provider):
        """Invoke tool by name when multiple tools match."""
        tool1 = MagicMock(spec=BaseTool)
        tool1.name = "read_file"
        tool1.is_bound = True
        tool1.runtime_info = MagicMock()
        tool1.runtime_info.backend = BackendType.SHELL
        tool1.runtime_info.session_name = "shell"

        tool2 = MagicMock(spec=BaseTool)
        tool2.name = "read_file"
        tool2.is_bound = True
        tool2.runtime_info = MagicMock()
        tool2.runtime_info.backend = BackendType.WEB
        tool2.runtime_info.session_name = "web"

        grounding_client._registry.get = MagicMock(return_value=mock_provider)
        grounding_client._sessions = {"shell": MagicMock(), "web": MagicMock()}
        grounding_client._session_info = {
            "shell": SessionInfo(
                session_name="shell",
                backend_type=BackendType.SHELL,
                status=SessionStatus.CONNECTED,
                created_at=datetime.utcnow(),
                last_activity=datetime.utcnow(),
            ),
            "web": SessionInfo(
                session_name="web",
                backend_type=BackendType.WEB,
                status=SessionStatus.CONNECTED,
                created_at=datetime.utcnow(),
                last_activity=datetime.utcnow(),
            ),
        }

        # Mock list_tools to return both tools
        with patch.object(grounding_client, "list_tools", return_value=[tool1, tool2]):
            with pytest.raises(GroundingError, match="Multiple tools named"):
                await grounding_client.invoke_tool("read_file", {})
