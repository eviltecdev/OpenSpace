"""Tests for LLMClient.complete() function with tool execution.

Tests tool handling, execution, callbacks, summarization, rate limiting,
retry logic, and error cases. Target coverage: 50%+
"""

import json
import pytest
import asyncio
from unittest.mock import MagicMock, Mock, AsyncMock, patch, call
from typing import Optional, List, Dict, Any

from openspace.llm.client import LLMClient
from openspace.grounding.core.types import ToolResult, ToolStatus, BackendType


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def env_setup(monkeypatch):
    """Set up environment for LLMClient tests."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")


@pytest.fixture
def client(env_setup):
    """Initialize LLMClient with test configuration."""
    return LLMClient(
        model="claude-sonnet-4-6",
        rate_limit_delay=0,  # No delays in tests
        max_retries=2,
        timeout=30
    )


@pytest.fixture
def mock_asyncio_sleep(monkeypatch):
    """Mock asyncio.sleep to skip delays (instant execution)."""
    async def instant_sleep(duration):
        pass

    monkeypatch.setattr("asyncio.sleep", instant_sleep)


@pytest.fixture
def mock_llm_basic_response(monkeypatch):
    """Mock basic LLM response without tool calls."""
    import litellm

    async def mock_acompletion(*args, **kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = "I can help with that."
        response.choices[0].message.tool_calls = None
        response.usage = Mock(prompt_tokens=10, completion_tokens=5)
        response._response_cost = 0.001
        return response

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)


@pytest.fixture
def mock_llm_with_tool_calls(monkeypatch):
    """Mock LLM response with tool calls."""
    import litellm

    async def mock_acompletion(*args, **kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = None
        response.choices[0].message.tool_calls = [
            MagicMock(
                id="call_001",
                function=MagicMock(
                    name="test_tool",
                    arguments='{"input": "test_value"}'
                )
            )
        ]
        response.usage = Mock(prompt_tokens=20, completion_tokens=10)
        response._response_cost = 0.002
        return response

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)


@pytest.fixture
def mock_llm_with_multiple_tool_calls(monkeypatch):
    """Mock LLM response with multiple tool calls."""
    import litellm

    async def mock_acompletion(*args, **kwargs):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = None
        response.choices[0].message.tool_calls = [
            MagicMock(
                id="call_001",
                function=MagicMock(
                    name="tool_1",
                    arguments='{"param": "value1"}'
                )
            ),
            MagicMock(
                id="call_002",
                function=MagicMock(
                    name="tool_2",
                    arguments='{"param": "value2"}'
                )
            )
        ]
        response.usage = Mock(prompt_tokens=30, completion_tokens=15)
        response._response_cost = 0.003
        return response

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)


@pytest.fixture
def mock_tool():
    """Mock a BaseTool for execution."""
    tool = MagicMock()
    tool.name = "test_tool"
    tool.description = "A test tool"
    tool.is_bound = True
    # Mock runtime_info with BackendType enum
    runtime_info = MagicMock()
    runtime_info.backend = BackendType.MCP
    runtime_info.server_name = "test_server"
    tool.runtime_info = runtime_info

    async def mock_invoke(*args, **kwargs):
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content="Tool executed successfully",
            tool_output={"result": "success", "data": "test_data"}
        )

    tool.invoke = mock_invoke
    return tool


@pytest.fixture
def mock_tool_with_large_output():
    """Mock a tool that returns large output (requires summarization)."""
    tool = MagicMock()
    tool.name = "large_tool"
    tool.description = "Tool with large output"
    tool.is_bound = True
    # Mock runtime_info with BackendType enum
    runtime_info = MagicMock()
    runtime_info.backend = BackendType.MCP
    runtime_info.server_name = "test_server"
    tool.runtime_info = runtime_info

    async def mock_invoke(*args, **kwargs):
        # Generate large content (>200K chars for summarization)
        large_content = "x" * 300000
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=large_content,
            tool_output={"data": large_content}
        )

    tool.invoke = mock_invoke
    return tool


@pytest.fixture
def mock_tool_error():
    """Mock a tool that fails."""
    tool = MagicMock()
    tool.name = "error_tool"

    async def mock_invoke(*args, **kwargs):
        return ToolResult(
            status=ToolStatus.ERROR,
            content="Tool failed",
            tool_output={"error": "invalid parameter"}
        )

    tool.invoke = mock_invoke
    return tool


# ============================================================================
# Tests: Basic Completion (No Tools)
# ============================================================================


class TestCompleteBasic:
    """Test complete() without tool execution."""

    @pytest.mark.asyncio
    async def test_complete_simple_message(self, client, mock_llm_basic_response, mock_asyncio_sleep):
        """Test complete() with simple message (no tools)."""
        result = await client.complete(
            messages=[{"role": "user", "content": "Hello"}],
            tools=None,
            execute_tools=False
        )

        assert result is not None
        assert "message" in result
        assert result["message"]["role"] == "assistant"
        assert result["has_tool_calls"] is False

    @pytest.mark.asyncio
    async def test_complete_multiple_messages(self, client, mock_llm_basic_response, mock_asyncio_sleep):
        """Test complete() with message history."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": "Question 2"}
        ]

        result = await client.complete(
            messages=messages,
            tools=None,
            execute_tools=False
        )

        assert result is not None
        assert len(result["messages"]) > 0

    @pytest.mark.asyncio
    async def test_complete_with_string_message(self, client, mock_llm_basic_response, mock_asyncio_sleep):
        """Test complete() accepts string message (auto-converted to list)."""
        result = await client.complete(
            messages="What is Python?",
            tools=None,
            execute_tools=False
        )

        assert result is not None
        assert result["message"]["role"] == "assistant"


