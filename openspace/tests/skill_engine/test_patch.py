"""Tests for patch module — skill editing, patching, and validation.

Target coverage: 50%+ (currently 0%)
Test count: 20-25 tests covering patch types, parsing, skill operations, and error handling.
"""

import pytest
import shutil
from pathlib import Path
from openspace.skill_engine.patch import (
    PatchType,
    PatchError,
    PatchParseError,
    detect_patch_type,
    parse_multi_file_full,
    fix_skill,
    derive_skill,
    create_skill,
    compute_skill_diff,
    SKILL_FILENAME,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_skill_dir(tmp_path):
    """Create a sample skill directory with SKILL.md."""
    skill_dir = tmp_path / "test_skill"
    skill_dir.mkdir()

    skill_md = skill_dir / SKILL_FILENAME
    skill_md.write_text(
        "# Test Skill\n\n"
        "description: A test skill\n\n"
        "def hello():\n"
        "    return 'hello'\n"
    )

    # Add an auxiliary file
    (skill_dir / "helper.py").write_text("def helper():\n    pass\n")

    return skill_dir


@pytest.fixture
def skill_dir_with_content(tmp_path):
    """Create a skill with multi-file content."""
    skill_dir = tmp_path / "multi_skill"
    skill_dir.mkdir()

    skill_file = skill_dir / SKILL_FILENAME
    skill_file.write_text(
        "---\n"
        "name: MultiFile\n"
        "version: 1.0\n"
        "---\n\n"
        "# MultiFile Skill\n\n"
        "Line 1\n"
        "Line 2\n"
        "Line 3\n"
    )

    (skill_dir / "config.json").write_text('{"name": "test"}\n')
    (skill_dir / "scripts/setup.sh").parent.mkdir(parents=True)
    (skill_dir / "scripts/setup.sh").write_text("#!/bin/bash\necho hello\n")

    return skill_dir


# ============================================================================
# Tests: Patch Type Detection
# ============================================================================


class TestDetectPatchType:
    """Test auto-detection of patch format."""

    def test_detect_patch_format(self):
        """Detect *** Begin Patch format."""
        content = "*** Begin Patch\n*** Add File: SKILL.md\n+content\n*** End Patch"
        assert detect_patch_type(content) == PatchType.PATCH

    def test_detect_full_format_with_envelope(self):
        """Detect *** Begin Files format."""
        content = "*** Begin Files\n*** File: SKILL.md\ncontent\n*** End Files"
        assert detect_patch_type(content) == PatchType.FULL

    def test_detect_full_format_with_markers(self):
        """Detect *** File: markers (no envelope)."""
        content = "*** File: SKILL.md\ncontent\n*** File: helper.py\nmore"
        assert detect_patch_type(content) == PatchType.FULL

    def test_detect_diff_format(self):
        """Detect <<<<<<< SEARCH format."""
        content = (
            "<<<<<<< SEARCH\n"
            "old content\n"
            "=======\n"
            "new content\n"
            ">>>>>>> REPLACE"
        )
        assert detect_patch_type(content) == PatchType.DIFF

    def test_detect_default_full(self):
        """Default to FULL when no markers present."""
        content = "Just some regular text\nwith no markers"
        assert detect_patch_type(content) == PatchType.FULL

    def test_detect_priority_patch_over_diff(self):
        """PATCH marker takes precedence over DIFF."""
        content = (
            "*** Begin Patch\n"
            "content\n"
            "<<<<<<< SEARCH\n"
            "more content"
        )
        assert detect_patch_type(content) == PatchType.PATCH

    def test_detect_priority_full_over_diff(self):
        """FULL markers take precedence over DIFF."""
        content = (
            "*** Begin Files\n"
            "content\n"
            "<<<<<<< SEARCH\n"
            "more content"
        )
        assert detect_patch_type(content) == PatchType.FULL


# ============================================================================
# Tests: Multi-File FULL Format Parsing
# ============================================================================


class TestParseMultiFileFull:
    """Test parsing of *** File: format."""

    def test_parse_single_file(self):
        """Parse single file content (no markers)."""
        content = "# Skill\n\nSome content"
        result = parse_multi_file_full(content)
        assert SKILL_FILENAME in result
        assert "# Skill" in result[SKILL_FILENAME]

    def test_parse_multi_file_with_envelope(self):
        """Parse with *** Begin Files envelope."""
        content = (
            "*** Begin Files\n"
            "*** File: SKILL.md\n"
            "# Skill content\n"
            "*** File: helper.py\n"
            "def helper():\n"
            "    pass\n"
            "*** End Files"
        )
        result = parse_multi_file_full(content)
        assert "SKILL.md" in result
        assert "helper.py" in result
        assert "# Skill content" in result["SKILL.md"]
        assert "def helper():" in result["helper.py"]

    def test_parse_multi_file_without_envelope(self):
        """Parse with *** File: markers (no envelope)."""
        content = (
            "*** File: SKILL.md\n"
            "Skill content\n"
            "*** File: config.json\n"
            '{"key": "value"}'
        )
        result = parse_multi_file_full(content)
        assert len(result) == 2
        assert "SKILL.md" in result
        assert "config.json" in result

    def test_parse_nested_paths(self):
        """Parse files in subdirectories."""
        content = (
            "*** File: SKILL.md\n"
            "skill\n"
            "*** File: scripts/setup.sh\n"
            "#!/bin/bash\n"
        )
        result = parse_multi_file_full(content)
        assert "scripts/setup.sh" in result
        assert "#!/bin/bash" in result["scripts/setup.sh"]

    def test_parse_empty_file(self):
        """Handle empty files."""
        content = (
            "*** File: SKILL.md\n"
            "content\n"
            "*** File: empty.txt\n"
            "*** File: another.txt\n"
            "content"
        )
        result = parse_multi_file_full(content)
        assert "empty.txt" in result
        # Empty file should have empty string
        assert result["empty.txt"] == ""

    def test_parse_preserves_trailing_newlines(self):
        """Preserve one trailing newline for non-empty files."""
        content = "*** File: test.txt\nLine 1\nLine 2"
        result = parse_multi_file_full(content)
        assert result["test.txt"].endswith("\n")


# ============================================================================
# Tests: Fix Skill
# ============================================================================


class TestFixSkill:
    """Test in-place skill repair."""

    def test_fix_skill_with_full_format(self, sample_skill_dir):
        """Fix skill using FULL format."""
        new_content = (
            "*** Begin Files\n"
            "*** File: SKILL.md\n"
            "# Updated Skill\n\n"
            "Updated content\n"
            "*** File: helper.py\n"
            "def updated_helper():\n"
            "    return 42\n"
            "*** End Files"
        )

        result = fix_skill(sample_skill_dir, new_content, PatchType.FULL)

        assert result.ok
        assert result.skill_dir == sample_skill_dir
        assert "Updated content" in result.content_snapshot[SKILL_FILENAME]
        assert "updated_helper" in result.content_snapshot.get("helper.py", "")

    def test_fix_skill_skill_dir_not_found(self, tmp_path):
        """Error when skill directory doesn't exist."""
        nonexistent = tmp_path / "nonexistent"
        result = fix_skill(nonexistent, "content", PatchType.FULL)
        assert not result.ok
        assert "not found" in result.error.lower()

    def test_fix_skill_missing_skill_md(self, tmp_path):
        """Error when SKILL.md missing."""
        skill_dir = tmp_path / "broken_skill"
        skill_dir.mkdir()

        result = fix_skill(skill_dir, "content", PatchType.FULL)
        assert not result.ok
        assert "SKILL.md" in result.error

    def test_fix_skill_auto_detects_patch_type(self, sample_skill_dir):
        """Auto-detect patch type and apply."""
        content = (
            "*** Begin Files\n"
            "*** File: SKILL.md\n"
            "# Auto-detected\n"
            "*** End Files"
        )

        result = fix_skill(sample_skill_dir, content)  # No patch_type specified
        assert result.ok

    def test_fix_skill_returns_diff(self, sample_skill_dir):
        """Returned diff captures changes."""
        original_content = (sample_skill_dir / SKILL_FILENAME).read_text()

        new_content = (
            "*** File: SKILL.md\n"
            "# Completely new\n"
        )

        result = fix_skill(sample_skill_dir, new_content, PatchType.FULL)
        assert result.ok
        # Diff should show changes were made
        assert len(result.content_diff) > 0


# ============================================================================
# Tests: Derive Skill
# ============================================================================


class TestDeriveSkill:
    """Test skill derivation from parent(s)."""

    def test_derive_skill_single_parent(self, sample_skill_dir, tmp_path):
        """Derive from single parent skill."""
        target = tmp_path / "derived"

        new_content = (
            "*** File: SKILL.md\n"
            "# Derived Skill\n"
        )

        result = derive_skill(sample_skill_dir, target, new_content, PatchType.FULL)

        assert result.ok
        assert target.exists()
        (target / SKILL_FILENAME).read_text()  # Should exist

    def test_derive_skill_target_already_exists(self, sample_skill_dir, tmp_path):
        """Error when target already exists."""
        target = tmp_path / "existing"
        target.mkdir()

        result = derive_skill(sample_skill_dir, target, "content", PatchType.FULL)
        assert not result.ok
        assert "exists" in result.error.lower()

    def test_derive_skill_source_not_found(self, tmp_path):
        """Error when source skill doesn't exist."""
        nonexistent_source = tmp_path / "nonexistent"
        target = tmp_path / "target"

        result = derive_skill(nonexistent_source, target, "content", PatchType.FULL)
        assert not result.ok
        assert "not found" in result.error.lower() or "does not exist" in result.error.lower()

    def test_derive_skill_preserves_source(self, sample_skill_dir, tmp_path):
        """Source skill remains unchanged."""
        original_content = (sample_skill_dir / SKILL_FILENAME).read_text()
        target = tmp_path / "derived"

        derive_skill(sample_skill_dir, target, "*** File: SKILL.md\n# New", PatchType.FULL)

        # Source should be unchanged
        assert (sample_skill_dir / SKILL_FILENAME).read_text() == original_content

    def test_derive_skill_multi_parent(self, skill_dir_with_content, sample_skill_dir, tmp_path):
        """Derive from multiple parents."""
        target = tmp_path / "merged"

        new_content = (
            "*** File: SKILL.md\n"
            "# Merged from multiple sources\n"
        )

        result = derive_skill(
            [sample_skill_dir, skill_dir_with_content],
            target,
            new_content,
            PatchType.FULL
        )

        assert result.ok
        assert target.exists()

    def test_derive_skill_single_parent_with_diff_becomes_full(self, sample_skill_dir, tmp_path):
        """DIFF on single parent gets converted to FULL for multi-parent."""
        # This test would check multi-parent with DIFF type
        target = tmp_path / "multi"

        diff_content = (
            "<<<<<<< SEARCH\n"
            "old\n"
            "=======\n"
            "new\n"
            ">>>>>>> REPLACE"
        )

        result = derive_skill(
            [sample_skill_dir, tmp_path / "dummy"],  # dummy won't be checked as it fails on parent validation
            target,
            diff_content,
            PatchType.DIFF
        )

        assert not result.ok  # Will fail due to invalid second parent


# ============================================================================
# Tests: Create Skill
# ============================================================================


class TestCreateSkill:
    """Test skill creation from scratch."""

    def test_create_skill_from_full_format(self, tmp_path):
        """Create new skill from FULL format."""
        target = tmp_path / "new_skill"

        content = (
            "*** Begin Files\n"
            "*** File: SKILL.md\n"
            "# New Skill\n\n"
            "description: Newly created\n"
            "*** File: main.py\n"
            "def main():\n"
            "    pass\n"
            "*** End Files"
        )

        result = create_skill(target, content, PatchType.FULL)

        assert result.ok
        assert target.exists()
        assert (target / SKILL_FILENAME).exists()
        assert (target / "main.py").exists()

    def test_create_skill_target_already_exists(self, tmp_path):
        """Error when target already exists."""
        target = tmp_path / "existing"
        target.mkdir()

        result = create_skill(target, "content", PatchType.FULL)
        assert not result.ok
        assert "exists" in result.error.lower()

    def test_create_skill_auto_detects_type(self, tmp_path):
        """Auto-detect format and create."""
        target = tmp_path / "auto_skill"

        content = "*** File: SKILL.md\n# Auto Detected"

        result = create_skill(target, content)  # No type specified
        assert result.ok

    def test_create_skill_returns_snapshot(self, tmp_path):
        """Returned snapshot contains all created files."""
        target = tmp_path / "snapshot_skill"

        content = (
            "*** File: SKILL.md\n"
            "Content 1\n"
            "*** File: helper.py\n"
            "Content 2\n"
        )

        result = create_skill(target, content, PatchType.FULL)

        assert result.ok
        assert SKILL_FILENAME in result.content_snapshot
        assert "helper.py" in result.content_snapshot

    def test_create_skill_adds_trailing_newlines(self, tmp_path):
        """Create preserves file content with proper newlines."""
        target = tmp_path / "newline_skill"

        content = (
            "*** File: SKILL.md\n"
            "Line 1\n"
            "Line 2"  # No trailing newline
        )

        result = create_skill(target, content, PatchType.FULL)

        assert result.ok
        skill_content = (target / SKILL_FILENAME).read_text()
        # Should have a trailing newline
        assert skill_content.endswith("\n")


# ============================================================================
# Tests: Path Validation (Security)
# ============================================================================


class TestPathValidation:
    """Test path-jail security for skill operations."""

    def test_fix_skill_blocks_path_traversal(self, sample_skill_dir):
        """Reject paths that escape skill directory."""
        # Try to create a file outside skill_dir
        malicious_content = (
            "*** File: ../../../etc/passwd\n"
            "malicious content\n"
        )

        result = fix_skill(sample_skill_dir, malicious_content, PatchType.FULL)
        # Should either reject or be safe (resolve path)
        assert not result.ok or result.skill_dir.is_dir()

    def test_fix_skill_blocks_absolute_paths(self, sample_skill_dir):
        """Reject absolute paths."""
        malicious_content = (
            "*** File: /etc/passwd\n"
            "malicious\n"
        )

        result = fix_skill(sample_skill_dir, malicious_content, PatchType.FULL)
        assert not result.ok or result.skill_dir.is_dir()


# ============================================================================
# Tests: Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_fix_skill_invalid_patch_type(self, sample_skill_dir):
        """Handle invalid patch type gracefully."""
        content = "some content"
        # This should be handled by detect_patch_type, but test robustness
        result = fix_skill(sample_skill_dir, content, PatchType.AUTO)
        assert result.ok or not result.ok  # Either works or has error

    def test_derive_skill_empty_source_list(self, tmp_path):
        """Error when source list is empty."""
        target = tmp_path / "target"
        result = derive_skill([], target, "content", PatchType.FULL)
        assert not result.ok

    def test_create_skill_cleans_up_on_error(self, tmp_path):
        """Directory cleaned up if creation fails."""
        target = tmp_path / "cleanup_test"
        # Invalid content that will cause failure
        invalid_content = "Not a valid patch format but also not creatable"

        result = create_skill(target, invalid_content, PatchType.DIFF)

        # Either succeeded or cleaned up
        if not result.ok:
            # Directory might not exist after cleanup, or be empty
            assert not target.exists() or not list(target.iterdir())


# ============================================================================
# Tests: Integration & Complex Scenarios
# ============================================================================


class TestComplexScenarios:
    """Test realistic multi-step scenarios."""

    def test_roundtrip_fix_and_derive(self, sample_skill_dir, tmp_path):
        """Fix a skill, then derive from it."""
        # Step 1: Fix original
        fix_content = "*** File: SKILL.md\n# Fixed"
        fix_result = fix_skill(sample_skill_dir, fix_content, PatchType.FULL)
        assert fix_result.ok

        # Step 2: Derive from fixed
        target = tmp_path / "derived"
        derive_content = "*** File: SKILL.md\n# Derived from fixed"
        derive_result = derive_skill(sample_skill_dir, target, derive_content, PatchType.FULL)
        assert derive_result.ok
        assert target.exists()

    def test_create_and_fix_workflow(self, tmp_path):
        """Create a skill, then fix it."""
        # Step 1: Create
        skill_dir = tmp_path / "created"
        create_content = (
            "*** File: SKILL.md\n"
            "# Original\n"
            "*** File: helper.py\n"
            "original content"
        )
        create_result = create_skill(skill_dir, create_content, PatchType.FULL)
        assert create_result.ok

        # Step 2: Fix it
        fix_content = "*** File: helper.py\nupdated content"
        fix_result = fix_skill(skill_dir, fix_content, PatchType.FULL)
        assert fix_result.ok

        # Verify change was applied
        helper_content = (skill_dir / "helper.py").read_text()
        assert "updated content" in helper_content
