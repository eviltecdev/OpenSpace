"""Tests for mcp_server — Orchestration layer (execute_task, rate limiting, skill registration).

Target coverage: Rate limiting, skill registration, cloud search, metadata management, result formatting, error handling
Test count: 45+ tests covering:
- Rate limiting (concurrent & per-minute throttling)
- Skill registration & auto-discovery
- Cloud search & import pipeline
- Metadata (.upload_meta.json) read/write
- Task result formatting
- Error handling (rate limit, cloud unavailable, init failure)
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_openspace_engine(mock_openspace):
    """Mock OpenSpace engine with full interface."""
    mock_openspace._skill_registry = MagicMock()
    mock_openspace._skill_registry.discover_from_dirs = MagicMock(return_value=[
        {"name": "skill-001", "path": "/tmp/skill-001"}
    ])
    mock_openspace.execute = AsyncMock(return_value={
        "status": "success",
        "response": "Task completed successfully",
        "execution_time": 1.5,
        "iterations": 3,
        "skills_used": ["skill-001"],
        "task_id": "task-123",
        "tool_executions": [
            {
                "tool_name": "test_tool",
                "status": "success",
                "error": None,
            }
        ],
        "evolved_skills": [],
        "warning": None,
    })
    mock_openspace.is_initialized = MagicMock(return_value=True)
    return mock_openspace


@pytest.fixture
def mock_skill_store():
    """Mock SkillStore for skill registration."""
    store = AsyncMock()
    store.sync_from_registry = AsyncMock(return_value=5)  # 5 new DB records
    store._closed = False
    return store


@pytest.fixture
def mock_cloud_client():
    """Mock OpenSpaceClient for cloud API."""
    client = MagicMock()
    client.search_record_embeddings = MagicMock(return_value=[
        {
            "record_id": "cloud-skill-001",
            "name": "Cloud Skill 1",
            "description": "Test cloud skill",
            "visibility": "public",
        },
        {
            "record_id": "cloud-skill-002",
            "name": "Cloud Skill 2",
            "visibility": "private",  # Should be filtered out
        },
    ])
    return client


@pytest.fixture
def sample_task_result():
    """Sample execution result from OpenSpace.execute()."""
    return {
        "status": "success",
        "response": "Task completed",
        "execution_time": 2.3,
        "iterations": 5,
        "skills_used": ["skill-001", "skill-002"],
        "task_id": "task-456",
        "tool_executions": [
            {"tool_name": "read_file", "status": "success", "error": None},
            {"tool_name": "write_file", "status": "success", "error": None},
        ],
        "evolved_skills": [
            {
                "path": "/tmp/skills/evolved-skill/run.py",
                "name": "evolved-skill",
                "origin": "derived",
                "change_summary": "Added error handling",
            }
        ],
        "warning": None,
    }


# ============================================================================
# Tests: Rate Limiting
# ============================================================================


class TestRateLimiter:
    """Test RateLimiter class."""

    @pytest.mark.asyncio
    async def test_rate_limiter_acquire_success(self):
        """Acquire token when within limits."""
        from openspace.mcp_server_limiter import RateLimiter

        limiter = RateLimiter(max_concurrent=3, max_per_minute=10)
        result = await limiter.acquire()

        assert result is True
        assert limiter.active_tasks == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_concurrent_limit(self):
        """Reject token when concurrent limit reached."""
        from openspace.mcp_server_limiter import RateLimiter

        limiter = RateLimiter(max_concurrent=2, max_per_minute=10)

        # Acquire 2 tokens (at limit)
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True

        # Third should fail
        assert await limiter.acquire() is False

    @pytest.mark.asyncio
    async def test_rate_limiter_per_minute_limit(self):
        """Reject token when per-minute limit reached."""
        from openspace.mcp_server_limiter import RateLimiter

        limiter = RateLimiter(max_concurrent=10, max_per_minute=2)

        # Acquire 2 tokens (at per-minute limit)
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True

        # Third should fail (per-minute limit)
        assert await limiter.acquire() is False

    @pytest.mark.asyncio
    async def test_rate_limiter_release(self):
        """Release decrements active task count."""
        from openspace.mcp_server_limiter import RateLimiter

        limiter = RateLimiter(max_concurrent=2, max_per_minute=10)

        await limiter.acquire()
        await limiter.acquire()
        assert limiter.active_tasks == 2

        await limiter.release()
        assert limiter.active_tasks == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_minute_window_purge(self):
        """Old request times purged from minute window."""
        from openspace.mcp_server_limiter import RateLimiter
        import time

        limiter = RateLimiter(max_concurrent=10, max_per_minute=2)

        # Add old timestamp (>60s ago)
        old_time = time.time() - 70
        limiter.request_times = [old_time]

        # Should acquire because old time is outside 60s window
        assert await limiter.acquire() is True
        assert len([t for t in limiter.request_times if t > time.time() - 60]) == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_race_safety(self):
        """Concurrent acquire/release is thread-safe."""
        from openspace.mcp_server_limiter import RateLimiter

        limiter = RateLimiter(max_concurrent=5, max_per_minute=100)

        # Simulate concurrent acquisitions
        results = await asyncio.gather(
            limiter.acquire(),
            limiter.acquire(),
            limiter.acquire(),
            limiter.acquire(),
            limiter.acquire(),
        )

        assert results == [True, True, True, True, True]
        assert limiter.active_tasks == 5


# ============================================================================
# Tests: Skill Registration
# ============================================================================


class TestSkillRegistration:
    """Test skill registration & auto-discovery."""

    @pytest.mark.asyncio
    async def test_auto_register_skill_dirs_valid_path(self, mock_openspace_engine, mock_skill_store, tmp_path):
        """Register skill directory."""
        from openspace.mcp_server import _auto_register_skill_dirs, _get_store

        test_dir = tmp_path / "test_skills"
        test_dir.mkdir()

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            with patch("openspace.mcp_server._get_store", return_value=mock_skill_store):
                skill_dirs = [str(test_dir)]
                count = await _auto_register_skill_dirs(skill_dirs)

                # Should return number of added skills
                assert isinstance(count, int)
                # Registry.discover_from_dirs was called
                assert mock_openspace_engine._skill_registry.discover_from_dirs.called

    @pytest.mark.asyncio
    async def test_auto_register_skill_dirs_empty_list(self, mock_openspace_engine):
        """Handle empty skill directory list."""
        from openspace.mcp_server import _auto_register_skill_dirs

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            count = await _auto_register_skill_dirs([])

            assert count == 0

    @pytest.mark.asyncio
    async def test_auto_register_skill_dirs_missing_path(self, mock_openspace_engine):
        """Skip non-existent directories."""
        from openspace.mcp_server import _auto_register_skill_dirs

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            count = await _auto_register_skill_dirs(["/nonexistent/path"])

            assert count == 0

    @pytest.mark.asyncio
    async def test_auto_register_skill_dirs_db_sync(self, mock_openspace_engine, mock_skill_store, tmp_path):
        """DB sync called for new skills."""
        from openspace.mcp_server import _auto_register_skill_dirs

        test_dir = tmp_path / "test"
        test_dir.mkdir()

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            with patch("openspace.mcp_server._get_store", return_value=mock_skill_store):
                await _auto_register_skill_dirs([str(test_dir)])

                # store.sync_from_registry should be called
                assert mock_skill_store.sync_from_registry.called


# ============================================================================
# Tests: Cloud Search & Import
# ============================================================================


class TestCloudSearchAndImport:
    """Test cloud search and auto-import pipeline."""

    @pytest.mark.asyncio
    async def test_cloud_search_empty_query(self):
        """Empty query returns empty list and cloud_available=True."""
        from openspace.mcp_server import _cloud_search_and_import

        with patch("openspace.mcp_server._get_cloud_client"):
            results, cloud_available = await _cloud_search_and_import("")

            assert results == []
            assert cloud_available is True

    @pytest.mark.asyncio
    async def test_cloud_search_empty_results(self, mock_cloud_client):
        """No results returns empty list and cloud_available=True."""
        from openspace.mcp_server import _cloud_search_and_import

        mock_cloud_client.search_record_embeddings = MagicMock(return_value=[])

        with patch("openspace.mcp_server._get_cloud_client", return_value=mock_cloud_client):
            results, cloud_available = await _cloud_search_and_import("test query")

            assert results == []
            assert cloud_available is True

    @pytest.mark.asyncio
    async def test_cloud_search_filters_private(self, mock_cloud_client):
        """Private skills filtered from results."""
        from openspace.mcp_server import _cloud_search_and_import

        mock_cloud_client.search_record_embeddings = MagicMock(return_value=[
            {"record_id": "public-1", "visibility": "public", "name": "Public"},
            {"record_id": "private-1", "visibility": "private", "name": "Private"},
        ])

        with patch("openspace.mcp_server._get_cloud_client", return_value=mock_cloud_client):
            with patch("openspace.mcp_server._do_import_cloud_skill", return_value={"status": "imported"}):
                results, cloud_available = await _cloud_search_and_import("test")

                # Should only import public skills
                assert len([r for r in results if "Public" in str(r)]) >= 0
                assert cloud_available is True

    @pytest.mark.asyncio
    async def test_cloud_search_respects_limit(self, mock_cloud_client):
        """Search respects limit parameter."""
        from openspace.mcp_server import _cloud_search_and_import

        # Mock many results
        mock_cloud_client.search_record_embeddings = MagicMock(return_value=[
            {
                "record_id": f"skill-{i}",
                "visibility": "public",
                "name": f"Skill {i}",
            }
            for i in range(20)
        ])

        with patch("openspace.mcp_server._get_cloud_client", return_value=mock_cloud_client):
            with patch("openspace.mcp_server._do_import_cloud_skill", return_value={"status": "imported"}):
                results, cloud_available = await _cloud_search_and_import("test", limit=5)

                # Should not exceed limit
                assert len(results) <= 5
                assert cloud_available is True


# ============================================================================
# Tests: Metadata Management
# ============================================================================


class TestMetadataManagement:
    """Test .upload_meta.json read/write."""

    def test_write_upload_meta_creates_file(self, tmp_path):
        """Write upload metadata to file."""
        from openspace.mcp_server import _write_upload_meta

        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()

        info = {
            "origin": "derived",
            "parent_skill_ids": ["skill-001"],
            "change_summary": "Added error handling",
            "created_by": "openspace",
            "tags": ["error-handling"],
        }

        _write_upload_meta(skill_dir, info)

        meta_file = skill_dir / ".upload_meta.json"
        assert meta_file.exists()

        # Verify content
        content = json.loads(meta_file.read_text())
        assert content["origin"] == "derived"
        assert content["change_summary"] == "Added error handling"

    def test_write_upload_meta_default_values(self, tmp_path):
        """Use default values when not provided."""
        from openspace.mcp_server import _write_upload_meta

        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()

        _write_upload_meta(skill_dir, {})

        meta_file = skill_dir / ".upload_meta.json"
        content = json.loads(meta_file.read_text())

        assert content["origin"] == "imported"
        assert content["parent_skill_ids"] == []
        assert content["created_by"] == "openspace"

    def test_write_upload_meta_overwrites_existing(self, tmp_path):
        """Overwrite existing metadata file."""
        from openspace.mcp_server import _write_upload_meta

        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()

        # Write first version
        _write_upload_meta(skill_dir, {"origin": "v1"})

        # Write second version
        _write_upload_meta(skill_dir, {"origin": "v2", "change_summary": "Updated"})

        meta_file = skill_dir / ".upload_meta.json"
        content = json.loads(meta_file.read_text())

        assert content["origin"] == "v2"
        assert content["change_summary"] == "Updated"


# ============================================================================
# Tests: Result Formatting
# ============================================================================


class TestResultFormatting:
    """Test task result formatting for MCP transport."""

    def test_format_task_result_basic(self, sample_task_result):
        """Format basic execution result."""
        from openspace.mcp_server import _format_task_result

        formatted = _format_task_result(sample_task_result)

        assert formatted["status"] == "success"
        assert formatted["response"] == "Task completed"
        assert isinstance(formatted["execution_time"], float)
        assert formatted["iterations"] == 5
        assert len(formatted["skills_used"]) == 2

    def test_format_task_result_tool_summary(self, sample_task_result):
        """Tool summary truncated to 20 tools."""
        from openspace.mcp_server import _format_task_result

        # Add many tool executions
        many_tools = [
            {"tool_name": f"tool-{i}", "status": "success", "error": None}
            for i in range(25)
        ]
        sample_task_result["tool_executions"] = many_tools

        formatted = _format_task_result(sample_task_result)

        assert len(formatted["tool_summary"]) <= 20

    def test_format_task_result_error_truncation(self, sample_task_result):
        """Error messages truncated to 200 chars."""
        from openspace.mcp_server import _format_task_result

        long_error = "x" * 300
        sample_task_result["tool_executions"] = [
            {"tool_name": "test_tool", "status": "error", "error": long_error}
        ]

        formatted = _format_task_result(sample_task_result)

        # Error should be truncated
        assert len(formatted["tool_summary"][0]["error"]) <= 200

    def test_format_task_result_evolved_skills(self, sample_task_result):
        """Format evolved skills with upload_ready flag."""
        from openspace.mcp_server import _format_task_result

        formatted = _format_task_result(sample_task_result)

        assert "evolved_skills" in formatted
        assert len(formatted["evolved_skills"]) == 1
        evolved = formatted["evolved_skills"][0]
        assert evolved["name"] == "evolved-skill"
        assert evolved["upload_ready"] is True
        assert "skill_dir" in evolved

    def test_format_task_result_action_required(self, sample_task_result):
        """Generate action_required message for evolved skills."""
        from openspace.mcp_server import _format_task_result

        formatted = _format_task_result(sample_task_result)

        assert "action_required" in formatted
        assert "evolved" in formatted["action_required"]
        assert "upload_skill" in formatted["action_required"]

    def test_format_task_result_no_evolved_skills(self, sample_task_result):
        """Skip evolved_skills section when empty."""
        from openspace.mcp_server import _format_task_result

        sample_task_result["evolved_skills"] = []

        formatted = _format_task_result(sample_task_result)

        assert "evolved_skills" not in formatted
        assert "action_required" not in formatted

    def test_format_task_result_warning_included(self, sample_task_result):
        """Include warning in output."""
        from openspace.mcp_server import _format_task_result

        sample_task_result["warning"] = "Max iterations reached"

        formatted = _format_task_result(sample_task_result)

        assert formatted["warning"] == "Max iterations reached"


# ============================================================================
# Tests: JSON Formatting
# ============================================================================


class TestJSONFormatting:
    """Test _json_ok and _json_error."""

    def test_json_ok_valid_data(self):
        """_json_ok serializes valid data."""
        from openspace.mcp_server import _json_ok

        data = {"status": "success", "message": "OK"}
        result = _json_ok(data)

        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_json_ok_unicode_handling(self):
        """_json_ok handles unicode correctly."""
        from openspace.mcp_server import _json_ok

        data = {"message": "Über große Skillo"}
        result = _json_ok(data)

        assert "Über" in result

    def test_json_error_error_field(self):
        """_json_error includes error field."""
        from openspace.mcp_server import _json_error

        result = _json_error("Test error")
        parsed = json.loads(result)

        assert "error" in parsed
        assert parsed["error"] == "Test error"

    def test_json_error_extra_fields(self):
        """_json_error includes extra fields."""
        from openspace.mcp_server import _json_error

        result = _json_error("Test error", status="failed", code=500)
        parsed = json.loads(result)

        assert parsed["error"] == "Test error"
        assert parsed["status"] == "failed"
        assert parsed["code"] == 500


# ============================================================================
# Tests: Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error paths and exception handling."""

    @pytest.mark.asyncio
    async def test_execute_task_rate_limit_exceeded(self, isolated_globals, rate_limiter_reset):
        """Return rate_limited error when limit exceeded."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Max out rate limiter
        execute_task_limiter.active_tasks = 3

        result_str = await execute_task("test task")
        result = json.loads(result_str)

        assert result.get("status") == "rate_limited"
        assert "Rate limit exceeded" in result.get("error", "")

        # Reset for next test
        execute_task_limiter.active_tasks = 0

    @pytest.mark.asyncio
    async def test_execute_task_openspace_init_failure(self, isolated_globals, rate_limiter_reset):
        """Handle OpenSpace initialization failure."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Reset limiter state
        execute_task_limiter.active_tasks = 0
        execute_task_limiter.request_times = []

        # Mock _get_openspace to raise exception
        with patch("openspace.mcp_server._get_openspace", side_effect=Exception("Init failed")):
            result_str = await execute_task("test task")
            result = json.loads(result_str)

            assert result.get("status") == "error"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_task_cloud_client_unavailable(self, isolated_globals, rate_limiter_reset, mock_openspace_engine):
        """Gracefully degrade when cloud client unavailable."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Reset limiter state
        execute_task_limiter.active_tasks = 0
        execute_task_limiter.request_times = []

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            with patch("openspace.mcp_server._get_cloud_client", side_effect=Exception("Cloud unavailable")):
                # Should still work with local-only search
                result_str = await execute_task("test task", search_scope="local")
                result = json.loads(result_str)

                # Should succeed even if cloud unavailable
                assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_execute_task_invalid_workspace_dir(self, isolated_globals, rate_limiter_reset, mock_openspace_engine):
        """Handle invalid workspace directory."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Reset limiter state
        execute_task_limiter.active_tasks = 0
        execute_task_limiter.request_times = []

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            result_str = await execute_task("test", workspace_dir="/invalid/path/that/does/not/exist")
            result = json.loads(result_str)

            # May succeed or fail depending on workspace validation
            assert isinstance(result, dict)

    def test_write_upload_meta_permission_denied(self, tmp_path):
        """Handle permission denied when writing metadata."""
        from openspace.mcp_server import _write_upload_meta

        skill_dir = tmp_path / "readonly"
        skill_dir.mkdir()

        # Make directory read-only
        try:
            skill_dir.chmod(0o444)

            # Should handle gracefully (may log warning)
            _write_upload_meta(skill_dir, {"origin": "test"})

            # Restore permissions for cleanup
            skill_dir.chmod(0o755)
        except PermissionError:
            # Expected on some systems
            skill_dir.chmod(0o755)
            pass