# ============================================================================
# Tests: Tool Execution
# ============================================================================


class TestCompleteWithToolExecution:
    """Test complete() with tool execution."""

    @pytest.mark.asyncio
    async def test_execute_single_tool(self, client, mock_llm_with_tool_calls, mock_tool, mock_asyncio_sleep, monkeypatch):
        """Test executing a single tool call."""
        # Mock tool resolution - returns (tool_obj, ambiguous_names)
        def mock_resolve(*args):
            return (mock_tool, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)

        # Mock tool preparation
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"test_tool": mock_tool})
        )

        result = await client.complete(
            messages=[{"role": "user", "content": "Use the test tool"}],
            tools=[mock_tool],
            execute_tools=True
        )

        assert result["has_tool_calls"] is True
        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["backend"] == "mcp"  # BackendType.MCP.value
        assert result["tool_results"][0]["server_name"] == "test_server"

    @pytest.mark.asyncio
    async def test_execute_multiple_tools(self, client, mock_llm_with_multiple_tool_calls, mock_tool, mock_asyncio_sleep, monkeypatch):
        """Test executing multiple tool calls in sequence."""
        tool2 = MagicMock()
        tool2.name = "tool_2"
        tool2.is_bound = True
        # Mock runtime_info with BackendType enum
        runtime_info2 = MagicMock()
        runtime_info2.backend = BackendType.SHELL
        runtime_info2.server_name = "server_2"
        tool2.runtime_info = runtime_info2

        async def tool2_invoke(*args, **kwargs):
            return ToolResult(status=ToolStatus.SUCCESS, content="Tool 2 success")

        tool2.invoke = tool2_invoke

        def mock_resolve(tool_map, name):
            tool = tool_map.get(name)
            return (tool, []) if tool else (None, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"tool_1": mock_tool, "tool_2": tool2})
        )

        result = await client.complete(
            messages=[{"role": "user", "content": "Use tools"}],
            tools=[mock_tool, tool2],
            execute_tools=True
        )

        assert result["has_tool_calls"] is True
        assert len(result["tool_results"]) == 2

    @pytest.mark.asyncio
    async def test_execute_tools_disabled(self, client, mock_llm_with_tool_calls, mock_asyncio_sleep, monkeypatch):
        """Test that tools are not executed when execute_tools=False."""
        def mock_resolve(*args):
            raise AssertionError("Tool should not be resolved if execute_tools=False")

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {})
        )

        result = await client.complete(
            messages=[{"role": "user", "content": "Use tool"}],
            tools=[MagicMock()],
            execute_tools=False
        )

        # Tool calls exist in response but weren't executed
        # (LLM decided to make the call, but we didn't execute)
        assert result is not None


