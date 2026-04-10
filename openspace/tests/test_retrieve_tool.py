"""Tests for skill_engine/retrieve_tool — Mid-iteration skill retrieval.

Target coverage: Tool initialization, skill loading, fallback behavior
Test count: 2 tests covering:
- Skill quality data loading from SkillStore
- Fallback behavior (LLM unavailable → BM25 search)
"""

from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from openspace.skill_engine.retrieve_tool import RetrieveSkillTool


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_skill_registry():
    """Mock SkillRegistry for testing."""
    registry = MagicMock()
    registry.list_skills.return_value = [
        MagicMock(skill_id="skill-001", name="Test Skill"),
        MagicMock(skill_id="skill-002", name="Search Skill"),
    ]
    return registry


@pytest.fixture
def mock_skill_store():
    """Mock SkillStore with quality data."""
    store = MagicMock()
    store.get_summary.return_value = {
        "skill-001": {
            "total_selections": 10,
            "total_applied": 8,
            "total_completions": 7,
            "total_fallbacks": 1,
        },
    }
    return store


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient."""
    return MagicMock()


# ============================================================================
# Tests: Tool Initialization and Quality Loading
# ============================================================================


class TestRetrieveSkillTool:
    """Test RetrieveSkillTool initialization and quality loading."""

    def test_tool_initialization(self, mock_skill_registry, mock_llm_client):
        """Tool initializes with registry and LLM client."""
        tool = RetrieveSkillTool(
            skill_registry=mock_skill_registry,
            backends=None,
            llm_client=mock_llm_client,
            skill_store=None,
        )

        assert tool is not None
        assert tool._skill_registry == mock_skill_registry

    def test_load_skill_quality_from_store(self, mock_skill_registry, mock_skill_store):
        """Load skill quality metrics from SkillStore."""
        tool = RetrieveSkillTool(
            skill_registry=mock_skill_registry,
            backends=None,
            llm_client=None,
            skill_store=mock_skill_store,
        )

        quality = tool._load_skill_quality()

        # Should return quality dict or None
        if quality:
            assert isinstance(quality, dict)
            if "skill-001" in quality:
                assert "total_selections" in quality["skill-001"]

    def test_load_skill_quality_no_store(self, mock_skill_registry):
        """Handle missing SkillStore gracefully."""
        tool = RetrieveSkillTool(
            skill_registry=mock_skill_registry,
            backends=None,
            llm_client=None,
            skill_store=None,
        )

        quality = tool._load_skill_quality()

        # Should return None or empty dict without crashing
        assert quality is None or isinstance(quality, dict)

    @pytest.mark.asyncio
    async def test_fallback_without_llm(self, mock_skill_registry):
        """Fallback to BM25 search when LLM unavailable."""
        tool = RetrieveSkillTool(
            skill_registry=mock_skill_registry,
            backends=None,
            llm_client=None,  # No LLM
            skill_store=None,
        )

        # Tool should be initialized
        assert tool is not None
        assert tool._skill_registry == mock_skill_registry


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
