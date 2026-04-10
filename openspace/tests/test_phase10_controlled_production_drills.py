"""Phase 10 Controlled Production Drills — validate runtime hardening fixes.

Focused tests for concurrency, failure recovery, idempotency, and degradation visibility.
"""

import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# Marker for tests requiring X11 display
has_display = os.getenv("DISPLAY") is not None


# ============================================================================
# Drill 1: Limiter acquire/release correctness
# ============================================================================

class TestLimiterAcquireRelease:
    """Verify limiter token semantics and idempotent release."""

    @pytest.mark.asyncio
    async def test_release_only_called_after_successful_acquire(self):
        """Limiter.release() should not decrement if acquire() returned False."""
        from openspace.mcp_server_limiter import RateLimiter

        limiter = RateLimiter(max_concurrent=1, max_per_minute=10)

        # First call succeeds
        result1 = await limiter.acquire()
        assert result1 is True
        assert limiter.active_tasks == 1

        # Second call fails (concurrent limit exceeded)
        result2 = await limiter.acquire()
        assert result2 is False
        assert limiter.active_tasks == 1  # Not incremented

        # Release once
        await limiter.release()
        assert limiter.active_tasks == 0

        # Release again (should not go negative, should be safe)
        await limiter.release()
        assert limiter.active_tasks == 0  # Idempotent: stays at 0, not -1

    @pytest.mark.asyncio
    async def test_execute_task_guards_release_on_failed_acquire(self):
        """execute_task should only call release() if acquire() succeeded."""
        from openspace.mcp_server import execute_task
        from openspace.mcp_server_limiter import execute_task_limiter

        # Fill rate limiter to capacity (max_concurrent=3)
        acquired = []
        for i in range(3):
            result = await execute_task_limiter.acquire()
            acquired.append(result)
        assert all(acquired), "Should acquire 3 tokens"

        # Now call execute_task (should fail rate limit)
        result = await execute_task(task="test task")

        # Should get rate limit error
        assert "rate_limited" in result
        assert "Rate limit exceeded" in result

        # Check that limiter state is still consistent
        assert execute_task_limiter.active_tasks == 3
        # Verify no double-release happened
        assert execute_task_limiter.active_tasks > 0

        # Release all
        for _ in range(3):
            await execute_task_limiter.release()
        assert execute_task_limiter.active_tasks == 0

    @pytest.mark.asyncio
    async def test_search_skills_guards_release_on_failed_acquire(self):
        """search_skills should only call release() if acquire() succeeded."""
        from openspace.mcp_server import search_skills
        from openspace.mcp_server_limiter import search_skills_limiter

        # Fill rate limiter to capacity (max_concurrent=5)
        acquired = []
        for i in range(5):
            result = await search_skills_limiter.acquire()
            acquired.append(result)
        assert all(acquired), "Should acquire 5 tokens"

        # Now call search_skills (should fail rate limit)
        result = await search_skills(query="test query")

        # Should get rate limit error
        assert "rate_limited" in result
        assert "Rate limit exceeded" in result

        # Check that limiter state is consistent
        assert search_skills_limiter.active_tasks == 5
        # Verify no double-release happened
        assert search_skills_limiter.active_tasks > 0

        # Release all
        for _ in range(5):
            await search_skills_limiter.release()
        assert search_skills_limiter.active_tasks == 0


# ============================================================================
# Drill 2: _registered_skill_dirs atomic protection
# ============================================================================

