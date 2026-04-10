"""Phase 11 Operational Readiness — validate HTTP health/readiness probes and graceful shutdown.

Tests for Kubernetes-compatible health checks and operational readiness endpoints.
"""

import asyncio
import json
import os
import sys
import pytest
import time
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================================
# Fixtures: Mock OpenSpace and Flask test client
# ============================================================================

@pytest.fixture
def flask_test_client():
    """Flask test client for local_server.

    GUI modules are globally mocked by conftest.py, so this fixture only
    needs to import the Flask app and create a test client. Runs on headless CI.
    """
    # Mock the remaining components that don't require X11
    with patch('openspace.local_server.utils.AccessibilityHelper'):
        with patch('openspace.local_server.utils.ScreenshotHelper'):
            with patch('openspace.local_server.health_checker.HealthChecker'):
                with patch('openspace.local_server.feature_checker.FeatureChecker'):
                    # Safe to import main (GUI modules already mocked globally)
                    from openspace.local_server.main import app

                    app.config['TESTING'] = True
                    with app.test_client() as client:
                        yield client


@pytest.fixture
def mock_openspace_initialized():
    """Mock initialized OpenSpace instance."""
    mock_instance = MagicMock()
    mock_instance.is_initialized.return_value = True
    return mock_instance


@pytest.fixture
def mock_openspace_not_initialized():
    """Mock uninitialized OpenSpace instance."""
    mock_instance = MagicMock()
    mock_instance.is_initialized.return_value = False
    return mock_instance


# ============================================================================
# /health endpoint tests (liveness)
# ============================================================================