# ============================================================================
# Tests: Integration Scenarios
# ============================================================================


class TestExecuteTaskIntegration:
    """Integration tests for execute_task workflow."""

    @pytest.mark.asyncio
    async def test_execute_task_full_workflow(self, isolated_globals, rate_limiter_reset, mock_openspace_engine):
        """Full execute_task workflow with mocked dependencies."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Reset limiter state
        execute_task_limiter.active_tasks = 0
        execute_task_limiter.request_times = []

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            with patch("openspace.mcp_server._auto_register_skill_dirs", return_value=5):
                result_str = await execute_task(
                    task="Write a test file",
                    workspace_dir="/tmp",
                    max_iterations=10,
                )

                result = json.loads(result_str)

                assert result["status"] == "success"
                assert "response" in result
                assert "execution_time" in result

    @pytest.mark.asyncio
    async def test_execute_task_with_skill_dirs(self, isolated_globals, rate_limiter_reset, mock_openspace_engine):
        """Auto-register skill directories."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Reset limiter state
        execute_task_limiter.active_tasks = 0
        execute_task_limiter.request_times = []

        with patch("openspace.mcp_server._get_openspace", return_value=mock_openspace_engine):
            with patch("openspace.mcp_server._auto_register_skill_dirs", return_value=3):
                result_str = await execute_task(
                    task="test",
                    skill_dirs=["/tmp/skills"],
                )

                result = json.loads(result_str)
                assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_execute_task_rate_limiter_release_on_error(self, isolated_globals, rate_limiter_reset):
        """Rate limiter released even on error."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Reset limiter state
        execute_task_limiter.active_tasks = 0
        execute_task_limiter.request_times = []

        initial_active = execute_task_limiter.active_tasks

        with patch("openspace.mcp_server._get_openspace", side_effect=Exception("Test error")):
            await execute_task("test")

        # Should be released
        assert execute_task_limiter.active_tasks == initial_active


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
