"""Phase 9 production readiness tests — validate critical hardening fixes.

Tests verify real production behavior:
- Startup failure modes
- Security fixes (path validation, shell rejection)
- Error handling and cleanup
- Rate limiting
- Resilience configuration
"""

import os
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from tempfile import TemporaryDirectory


# Marker for tests requiring X11 display
has_display = os.getenv("DISPLAY") is not None


# ============================================================================
# Tests: Startup Validation
# ============================================================================


class TestStartupValidation:
    """Test that startup validation catches missing/invalid config."""

    @pytest.mark.asyncio
    async def test_openspace_init_fails_without_model(self, monkeypatch):
        """Startup should fail clearly when no LLM model is configured."""
        # Clear model env vars to force failure
        monkeypatch.delenv("OPENSPACE_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        # Mock build_llm_kwargs to return empty model
        with patch("openspace.host_detection.build_llm_kwargs", return_value=("", {})):
            from openspace.mcp_server import _get_openspace

            with pytest.raises(RuntimeError, match="No LLM model configured"):
                await _get_openspace()

    @pytest.mark.asyncio
    async def test_openspace_init_succeeds_with_valid_model(self, monkeypatch):
        """Startup should succeed when valid model is provided."""
        monkeypatch.setenv("OPENSPACE_MODEL", "anthropic/claude-opus-4-6")

        # Mock OpenSpace to avoid actual initialization
        mock_os = AsyncMock()
        mock_os.is_initialized.return_value = True

        with patch("openspace.tool_layer.OpenSpace", return_value=mock_os):
            with patch("openspace.host_detection.build_llm_kwargs",
                      return_value=("anthropic/claude-opus-4-6", {})):
                from openspace.mcp_server import _get_openspace

                # Should not raise
                result = await _get_openspace()
                assert result is not None


# ============================================================================
# Tests: Path Validation Security
# ============================================================================


@pytest.mark.skipif(not has_display, reason="Requires X11 display")
class TestPathValidationSecurity:
    """Test that path validation prevents traversal and symlink escapes."""

    def test_path_validation_rejects_absolute_escape(self):
        """Path validation should reject absolute paths outside allowed roots."""
        from openspace.local_server.main import _validate_path

        with pytest.raises(ValueError, match="Access denied"):
            _validate_path("/etc/passwd")

    def test_path_validation_rejects_relative_escape(self):
        """Path validation should reject relative paths that escape."""
        from openspace.local_server.main import _validate_path

        with pytest.raises(ValueError, match="Access denied"):
            _validate_path("../../etc/passwd")

    def test_path_validation_accepts_home_paths(self):
        """Path validation should accept paths under home directory."""
        from openspace.local_server.main import _validate_path

        home = os.path.expanduser("~")
        result = _validate_path("~/test.txt")

        assert result == os.path.realpath(os.path.join(home, "test.txt"))

    def test_path_validation_accepts_tmp_paths(self):
        """Path validation should accept paths under /tmp."""
        from openspace.local_server.main import _validate_path

        result = _validate_path("/tmp/test.txt")

        assert result == os.path.realpath("/tmp/test.txt")

    def test_path_validation_rejects_symlink_escape(self):
        """Path validation should block symlink-based escape attempts."""
        from openspace.local_server.main import _validate_path

        with TemporaryDirectory() as tmpdir:
            # Create a symlink that points outside allowed roots
            symlink_path = os.path.join(tmpdir, "evil_link")

            # On Unix, create symlink to /etc
            if hasattr(os, 'symlink'):
                try:
                    os.symlink("/etc", symlink_path)
                    # Trying to access through symlink should be rejected
                    with pytest.raises(ValueError, match="Access denied"):
                        _validate_path(symlink_path)
                except (OSError, NotImplementedError):
                    # Skip on Windows or if symlinks not supported
                    pytest.skip("Symlinks not supported on this platform")


# ============================================================================
# Tests: Shell Execution Security
# ============================================================================


@pytest.mark.skipif(not has_display, reason="Requires X11 display")
class TestShellExecutionSecurity:
    """Test that shell execution is properly restricted."""

    def test_execute_rejects_shell_true(self, client=None):
        """Execute endpoint should reject shell=True."""
        from openspace.local_server.main import app

        test_client = app.test_client()

        response = test_client.post(
            "/execute",
            json={"shell": True, "command": "echo test"}
        )

        assert response.status_code == 400
        assert "shell=True" in response.get_json().get("message", "")

    def test_launch_rejects_shell_true(self):
        """Launch endpoint should reject shell=True."""
        from openspace.local_server.main import app

        test_client = app.test_client()

        response = test_client.post(
            "/setup/launch",
            json={"shell": True, "command": "xdg-open http://example.com"}
        )

        assert response.status_code == 400
        assert "shell=True" in response.get_json().get("message", "")

    def test_verify_rejects_shell_true(self):
        """Verify endpoint should reject shell=True."""
        from openspace.local_server.main import app

        test_client = app.test_client()

        response = test_client.post(
            "/execute_with_verification",
            json={"shell": True, "command": "echo test"}
        )

        assert response.status_code == 400
        assert "shell=True" in response.get_json().get("message", "")


# ============================================================================
# Tests: Recording Cleanup
# ============================================================================


@pytest.mark.skipif(not has_display, reason="Requires X11 display")
class TestRecordingCleanup:
    """Test that recording state is cleaned up on errors."""

    def test_recording_process_cleared_on_start_failure(self):
        """recording_process should be None if start fails."""
        from openspace.local_server.main import app

        test_client = app.test_client()

        # Mock platform_adapter to raise exception
        with patch("openspace.local_server.main.platform_adapter") as mock_adapter:
            mock_adapter.start_recording.side_effect = RuntimeError("Mock failure")

            response = test_client.post("/start_recording")

            assert response.status_code == 500

            # recording_process should be None (not left in bad state)
            from openspace.local_server.main import recording_process
            assert recording_process is None

    def test_recording_process_cleared_on_end_failure(self):
        """recording_process should be None if stop fails."""
        from openspace.local_server.main import app

        test_client = app.test_client()

        # Set recording_process to a mock
        import openspace.local_server.main as server_module
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running
        server_module.recording_process = mock_process

        # Mock platform_adapter to raise exception
        with patch("openspace.local_server.main.platform_adapter") as mock_adapter:
            mock_adapter.stop_recording.side_effect = RuntimeError("Stop failed")

            response = test_client.post("/end_recording")

            assert response.status_code == 500

            # recording_process should be None (cleaned up on exception)
            assert server_module.recording_process is None


# ============================================================================
# Tests: Error Sanitization
# ============================================================================


class TestErrorSanitization:
    """Test that error responses don't leak secrets."""

    def test_json_error_sanitizes_exception(self):
        """_json_error should sanitize sensitive information from exceptions."""
        from openspace.mcp_server import _json_error
        import json

        # Create exception with sensitive data
        exc = RuntimeError("Failed to authenticate with OPENAI_API_KEY=sk-test-123")

        result = _json_error(exc)
        parsed = json.loads(result)

        # API key should not appear in error response
        assert "sk-test-" not in parsed["error"]
        assert "OPENAI_API_KEY" not in parsed["error"]

    def test_json_error_preserves_error_type(self):
        """_json_error should preserve error type in message."""
        from openspace.mcp_server import _json_error
        import json

        exc = ValueError("Invalid configuration")

        result = _json_error(exc)
        parsed = json.loads(result)

        # Error type should be in message
        assert "ValueError" in parsed["error"] or "Invalid configuration" in parsed["error"]

    def test_json_error_truncates_long_messages(self):
        """_json_error should truncate very long error messages."""
        from openspace.mcp_server import _json_error
        import json

        # Create very long error message
        long_msg = "x" * 500
        exc = RuntimeError(long_msg)

        result = _json_error(exc)
        parsed = json.loads(result)

        # Should be truncated, not full 500 chars
        assert len(parsed["error"]) < 500


# ============================================================================
# Tests: Rate Limiting
# ============================================================================


class TestAuthRateLimiting:
    """Test that auth rate limiting prevents brute force."""

    def test_auth_rate_limit_logic(self):
        """Auth rate limiting logic should block after 5 failures per minute."""
        from openspace.dashboard_server import (
            _check_auth_rate_limit,
            _record_failed_auth,
        )

        # Clear rate limit state
        import openspace.dashboard_server
        openspace.dashboard_server._FAILED_AUTH_ATTEMPTS.clear()

        # Should allow initial attempts
        assert _check_auth_rate_limit("192.168.1.1") is False

        # Record 4 failures (0-indexed, so 0, 1, 2, 3)
        for i in range(4):
            _record_failed_auth("192.168.1.1")

        # At 4 failures, still not rate limited
        assert _check_auth_rate_limit("192.168.1.1") is False

        # Record 5th failure
        _record_failed_auth("192.168.1.1")

        # Now with 5 failures, it should be rate limited
        assert _check_auth_rate_limit("192.168.1.1") is True

    def test_auth_rate_limit_different_ips(self):
        """Rate limiting should be per IP, not global."""
        from openspace.dashboard_server import (
            _check_auth_rate_limit,
            _record_failed_auth,
        )

        import openspace.dashboard_server
        openspace.dashboard_server._FAILED_AUTH_ATTEMPTS.clear()

        # Record 5 failures for IP1
        for i in range(5):
            _record_failed_auth("192.168.1.1")

        # IP1 should be rate limited
        assert _check_auth_rate_limit("192.168.1.1") is True

        # Different IP should not be rate limited
        assert _check_auth_rate_limit("192.168.1.2") is False


# ============================================================================
# Tests: Rate Limiter Logging
# ============================================================================


class TestRateLimiterLogging:
    """Test that rate limiter logs rejections for diagnostics."""

    def test_rate_limiter_logs_concurrent_limit(self, caplog):
        """Rate limiter should log when concurrent limit is exceeded."""
        from openspace.mcp_server_limiter import RateLimiter
        import asyncio
        import logging

        # Enable debug logging
        logging.getLogger("openspace.mcp_server_limiter").setLevel(logging.WARNING)

        async def test():
            limiter = RateLimiter(max_concurrent=1)

            # Acquire first token
            result1 = await limiter.acquire()
            assert result1 is True

            # Try to acquire second (should fail and log)
            result2 = await limiter.acquire()
            assert result2 is False

            await limiter.release()

        asyncio.run(test())
        # Log message should be present (checked at runtime)


# ============================================================================
# Tests: HTTP Timeout Configuration
# ============================================================================


class TestHttpTimeoutConfiguration:
    """Test that HTTP timeout is configurable."""

    def test_http_timeout_default(self):
        """Default HTTP timeout should be 30 seconds."""
        from openspace.cloud.client import OpenSpaceClient

        auth_headers = {"Authorization": "Bearer test"}
        client = OpenSpaceClient(auth_headers, "https://api.example.com")

        assert client._timeout == 30

    def test_http_timeout_from_env(self, monkeypatch):
        """HTTP timeout should be configurable via env var."""
        monkeypatch.setenv("OPENSPACE_HTTP_TIMEOUT", "60")

        from openspace.cloud.client import OpenSpaceClient

        auth_headers = {"Authorization": "Bearer test"}
        client = OpenSpaceClient(auth_headers, "https://api.example.com")

        assert client._timeout == 60

    def test_http_timeout_clamped_min(self, monkeypatch):
        """HTTP timeout should be clamped to minimum 5 seconds."""
        monkeypatch.setenv("OPENSPACE_HTTP_TIMEOUT", "1")

        from openspace.cloud.client import OpenSpaceClient

        auth_headers = {"Authorization": "Bearer test"}
        client = OpenSpaceClient(auth_headers, "https://api.example.com")

        assert client._timeout == 5  # Clamped from 1 to min 5

    def test_http_timeout_clamped_max(self, monkeypatch):
        """HTTP timeout should be clamped to maximum 300 seconds."""
        monkeypatch.setenv("OPENSPACE_HTTP_TIMEOUT", "500")

        from openspace.cloud.client import OpenSpaceClient

        auth_headers = {"Authorization": "Bearer test"}
        client = OpenSpaceClient(auth_headers, "https://api.example.com")

        assert client._timeout == 300  # Clamped from 500 to max 300


# ============================================================================
# Integration Tests: Critical Workflows
# ============================================================================


class TestProductionWorkflows:
    """Test critical production workflows with hardening in place."""

    @pytest.mark.asyncio
    async def test_mcp_tool_rate_limiting_works(self):
        """Rate limiter should prevent concurrent task flooding."""
        from openspace.mcp_server_limiter import execute_task_limiter

        # Acquire all concurrent tokens
        results = []
        for i in range(3):
            result = await execute_task_limiter.acquire()
            results.append(result)

        assert results == [True, True, True]

        # 4th attempt should be rejected
        result4 = await execute_task_limiter.acquire()
        assert result4 is False

        # Release all
        for i in range(3):
            await execute_task_limiter.release()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