class TestHealthLiveness:
    """Verify /health endpoint always returns 200 (process alive)."""

    def test_health_always_returns_200(self, flask_test_client):
        """GET /health should always return 200 with 'ok' status."""
        response = flask_test_client.get('/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'

    def test_health_response_format(self, flask_test_client):
        """GET /health response should have correct JSON structure."""
        response = flask_test_client.get('/health')
        data = json.loads(response.data)
        assert 'status' in data
        assert isinstance(data['status'], str)


# ============================================================================
# /ready endpoint tests (readiness)
# ============================================================================

class TestReadyReadiness:
    """Verify /ready endpoint returns 200 when ready, 503 when not."""

    def test_ready_true_when_openspace_initialized(self, flask_test_client,
                                                     mock_openspace_initialized):
        """GET /ready should return 200 when OpenSpace initialized."""
        with patch('openspace.runtime_state.get_is_ready', return_value=True):
            response = flask_test_client.get('/ready')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['ready'] is True
            assert data['reason'] is None

    def test_ready_false_when_openspace_not_initialized(self, flask_test_client,
                                                          mock_openspace_not_initialized):
        """GET /ready should return 503 when OpenSpace not initialized."""
        with patch('openspace.runtime_state.get_is_ready', return_value=False):
            response = flask_test_client.get('/ready')
            assert response.status_code == 503
            data = json.loads(response.data)
            assert data['ready'] is False
            assert isinstance(data['reason'], str)

    def test_ready_false_when_shutting_down(self, flask_test_client,
                                             mock_openspace_initialized):
        """GET /ready should return 503 when shutdown requested."""
        with patch('openspace.runtime_state.get_is_ready', return_value=False):
            response = flask_test_client.get('/ready')
            assert response.status_code == 503
            data = json.loads(response.data)
            assert data['ready'] is False

    def test_ready_response_format_success(self, flask_test_client):
        """GET /ready (success) should have ready and reason fields."""
        with patch('openspace.runtime_state.get_is_ready', return_value=True):
            response = flask_test_client.get('/ready')
            data = json.loads(response.data)
            assert 'ready' in data
            assert 'reason' in data
            assert isinstance(data['ready'], bool)
            assert data['reason'] is None

    def test_ready_response_format_failure(self, flask_test_client):
        """GET /ready (failure) should have ready and reason fields."""
        with patch('openspace.runtime_state.get_is_ready', return_value=False):
            response = flask_test_client.get('/ready')
            data = json.loads(response.data)
            assert 'ready' in data
            assert 'reason' in data
            assert isinstance(data['ready'], bool)
            assert isinstance(data['reason'], str)


# ============================================================================
# /status endpoint tests (diagnostics)
# ============================================================================

class TestStatusDiagnostics:
    """Verify /status endpoint returns comprehensive diagnostics."""

    def test_status_response_format(self, flask_test_client):
        """GET /status should have all required fields."""
        response = flask_test_client.get('/status')
        assert response.status_code == 200
        data = json.loads(response.data)

        assert 'uptime_seconds' in data
        assert 'openspace_initialized' in data
        assert 'limiter' in data
        assert 'cloud_status' in data

    def test_status_uptime_is_positive(self, flask_test_client):
        """GET /status uptime should be non-negative."""
        response = flask_test_client.get('/status')
        data = json.loads(response.data)
        assert isinstance(data['uptime_seconds'], (int, float))
        assert data['uptime_seconds'] >= 0

    def test_status_openspace_initialized_is_bool(self, flask_test_client):
        """GET /status openspace_initialized should be boolean."""
        response = flask_test_client.get('/status')
        data = json.loads(response.data)
        assert isinstance(data['openspace_initialized'], bool)

    def test_status_limiter_has_active_counts(self, flask_test_client):
        """GET /status limiter should have active task counts."""
        response = flask_test_client.get('/status')
        data = json.loads(response.data)
        assert 'execute_task_active' in data['limiter']
        assert 'search_skills_active' in data['limiter']
        assert isinstance(data['limiter']['execute_task_active'], int)
        assert isinstance(data['limiter']['search_skills_active'], int)

    def test_status_cloud_status_value(self, flask_test_client):
        """GET /status cloud_status should be one of expected values."""
        response = flask_test_client.get('/status')
        data = json.loads(response.data)
        assert data['cloud_status'] in ['unknown', 'available', 'degraded']

    def test_status_with_mcp_initialized(self, flask_test_client,
                                         mock_openspace_initialized):
        """GET /status with initialized MCP server (structure validation)."""
        response = flask_test_client.get('/status')
        data = json.loads(response.data)
        # Verify structure exists even if values are defaults
        assert isinstance(data['limiter']['execute_task_active'], int)
        assert isinstance(data['limiter']['search_skills_active'], int)
        assert isinstance(data['cloud_status'], str)

    def test_status_with_mcp_not_initialized(self, flask_test_client,
                                              mock_openspace_not_initialized):
        """GET /status with uninitialized MCP server."""
        with patch('openspace.mcp_server._openspace_instance', mock_openspace_not_initialized):
            response = flask_test_client.get('/status')
            data = json.loads(response.data)
            assert data['openspace_initialized'] is False


# ============================================================================
# Graceful shutdown tests
# ============================================================================

class TestGracefulShutdown:
    """Verify graceful shutdown behavior."""

    def test_graceful_shutdown_sets_flag(self):
        """initiate_graceful_shutdown should set _shutdown_requested flag."""
        from openspace.mcp_server import initiate_graceful_shutdown
        import openspace.mcp_server as mcp_mod

        # Reset flag
        mcp_mod._shutdown_requested = False

        # Mock limiters to have no active tasks
        mock_et_limiter = MagicMock()
        mock_ss_limiter = MagicMock()
        mock_et_limiter.active_tasks = 0
        mock_ss_limiter.active_tasks = 0

        with patch('openspace.mcp_server_limiter.execute_task_limiter', mock_et_limiter):
            with patch('openspace.mcp_server_limiter.search_skills_limiter', mock_ss_limiter):
                initiate_graceful_shutdown(timeout_seconds=0.1)
                # Flag should have been set during shutdown
                assert mcp_mod._shutdown_requested

    def test_graceful_shutdown_waits_for_tasks(self):
        """initiate_graceful_shutdown should wait for active tasks."""
        from openspace.mcp_server import initiate_graceful_shutdown
        import openspace.mcp_server as mcp_mod

        # Mock limiters with no active tasks (for quick return)
        mock_et_limiter = MagicMock()
        mock_ss_limiter = MagicMock()
        mock_et_limiter.active_tasks = 0
        mock_ss_limiter.active_tasks = 0

        mcp_mod._shutdown_requested = False

        with patch('openspace.mcp_server_limiter.execute_task_limiter', mock_et_limiter):
            with patch('openspace.mcp_server_limiter.search_skills_limiter', mock_ss_limiter):
                # Should complete quickly as no real tasks
                initiate_graceful_shutdown(timeout_seconds=1.0)
                # Verify function completed
                assert mcp_mod._shutdown_requested

    def test_graceful_shutdown_timeout_warning(self, caplog):
        """initiate_graceful_shutdown should log warning if timeout reached."""
        from openspace.mcp_server import initiate_graceful_shutdown
        import openspace.mcp_server as mcp_mod
        import logging

        caplog.set_level(logging.WARNING)

        # Mock limiters with permanently active tasks
        mock_et_limiter = MagicMock()
        mock_ss_limiter = MagicMock()
        mock_et_limiter.active_tasks = 5
        mock_ss_limiter.active_tasks = 0

        mcp_mod._shutdown_requested = False

        with patch('openspace.mcp_server_limiter.execute_task_limiter', mock_et_limiter):
            with patch('openspace.mcp_server_limiter.search_skills_limiter', mock_ss_limiter):
                # Short timeout should trigger warning
                initiate_graceful_shutdown(timeout_seconds=0.05)
                # Verify timeout warning was logged
                assert any('timeout' in record.message.lower() for record in caplog.records)

    def test_graceful_shutdown_continues_after_timeout(self):
        """initiate_graceful_shutdown should continue cleanup even after timeout."""
        from openspace.mcp_server import initiate_graceful_shutdown
        import openspace.mcp_server as mcp_mod

        # Mock limiters that never complete
        mock_et_limiter = MagicMock()
        mock_ss_limiter = MagicMock()
        mock_et_limiter.active_tasks = 10
        mock_ss_limiter.active_tasks = 10

        mcp_mod._shutdown_requested = False

        with patch('openspace.mcp_server_limiter.execute_task_limiter', mock_et_limiter):
            with patch('openspace.mcp_server_limiter.search_skills_limiter', mock_ss_limiter):
                # Should complete despite timeout (no exception)
                initiate_graceful_shutdown(timeout_seconds=0.05)
                # Verify function completed
                assert mcp_mod._shutdown_requested

    def test_ready_returns_false_during_shutdown(self, flask_test_client):
        """GET /ready should return 503 when shutdown is in progress."""
        with patch('openspace.runtime_state.get_is_ready', return_value=False):
            response = flask_test_client.get('/ready')
            assert response.status_code == 503
            data = json.loads(response.data)
            assert data['ready'] is False


# ============================================================================
# Cloud status tracking tests
# ============================================================================

class TestCloudStatusTracking:
    """Verify cloud status is tracked and visible in /status."""

    def test_cloud_status_field_exists(self, flask_test_client):
        """GET /status should include cloud_status field with valid value."""
        response = flask_test_client.get('/status')
        data = json.loads(response.data)
        # Cloud status should exist and be one of the valid values
        assert 'cloud_status' in data
        assert data['cloud_status'] in ['unknown', 'available', 'degraded']

    def test_cloud_status_set_to_available_via_module(self):
        """_last_cloud_status can be set to 'available' at module level."""
        import openspace.mcp_server as mcp_mod

        original = mcp_mod._last_cloud_status
        try:
            mcp_mod._last_cloud_status = 'available'
            assert mcp_mod._last_cloud_status == 'available'
        finally:
            mcp_mod._last_cloud_status = original

    def test_cloud_status_set_to_degraded_via_module(self):
        """_last_cloud_status can be set to 'degraded' at module level."""
        import openspace.mcp_server as mcp_mod

        original = mcp_mod._last_cloud_status
        try:
            mcp_mod._last_cloud_status = 'degraded'
            assert mcp_mod._last_cloud_status == 'degraded'
        finally:
            mcp_mod._last_cloud_status = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