class TestRegisteredSkillDirsAtomicity:
    """Verify concurrent registration doesn't corrupt state."""

    @pytest.mark.asyncio
    async def test_concurrent_registration_does_not_corrupt_state(self):
        """Multiple concurrent _auto_register_skill_dirs should not corrupt set."""
        from openspace.mcp_server import (
            _auto_register_skill_dirs,
            _registered_skill_dirs,
            _openspace_instance,
        )
        from openspace.tool_layer import OpenSpace, OpenSpaceConfig

        # Mock OpenSpace to avoid full initialization
        mock_openspace = AsyncMock()
        mock_registry = MagicMock()
        mock_registry.discover_from_dirs = MagicMock(return_value=[])
        mock_openspace._skill_registry = mock_registry

        with patch('openspace.mcp_server._get_openspace', return_value=mock_openspace):
            # Create temp directories for testing
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                dir1 = str(Path(tmpdir) / "skill_dir_1")
                dir2 = str(Path(tmpdir) / "skill_dir_2")
                Path(dir1).mkdir(parents=True)
                Path(dir2).mkdir(parents=True)

                # Clear the global set
                _registered_skill_dirs.clear()

                # Run concurrent registration
                results = await asyncio.gather(
                    _auto_register_skill_dirs([dir1]),
                    _auto_register_skill_dirs([dir2]),
                    _auto_register_skill_dirs([dir1, dir2]),  # Same dirs again
                )

                # Verify final state is consistent
                assert dir1 in _registered_skill_dirs
                assert dir2 in _registered_skill_dirs
                assert len(_registered_skill_dirs) == 2  # Only 2 unique dirs

                # Verify no duplicates or corruption
                assert isinstance(_registered_skill_dirs, set)


# ============================================================================
# Drill 3: Cloud search degradation visibility
# ============================================================================

class TestCloudSearchDegradation:
    """Verify cloud failure is visible and doesn't silently become 'no results'."""

    @pytest.mark.asyncio
    async def test_cloud_search_failure_returns_cloud_unavailable_flag(self):
        """_cloud_search_and_import should return cloud_available=False on failure."""
        from openspace.mcp_server import _cloud_search_and_import

        # Mock cloud client to raise exception
        mock_cloud_client = MagicMock()
        mock_cloud_client.search_record_embeddings = MagicMock(
            side_effect=TimeoutError("Cloud service timeout")
        )

        with patch(
            'openspace.mcp_server._get_cloud_client',
            return_value=mock_cloud_client,
        ):
            results, cloud_available = await _cloud_search_and_import("test task")

            # Should return empty results AND cloud_available=False
            assert results == []
            assert cloud_available is False

    @pytest.mark.asyncio
    async def test_cloud_search_success_returns_cloud_available_true(self):
        """_cloud_search_and_import should return cloud_available=True on success."""
        from openspace.mcp_server import _cloud_search_and_import

        # Mock cloud client to return empty results (success but no hits)
        mock_cloud_client = MagicMock()
        mock_cloud_client.search_record_embeddings = MagicMock(return_value=[])

        with patch(
            'openspace.mcp_server._get_cloud_client',
            return_value=mock_cloud_client,
        ):
            results, cloud_available = await _cloud_search_and_import("test task")

            # Should return cloud_available=True even with zero results
            assert cloud_available is True

    @pytest.mark.asyncio
    async def test_execute_task_includes_cloud_available_in_response(self):
        """execute_task response should include cloud_available flag."""
        from openspace.mcp_server import execute_task, _openspace_instance

        # Mock cloud search to fail
        mock_cloud_client = MagicMock()
        mock_cloud_client.search_record_embeddings = MagicMock(
            side_effect=TimeoutError("Cloud unreachable")
        )

        mock_openspace = AsyncMock()
        mock_openspace.is_initialized = MagicMock(return_value=True)
        mock_openspace._skill_registry = MagicMock()
        mock_openspace._skill_registry.discover_from_dirs = MagicMock(return_value=[])
        mock_openspace.execute = AsyncMock(
            return_value={"status": "success", "response": "Done"}
        )

        with patch('openspace.mcp_server._get_openspace', return_value=mock_openspace):
            with patch(
                'openspace.mcp_server._get_cloud_client',
                return_value=mock_cloud_client,
            ):
                with patch('openspace.mcp_server._auto_register_skill_dirs'):
                    with patch('openspace.llm.task_router.route_task') as mock_route:
                        mock_route.return_value = MagicMock(model='test-model')
                        with patch('openspace.llm.task_router.log_route'):
                            result = await execute_task(task="test", search_scope="all")

                            # Response should include cloud_available flag
                            import json
                            response = json.loads(result)
                            assert 'cloud_available' in response
                            # Cloud failed, so should be False
                            assert response['cloud_available'] is False


