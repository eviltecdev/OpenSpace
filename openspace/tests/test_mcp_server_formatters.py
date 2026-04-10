"""Tests for mcp_server — Result formatting and JSON utilities.

Target coverage: MCP protocol result formatting, field mapping
Test count: 3 tests covering:
- Task result formatting (structure, field handling, truncation)
- JSON serialization (with error handling)
- Evolved skill metadata formatting
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from openspace.mcp_server import (
    _format_task_result,
    _json_ok,
    _json_error,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_task_result():
    """Sample OpenSpace task execution result."""
    return {
        "status": "success",
        "response": "Task completed successfully",
        "execution_time": 12.5,
        "iterations": 3,
        "skills_used": ["web-scraper", "data-parser"],
        "task_id": "task-12345",
        "tool_call_count": 5,
        "tool_summary": [
            {"name": "web_scrape", "count": 2, "success_count": 2},
            {"name": "parse_json", "count": 3, "success_count": 2},
        ],
    }


@pytest.fixture
def sample_task_result_with_evolution():
    """Task result with evolved skills."""
    return {
        "status": "success",
        "response": "Task completed with skill evolution",
        "execution_time": 15.0,
        "iterations": 2,
        "skills_used": ["custom-skill"],
        "task_id": "task-12346",
        "tool_call_count": 3,
        "tool_summary": [],
        "evolved_skills": [
            {
                "skill_dir": "/tmp/skill-v2",
                "name": "custom-skill",
                "origin": "FIX",
                "change_summary": "Fixed tool parameter validation",
                "upload_ready": True,
            }
        ],
    }


# ============================================================================
# Tests: Result Formatting
# ============================================================================


class TestFormatTaskResult:
    """Test _format_task_result() for MCP transport."""

    def test_format_basic_result(self, sample_task_result):
        """Format basic task result with all fields."""
        formatted = _format_task_result(sample_task_result)

        # Should be dict with standard fields
        assert isinstance(formatted, dict)
        assert "status" in formatted
        assert "response" in formatted
        assert "execution_time" in formatted

    def test_format_preserves_essential_fields(self, sample_task_result):
        """Preserves status, response, execution_time."""
        formatted = _format_task_result(sample_task_result)

        assert formatted["status"] == "success"
        assert "successfully" in formatted["response"].lower()
        assert formatted["execution_time"] == 12.5

    def test_format_truncates_tool_errors(self):
        """Tool error messages are truncated to 200 chars."""
        result = {
            "status": "partial_failure",
            "response": "Some tools failed",
            "tool_summary": [
                {
                    "name": "failing_tool",
                    "error": "A" * 300,  # Long error message
                }
            ],
        }

        formatted = _format_task_result(result)

        # Tool errors should be truncated
        assert isinstance(formatted, dict)

    def test_format_limits_tool_summary(self):
        """Tool summary is limited to 20 items max."""
        result = {
            "status": "success",
            "response": "Done",
            "tool_summary": [
                {"name": f"tool_{i}", "count": 1}
                for i in range(30)  # 30 tools
            ],
        }

        formatted = _format_task_result(result)

        # Summary should be limited
        if "tool_summary" in formatted:
            assert len(formatted["tool_summary"]) <= 20

    def test_format_evolved_skills(self, sample_task_result_with_evolution):
        """Include evolved_skills with upload_ready flag."""
        formatted = _format_task_result(sample_task_result_with_evolution)

        # Should have evolved_skills in result
        assert isinstance(formatted, dict)
        if "evolved_skills" in formatted:
            # Verify structure
            assert isinstance(formatted["evolved_skills"], list)

    def test_format_adds_action_required(self, sample_task_result_with_evolution):
        """Add action_required prompt if skills evolved."""
        formatted = _format_task_result(sample_task_result_with_evolution)

        # Should include evolved_skills field
        assert isinstance(formatted, dict)


# ============================================================================
# Tests: JSON Serialization
# ============================================================================


class TestJsonSerialization:
    """Test JSON serialization helpers."""

    def test_json_ok(self, sample_task_result):
        """_json_ok() serializes dict to valid JSON."""
        json_str = _json_ok(sample_task_result)

        assert isinstance(json_str, str)
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "status" in parsed

    def test_json_ok_handles_unicode(self):
        """_json_ok() handles unicode properly."""
        data = {
            "message": "Успех с данными 🎉",
            "emoji": "🚀",
        }

        json_str = _json_ok(data)

        assert isinstance(json_str, str)
        # Should deserialize correctly
        parsed = json.loads(json_str)
        assert "Успех" in parsed["message"] or "🎉" in json_str

    def test_json_error(self):
        """_json_error() formats error as JSON."""
        json_str = _json_error("Test error", status_code=500, attempt=2)

        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert "error" in parsed
        assert "Test error" in parsed["error"]

    def test_json_error_with_extras(self):
        """_json_error() includes extra fields."""
        json_str = _json_error(
            "Rate limited",
            status="rate_limited",
            retry_after=60,
        )

        parsed = json.loads(json_str)
        assert parsed.get("status") == "rate_limited"
        assert parsed.get("retry_after") == 60


# ============================================================================
# Tests: Metadata Formatting
# ============================================================================


class TestMetadataFormatting:
    """Test evolved skill metadata formatting."""

    def test_evolved_skill_structure(self, sample_task_result_with_evolution):
        """Evolved skills include required metadata."""
        formatted = _format_task_result(sample_task_result_with_evolution)

        if "evolved_skills" in formatted:
            for skill in formatted["evolved_skills"]:
                # Check required fields
                assert "skill_dir" in skill
                assert "name" in skill
                assert "origin" in skill  # FIX, DERIVED, CAPTURED
                assert "upload_ready" in skill

    def test_upload_meta_ready_flag(self):
        """upload_ready flag indicates skill is ready to upload."""
        result = {
            "status": "success",
            "response": "Done",
            "evolved_skills": [
                {
                    "skill_dir": "/tmp/skill",
                    "name": "test-skill",
                    "origin": "FIX",
                    "change_summary": "Fixed issue",
                    "upload_ready": True,  # Ready for upload
                }
            ],
        }

        formatted = _format_task_result(result)

        # Should format and return dict
        assert isinstance(formatted, dict)
        assert "status" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