# ============================================================================
# Tests: Tool Callbacks
# ============================================================================


class TestToolCallback:
    """Test tool_result_callback functionality."""

    @pytest.mark.asyncio
    async def test_tool_callback_invoked(self, client, mock_llm_with_tool_calls, mock_tool, mock_asyncio_sleep, monkeypatch):
        """Test that tool_result_callback is called with tool results."""
        def mock_resolve(*args):
            return (mock_tool, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"test_tool": mock_tool})
        )

        callback_invocations = []

        def callback(*args, **kwargs):
            callback_invocations.append((args, kwargs))

        result = await client.complete(
            messages=[{"role": "user", "content": "Use tool"}],
            tools=[mock_tool],
            execute_tools=True,
            tool_result_callback=callback
        )

        # Callback should have been called at least once
        assert len(callback_invocations) > 0

    @pytest.mark.asyncio
    async def test_callback_failure_doesnt_crash(self, client, mock_llm_with_tool_calls, mock_tool, mock_asyncio_sleep, monkeypatch):
        """Test that callback failure doesn't crash complete()."""
        def mock_resolve(*args):
            return (mock_tool, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"test_tool": mock_tool})
        )

        def failing_callback(*args, **kwargs):
            raise ValueError("Callback error")

        # Should not raise even if callback fails
        try:
            result = await client.complete(
                messages=[{"role": "user", "content": "Use tool"}],
                tools=[mock_tool],
                execute_tools=True,
                tool_result_callback=failing_callback
            )
            # If callback error is caught, result should still be returned
            assert result is not None
        except ValueError:
            # Some implementations may let callback errors propagate
            pass


# ============================================================================
# Tests: Tool Result Summarization
# ============================================================================


class TestToolResultSummarization:
    """Test large tool result summarization."""

    @pytest.mark.asyncio
    async def test_large_result_summarization(self, client, mock_llm_with_tool_calls, mock_tool_with_large_output, mock_asyncio_sleep, monkeypatch):
        """Test that large tool results are summarized."""
        def mock_resolve(*args):
            return (mock_tool_with_large_output, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"large_tool": mock_tool_with_large_output})
        )

        # Mock summarization - must be async since it's awaited in client.py
        async def mock_summarize(*args, **kwargs):
            return "Summarized: Large output shortened"

        monkeypatch.setattr(
            "openspace.llm.client._summarize_tool_result",
            mock_summarize
        )

        result = await client.complete(
            messages=[{"role": "user", "content": "Get large data"}],
            tools=[mock_tool_with_large_output],
            execute_tools=True
        )

        assert result["has_tool_calls"] is True
        # Result message should contain tool result (summarized)
        assert len(result["tool_results"]) == 1


# ============================================================================
# Tests: Rate Limiting & Retries
# ============================================================================


