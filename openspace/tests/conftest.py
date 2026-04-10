"""Pytest configuration and shared fixtures for Phase 8 and beyond.

Provides:
- Global state isolation (async locks, lazy-initialized singletons)
- Recording test fixtures (pre-built directory structures)
- Rate limiter state reset
- MCP server mocking
- GUI/X11 module mocking for headless CI environments
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime


# ============================================================================
# CRITICAL: Pre-patch GUI modules at conftest load time (BEFORE any imports)
# ============================================================================
# This runs when pytest loads conftest.py, before any test or fixture imports.
# Must happen here, not in a fixture, to catch imports in openspace modules.

def _setup_gui_mocks():
    """Patch sys.modules with GUI library mocks at conftest load time."""
    pyatspi_mock = MagicMock()
    pyatspi_mock.Accessible = type('Accessible', (), {})
    pyatspi_mock.StateType = MagicMock()
    pyatspi_mock.STATE_SHOWING = MagicMock()
    pyatspi_mock.Registry = MagicMock()

    gui_mocks = {
        'pyautogui': MagicMock(),
        'mouseinfo': MagicMock(),
        'Xlib': MagicMock(),
        'Xlib.display': MagicMock(),
        'Xlib.X': MagicMock(),
        'pynput': MagicMock(),
        'pynput.keyboard': MagicMock(),
        'gi': MagicMock(),
        'gi.repository': MagicMock(),
        'gi.repository.Atspi': MagicMock(),
        'accessibility_inspector': MagicMock(),
        'pyatspi': pyatspi_mock,
        'pyxcursor': MagicMock(),
        # macOS-specific frameworks (prevent objc reload errors)
        'AppKit': MagicMock(),
        'atomacos': MagicMock(),
        'Foundation': MagicMock(),
        'Quartz': MagicMock(),
        'objc': MagicMock(),
        'CoreFoundation': MagicMock(),
    }

    for module_name, mock_obj in gui_mocks.items():
        sys.modules[module_name] = mock_obj

# Call immediately when conftest.py is loaded
_setup_gui_mocks()


# ============================================================================
# Global State Isolation Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def isolated_globals():
    """Reset global state before each test to avoid cross-test pollution."""
    # Import modules that have global state
    import openspace.mcp_server as mcp_server_module

    # Store original state
    original_openspace = getattr(mcp_server_module, '_openspace_instance', None)
    original_store = getattr(mcp_server_module, '_standalone_store', None)
    original_registered = getattr(mcp_server_module, '_registered_skill_dirs', None)

    yield  # Test runs here

    # Reset to original state
    if hasattr(mcp_server_module, '_openspace_instance'):
        mcp_server_module._openspace_instance = original_openspace
    if hasattr(mcp_server_module, '_standalone_store'):
        mcp_server_module._standalone_store = original_store
    if hasattr(mcp_server_module, '_registered_skill_dirs'):
        mcp_server_module._registered_skill_dirs = original_registered


@pytest.fixture
def mock_openspace():
    """AsyncMock for OpenSpace engine instance."""
    mock = AsyncMock()
    mock.execute = AsyncMock(return_value={
        "status": "success",
        "response": "Task completed",
        "iterations": 1,
        "skills_used": [],
    })
    return mock


@pytest.fixture
def rate_limiter_reset():
    """Reset rate limiter state for clean test isolation."""
    import openspace.mcp_server as mcp_server_module

    # Reset limiters if they exist
    if hasattr(mcp_server_module, 'execute_task_limiter'):
        limiter = mcp_server_module.execute_task_limiter
        # Reset token bucket state if accessible
        if hasattr(limiter, '_tokens'):
            limiter._tokens = limiter._max_tokens
        if hasattr(limiter, '_request_times'):
            limiter._request_times = []

    yield

    # Clean up after test
    if hasattr(mcp_server_module, 'execute_task_limiter'):
        limiter = mcp_server_module.execute_task_limiter
        if hasattr(limiter, '_tokens'):
            limiter._tokens = limiter._max_tokens
        if hasattr(limiter, '_request_times'):
            limiter._request_times = []


# ============================================================================
# Recording Test Fixtures
# ============================================================================


@pytest.fixture
def sample_recording_dir(tmp_path):
    """Pre-built recording directory with JSON metadata."""
    recording_dir = tmp_path / "recording"
    recording_dir.mkdir()

    # Create metadata.json
    metadata = {
        "session_id": "test-session-123",
        "timestamp": datetime.now().isoformat(),
        "duration": 120,
        "agent": "test-agent",
        "task": "test task",
        "status": "completed",
    }
    (recording_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    # Create statistics.json
    statistics = {
        "total_steps": 10,
        "tool_calls": 5,
        "errors": 0,
        "success_rate": 1.0,
    }
    (recording_dir / "statistics.json").write_text(json.dumps(statistics, indent=2))

    # Create trajectory.json (list of steps)
    trajectory = [
        {
            "step": i,
            "action": f"action_{i}",
            "result": f"result_{i}",
            "timestamp": datetime.now().isoformat(),
        }
        for i in range(5)
    ]
    (recording_dir / "trajectory.json").write_text(json.dumps(trajectory, indent=2))

    # Create agent_actions.json (per-agent breakdown)
    agent_actions = {
        "test-agent": [
            {
                "step": 0,
                "action": "test_action",
                "success": True,
                "tool": "test_tool",
            }
        ]
    }
    (recording_dir / "agent_actions.json").write_text(json.dumps(agent_actions, indent=2))

    return recording_dir


@pytest.fixture
def recording_session_data():
    """Sample recording session JSON structure."""
    return {
        "session_id": "test-session",
        "timestamp": datetime.now().isoformat(),
        "duration": 100,
        "agent": "test-agent",
        "task": "test task",
        "iterations": 5,
        "skills_used": ["skill-001", "skill-002"],
        "tool_calls": 10,
        "success": True,
    }


@pytest.fixture
def empty_recording_dir(tmp_path):
    """Empty recording directory (no metadata)."""
    recording_dir = tmp_path / "empty_recording"
    recording_dir.mkdir()
    return recording_dir


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_recording_client():
    """Mock RecordingClient with async methods."""
    mock = AsyncMock()
    mock.start_recording = AsyncMock(return_value=True)
    mock.end_recording = AsyncMock(return_value="/tmp/recording.mp4")
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_cloud_client():
    """Mock OpenSpaceClient for cloud API."""
    mock = MagicMock()
    mock.search_record_embeddings = MagicMock(return_value=[
        {
            "skill_id": "cloud-skill-001",
            "name": "Cloud Skill",
            "description": "A cloud skill",
            "source": "cloud",
        }
    ])
    mock.download_artifact = MagicMock(return_value=b"artifact_data")
    return mock


if __name__ == "__main__":
    # Allow running conftest directly for debugging
    pytest.main([__file__, "-v"])