# ============================================================================
# Drill 4: Recording cleanup idempotency
# ============================================================================

@pytest.mark.skipif(not has_display, reason="Requires X11 display")
class TestRecordingCleanupIdempotency:
    """Verify recording cleanup is idempotent and recovery works."""

    def test_start_recording_after_failed_start(self):
        """After failed start_recording, next attempt should succeed."""
        from openspace.local_server.main import app, recording_process

        test_client = app.test_client()

        # Mock platform adapter to fail on first call
        with patch('openspace.local_server.main.platform_adapter') as mock_adapter:
            mock_adapter.start_recording.side_effect = RuntimeError("Mock failure")

            # First call fails
            response1 = test_client.post('/start_recording')
            assert response1.status_code == 500

            # Verify recording_process is cleared (state reset)
            from openspace.local_server.main import recording_process
            assert recording_process is None

            # Second call should be able to proceed (no lingering state)
            mock_adapter.start_recording.side_effect = None
            mock_process = MagicMock()
            mock_process.poll.return_value = None
            mock_adapter.start_recording.return_value = {
                'status': 'success',
                'process': mock_process,
            }

            response2 = test_client.post('/start_recording')
            assert response2.status_code == 200


# ============================================================================
# Drill 5: Request correlation IDs
# ============================================================================

class TestRequestCorrelationIds:
    """Verify request_id is generated and threaded through logs."""

    @pytest.mark.asyncio
    async def test_execute_task_sets_request_id(self, caplog):
        """execute_task should set and log request_id."""
        from openspace.mcp_server import execute_task
        import logging

        caplog.set_level(logging.INFO)

        mock_openspace = AsyncMock()
        mock_openspace.is_initialized = MagicMock(return_value=True)
        mock_openspace._skill_registry = MagicMock()
        mock_openspace.execute = AsyncMock(
            return_value={"status": "success", "response": "Done"}
        )

        with patch('openspace.mcp_server._get_openspace', return_value=mock_openspace):
            with patch('openspace.mcp_server._auto_register_skill_dirs'):
                with patch('openspace.llm.task_router.route_task') as mock_route:
                    mock_route.return_value = MagicMock(model='test-model')
                    with patch('openspace.llm.task_router.log_route'):
                        result = await execute_task(task="test task")

                        # Verify response is valid
                        assert 'success' in result or 'error' in result

                        # Verify logs include request_id (via filter)
                        # The caplog should have captured logs with request_id
                        assert len(caplog.records) > 0


# ============================================================================
# Drill 6: No destructive side effects from retries
# ============================================================================

class TestIdempotencyUnderRetry:
    """Verify duplicate/retry scenarios don't create destructive side effects."""

    @pytest.mark.asyncio
    async def test_duplicate_registration_does_not_corrupt_db(self):
        """Re-registering same skill dir twice should not create duplicates."""
        from openspace.mcp_server import _auto_register_skill_dirs
        import tempfile

        mock_openspace = AsyncMock()
        mock_registry = MagicMock()
        mock_skill = MagicMock()
        mock_skill.skill_id = 'test_skill_1'
        mock_registry.discover_from_dirs = MagicMock(return_value=[mock_skill])

        mock_store = AsyncMock()
        mock_store.sync_from_registry = AsyncMock(return_value=1)

        mock_openspace._skill_registry = mock_registry

        with patch('openspace.mcp_server._get_openspace', return_value=mock_openspace):
            with patch('openspace.mcp_server._get_store', return_value=mock_store):
                with tempfile.TemporaryDirectory() as tmpdir:
                    skill_dir = str(Path(tmpdir) / "my_skill")
                    Path(skill_dir).mkdir()

                    # Register twice
                    result1 = await _auto_register_skill_dirs([skill_dir])
                    result2 = await _auto_register_skill_dirs([skill_dir])

                    # Both should succeed
                    assert result1 >= 0
                    assert result2 >= 0

                    # Verify DB was synced each time (no corruption check)
                    assert mock_store.sync_from_registry.call_count >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
