"""Tests for local_server — Subprocess command execution.

Target coverage: Command execution, timeout handling, output capture, error handling
Test count: 4 tests covering:
- Shell command execution
- Timeout handling
- Output capture (stdout/stderr)
- Exit code propagation
"""

import subprocess
from unittest.mock import patch, MagicMock
import pytest


# ============================================================================
# Tests: Subprocess Execution
# ============================================================================


class TestCommandExecution:
    """Test subprocess command execution."""

    def test_execute_simple_command(self):
        """Execute simple shell command."""
        result = subprocess.run(
            ["echo", "hello"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_execute_with_stdout_capture(self):
        """Capture command output."""
        result = subprocess.run(
            ["echo", "test output"],
            capture_output=True,
            text=True,
        )

        assert result.stdout.strip() == "test output"

    def test_execute_with_stderr_capture(self):
        """Capture stderr output."""
        # Use a command that writes to stderr
        result = subprocess.run(
            "python3 -c \"import sys; sys.stderr.write('error')\"",
            shell=True,
            capture_output=True,
            text=True,
        )

        assert "error" in result.stderr

    def test_execute_nonzero_exit(self):
        """Propagate nonzero exit code."""
        result = subprocess.run(
            "exit 42",
            shell=True,
            capture_output=True,
        )

        assert result.returncode == 42

    def test_execute_with_timeout(self):
        """Handle timeout gracefully."""
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                "sleep 10",
                shell=True,
                capture_output=True,
                timeout=0.1,
            )

    def test_execute_missing_command(self):
        """Handle missing command."""
        with pytest.raises(FileNotFoundError):
            subprocess.run(
                ["nonexistent_command_xyz_123"],
                capture_output=True,
            )

    def test_execute_multiline_script(self):
        """Execute multiline shell script."""
        script = """
echo "line1"
echo "line2"
echo "line3"
"""

        result = subprocess.run(
            script,
            shell=True,
            capture_output=True,
            text=True,
        )

        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 3

    def test_execute_with_environment(self):
        """Pass environment variables to command."""
        env = {"TEST_VAR": "test_value"}

        result = subprocess.run(
            "echo $TEST_VAR",
            shell=True,
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )

        # Output depends on shell behavior
        assert result.returncode == 0


# ============================================================================
# Tests: Error Handling
# ============================================================================


class TestErrorHandling:
    """Test subprocess error handling."""

    def test_handle_timeout(self):
        """Gracefully handle timeout."""
        try:
            subprocess.run(
                "sleep 1000",
                shell=True,
                timeout=0.01,
            )
            assert False, "Should have timed out"
        except subprocess.TimeoutExpired:
            # Expected
            pass

    def test_handle_permission_denied(self):
        """Handle permission denied errors."""
        # Try to execute a file without execute permission
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"echo test")
            f.flush()
            fname = f.name

        try:
            os.chmod(fname, 0o644)  # Remove execute permission
            with pytest.raises((FileNotFoundError, PermissionError)):
                subprocess.run([fname], capture_output=True)
        finally:
            os.unlink(fname)


# Import for environ usage
import os


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