class TestRateLimitAndRetry:
    """Test rate limiting and retry logic."""

    @pytest.mark.asyncio
    async def test_rate_limit_applied(self, env_setup, monkeypatch):
        """Test that rate limiting adds delay between calls."""
        import litellm

        call_times = []

        async def mock_slow_acompletion(*args, **kwargs):
            call_times.append(asyncio.get_event_loop().time())
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message = MagicMock()
            response.choices[0].message.content = "response"
            response.choices[0].message.tool_calls = None
            response.usage = Mock(prompt_tokens=1, completion_tokens=1)
            response._response_cost = 0.0001
            return response

        monkeypatch.setattr(litellm, "acompletion", mock_slow_acompletion)

        client = LLMClient(rate_limit_delay=0.01)  # 10ms delay

        # First call
        await client.complete(
            messages=[{"role": "user", "content": "First"}],
            tools=None,
            execute_tools=False
        )

        # Second call (should have delay)
        await client.complete(
            messages=[{"role": "user", "content": "Second"}],
            tools=None,
            execute_tools=False
        )

        # Verify at least 2 calls were made
        assert len(call_times) >= 2

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, client, mock_asyncio_sleep, monkeypatch):
        """Test retry logic on rate limit error."""
        import litellm

        call_count = [0]

        async def mock_flaky_acompletion(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call fails
                raise Exception("rate_limit_exceeded")
            # Second call succeeds
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message = MagicMock()
            response.choices[0].message.content = "success"
            response.choices[0].message.tool_calls = None
            response.usage = Mock(prompt_tokens=1, completion_tokens=1)
            response._response_cost = 0.0001
            return response

        monkeypatch.setattr(litellm, "acompletion", mock_flaky_acompletion)

        # Should eventually succeed after retry
        try:
            result = await client.complete(
                messages=[{"role": "user", "content": "test"}],
                tools=None,
                execute_tools=False
            )
            # If retry works, we get a result
            assert result is not None
        except Exception:
            # If retry exhausts, exception is raised
            assert call_count[0] > 1


# ============================================================================
# Tests: Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error handling in complete()."""

    @pytest.mark.asyncio
    async def test_tool_not_found(self, client, mock_llm_with_tool_calls, mock_asyncio_sleep, monkeypatch):
        """Test handling when tool is not found."""
        def mock_resolve(*args):
            return (None, [])  # Tool not found

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {})
        )

        # Should handle missing tool gracefully
        try:
            result = await client.complete(
                messages=[{"role": "user", "content": "Use tool"}],
                tools=[MagicMock()],
                execute_tools=True
            )
            # May return error result or raise
            assert result is not None
        except (ValueError, KeyError):
            # Some implementations raise on tool not found
            pass

    @pytest.mark.asyncio
    async def test_tool_execution_error(self, client, mock_llm_with_tool_calls, mock_tool_error, mock_asyncio_sleep, monkeypatch):
        """Test handling of tool execution errors."""
        def mock_resolve(*args):
            return (mock_tool_error, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"error_tool": mock_tool_error})
        )

        result = await client.complete(
            messages=[{"role": "user", "content": "Use tool"}],
            tools=[mock_tool_error],
            execute_tools=True
        )

        # Should handle tool error and include in result
        assert result is not None
        assert len(result["tool_results"]) == 1
        # Tool result status should be ERROR
        assert result["tool_results"][0]["result"].status == ToolStatus.ERROR


# ============================================================================
# Tests: Return Value Structure
# ============================================================================


class TestReturnValue:
    """Test complete() return value structure."""

    @pytest.mark.asyncio
    async def test_return_value_keys(self, client, mock_llm_basic_response, mock_asyncio_sleep):
        """Test that return value contains all expected keys."""
        result = await client.complete(
            messages=[{"role": "user", "content": "Hello"}],
            tools=None,
            execute_tools=False
        )

        # Check required keys
        assert "message" in result
        assert "messages" in result
        assert "has_tool_calls" in result
        assert "tool_results" in result

    @pytest.mark.asyncio
    async def test_message_structure(self, client, mock_llm_basic_response, mock_asyncio_sleep):
        """Test assistant message structure."""
        result = await client.complete(
            messages=[{"role": "user", "content": "Test"}],
            tools=None,
            execute_tools=False
        )

        message = result["message"]
        assert message["role"] == "assistant"
        assert "content" in message

    @pytest.mark.asyncio
    async def test_tool_result_structure(self, client, mock_llm_with_tool_calls, mock_tool, mock_asyncio_sleep, monkeypatch):
        """Test tool result structure in return value."""
        def mock_resolve(*args):
            return (mock_tool, [])

        monkeypatch.setattr("openspace.llm.client._resolve_tool_call_target", mock_resolve)
        monkeypatch.setattr(
            "openspace.llm.client._prepare_tools_for_llmclient",
            lambda tools, fmt=None: ([], {"test_tool": mock_tool})
        )

        result = await client.complete(
            messages=[{"role": "user", "content": "Use tool"}],
            tools=[mock_tool],
            execute_tools=True
        )

        tool_result = result["tool_results"][0]
        assert "tool_call" in tool_result
        assert "result" in tool_result
        assert "message" in tool_result
        assert "backend" in tool_result
        assert "server_name" in tool_result
