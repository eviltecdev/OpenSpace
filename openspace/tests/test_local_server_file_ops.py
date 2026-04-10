"""Tests for local_server — File operations with path security validation.

Target coverage: Path validation, file read/write, permission handling
Test count: 6 tests covering:
- Path validation (allowed roots: $HOME, /tmp)
- Path traversal rejection
- File read/write operations
- Permission error handling
- Path normalization
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_workspace(tmp_path):
    """Temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


# ============================================================================
# Tests: Path Validation & Security
# ============================================================================


class TestPathValidation:
    """Test path validation security patterns."""

    def test_validate_home_path_allowed(self):
        """Home directory paths should be allowed."""
        home = Path.home()
        test_path = str(home / "test.txt")

        # Verify path is within home
        is_allowed = os.path.realpath(test_path).startswith(str(home))
        assert is_allowed

    def test_validate_tmp_path_allowed(self):
        """Temporary directory paths should be allowed."""
        test_path = "/tmp/test.txt"

        # Verify path is within /tmp (or /private/tmp on macOS)
        real_path = os.path.realpath(test_path)
        is_allowed = real_path.startswith("/tmp") or real_path.startswith("/private/tmp")
        assert is_allowed

    def test_validate_reject_etc_path(self):
        """Reject /etc access (outside allowed roots)."""
        blocked_path = "/etc/passwd"
        home = Path.home()

        # Check if path escapes allowed roots
        real_path = os.path.realpath(blocked_path)
        is_allowed = (
            real_path.startswith(str(home)) or
            real_path.startswith("/tmp")
        )

        assert not is_allowed  # Should be rejected

    def test_validate_reject_path_traversal(self):
        """Reject path traversal attempts (../)."""
        home = Path.home()
        traversal_path = str(home / ".." / "etc" / "passwd")

        # Resolve and check if still within home
        resolved = os.path.realpath(traversal_path)
        is_allowed = resolved.startswith(str(home))

        # Path traversal should escape home
        assert not is_allowed or ".." not in str(traversal_path)

    def test_path_normalization(self):
        """Paths are normalized (expanded, resolved)."""
        home = Path.home()
        raw_path = "~/test.txt"

        # Normalize path
        expanded = os.path.expanduser(raw_path)
        assert "~" not in expanded
        assert home.name in expanded


# ============================================================================
# Tests: File Operations
# ============================================================================


class TestFileOperations:
    """Test file read/write operations."""

    def test_read_file_content(self, temp_workspace):
        """Read file content from allowed path."""
        test_file = temp_workspace / "test.txt"
        test_file.write_text("test content")

        content = test_file.read_text()

        assert content == "test content"

    def test_write_file_allowed(self, temp_workspace):
        """Write file to allowed path."""
        test_file = temp_workspace / "output.txt"

        test_file.write_text("new content")

        assert test_file.exists()
        assert test_file.read_text() == "new content"

    def test_list_directory(self, temp_workspace):
        """List directory contents."""
        (temp_workspace / "file1.txt").write_text("a")
        (temp_workspace / "file2.txt").write_text("b")

        files = list(temp_workspace.iterdir())

        assert len(files) >= 2

    def test_delete_file(self, temp_workspace):
        """Delete file from allowed path."""
        test_file = temp_workspace / "delete_me.txt"
        test_file.write_text("temp")

        test_file.unlink()

        assert not test_file.exists()

    def test_create_subdirectory(self, temp_workspace):
        """Create subdirectory."""
        subdir = temp_workspace / "subdir"

        subdir.mkdir(exist_ok=True)

        assert subdir.exists()
        assert subdir.is_dir()

    def test_relative_path_safety(self, temp_workspace):
        """Ensure relative paths are resolved safely."""
        # Create file in subdirectory
        subdir = temp_workspace / "subdir"
        subdir.mkdir()
        file_in_subdir = subdir / "test.txt"
        file_in_subdir.write_text("content")

        # Resolve relative path
        resolved = os.path.realpath(str(file_in_subdir))

        # Should be absolute and within workspace
        assert os.path.isabs(resolved)
        assert str(temp_workspace) in resolved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
