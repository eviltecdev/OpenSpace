"""Test that max_iterations is passed to grounding agent in no-skill path."""

import asyncio
import types
from unittest.mock import AsyncMock, patch

import pytest

from openspace.tool_layer import OpenSpace, OpenSpaceConfig


def _make_openspace(configured_max: int = 50) -> OpenSpace:
    config = OpenSpaceConfig()
    config.grounding_max_iterations = configured_max
    os_inst = OpenSpace(config)
    os_inst._initialized = True
    os_inst._running = False
    os_inst._task_done = asyncio.Event()
    os_inst._task_done.set()
    os_inst._grounding_client = types.SimpleNamespace(_registry={})
    os_inst._recording_manager = None
    os_inst._skill_registry = None
    os_inst._execution_analyzer = None
    os_inst._skill_evolver = None
    return os_inst


@pytest.mark.asyncio
async def test_no_skill_path_passes_configured_max_iterations():
    """When no skills match, the configured grounding_max_iterations
    must be forwarded to the agent, not silently dropped."""
    os_inst = _make_openspace(configured_max=50)
    recorded = {}

    async def fake_process(context):
        recorded.update(context)
        return {"status": "success", "iterations": 1, "tool_executions": []}

    os_inst._grounding_agent = types.SimpleNamespace(process=fake_process)
    os_inst._maybe_analyze_execution = AsyncMock()
    os_inst._maybe_evolve_quality = AsyncMock()

    await os_inst.execute("do something")

    assert recorded.get("max_iterations") == 50


@pytest.mark.asyncio
async def test_no_skill_path_uses_caller_override_when_larger():
    """Caller-provided max_iterations should win when larger than config."""
    os_inst = _make_openspace(configured_max=20)
    recorded = {}

    async def fake_process(context):
        recorded.update(context)
        return {"status": "success", "iterations": 1, "tool_executions": []}

    os_inst._grounding_agent = types.SimpleNamespace(process=fake_process)
    os_inst._maybe_analyze_execution = AsyncMock()
    os_inst._maybe_evolve_quality = AsyncMock()

    await os_inst.execute("do something", max_iterations=100)

    assert recorded.get("max_iterations") == 100
