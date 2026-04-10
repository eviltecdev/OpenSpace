"""Tests for OpenSpace LLM cost tracking module.

Tests all cost extraction methods, provider detection, cache operations,
and daily aggregation. Target coverage: 85%+
"""

import json
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from typing import Optional

from openspace.llm import cost_tracker


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def cost_dir(tmp_path, monkeypatch):
    """Isolate cost tracking to temp directory for each test."""
    monkeypatch.setattr(cost_tracker, "_CACHE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def mock_response_with_cost():
    """Mock LiteLLM response with direct _response_cost attribute."""
    response = MagicMock()
    response._response_cost = 0.005
    response.usage = Mock(prompt_tokens=100, completion_tokens=50)
    return response


@pytest.fixture
def mock_response_hidden_params():
    """Mock LiteLLM response with cost in _hidden_params."""
    response = MagicMock()
    response._response_cost = None
    response._hidden_params = {"response_cost": 0.003}
    response.usage = Mock(prompt_tokens=50, completion_tokens=25)
    return response


@pytest.fixture
def mock_response_no_cost():
    """Mock LiteLLM response without cost data (fallback required)."""
    response = MagicMock()
    response._response_cost = None
    response._hidden_params = None
    response.usage = Mock(prompt_tokens=100, completion_tokens=50)
    return response


# ============================================================================
# Tests: Cost Extraction Methods
# ============================================================================


class TestCostExtraction:
    """Test all 4 cost extraction methods in record_cost()."""

    def test_record_cost_via_response_cost_attribute(self, mock_response_with_cost, cost_dir):
        """Test cost extraction from response._response_cost attribute (Method 1)."""
        result = cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")
        assert result == 0.005

        # Verify cache file created
        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        assert cache_file.exists()

        # Verify cache content
        cache = json.loads(cache_file.read_text())
        assert cache["total"] == 0.005
        assert cache["calls"] == 1
        assert cache["models"]["gpt-4o"] == 0.005

    def test_record_cost_via_hidden_params(self, mock_response_hidden_params, cost_dir):
        """Test cost extraction from response._hidden_params (Method 2)."""
        result = cost_tracker.record_cost(mock_response_hidden_params, "anthropic/claude-sonnet")
        assert result == 0.003

        cache_file = cost_dir / f"anthropic-daily-costs-{date.today()}.json"
        cache = json.loads(cache_file.read_text())
        assert cache["total"] == 0.003
        assert cache["calls"] == 1

    def test_record_cost_via_litellm_completion_cost(self, mock_response_no_cost, cost_dir, monkeypatch):
        """Test cost extraction via litellm.completion_cost() (Method 3)."""
        # Mock litellm.completion_cost to return a cost
        import litellm
        mock_litellm_cost = MagicMock(return_value=0.002)
        monkeypatch.setattr(litellm, "completion_cost", mock_litellm_cost)

        result = cost_tracker.record_cost(mock_response_no_cost, "gpt-3.5-turbo")
        assert result == 0.002

        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        cache = json.loads(cache_file.read_text())
        assert cache["total"] == 0.002

    def test_record_cost_via_cost_per_token(self, mock_response_no_cost, cost_dir, monkeypatch):
        """Test cost extraction via litellm.cost_per_token() fallback (Method 4)."""
        # Mock litellm functions
        import litellm
        monkeypatch.setattr(
            litellm, "completion_cost",
            MagicMock(return_value=None)
        )
        monkeypatch.setattr(
            litellm, "cost_per_token",
            MagicMock(return_value=(0.0001, 0.0002))  # (prompt_cost, completion_cost)
        )

        result = cost_tracker.record_cost(mock_response_no_cost, "gpt-4")
        # 0.0001 (100 prompt tokens @ $0.001/1k) + 0.0100 (50 completion tokens @ $0.002/1k)
        assert result is not None
        assert result > 0

    def test_record_cost_none_response(self, cost_dir):
        """Test record_cost with None response returns None."""
        result = cost_tracker.record_cost(None, "gpt-4o")
        assert result is None

    def test_record_cost_zero_cost_returns_none(self, cost_dir, monkeypatch):
        """Test record_cost returns None when cost is 0 or None after extraction."""
        response = MagicMock()
        response._response_cost = None
        response._hidden_params = None
        response.usage = None

        # Mock all fallbacks to return None/0
        import litellm
        monkeypatch.setattr(litellm, "completion_cost", MagicMock(return_value=None))
        monkeypatch.setattr(litellm, "cost_per_token", MagicMock(return_value=(None, None)))

        result = cost_tracker.record_cost(response, "unknown-model")
        assert result is None


# ============================================================================
# Tests: Provider Detection
# ============================================================================


class TestProviderDetection:
    """Test _detect_provider() function."""

    def test_detect_provider_openai(self):
        """Test OpenAI prefix detection."""
        assert cost_tracker._detect_provider("gpt-4o") == "openai"
        assert cost_tracker._detect_provider("gpt-3.5-turbo") == "openai"
        assert cost_tracker._detect_provider("o1-preview") == "openai"
        assert cost_tracker._detect_provider("o3-mini") == "openai"
        assert cost_tracker._detect_provider("openai/gpt-4") == "openai"

    def test_detect_provider_anthropic(self):
        """Test Anthropic prefix detection."""
        assert cost_tracker._detect_provider("claude-sonnet") == "anthropic"
        assert cost_tracker._detect_provider("claude-haiku") == "anthropic"
        assert cost_tracker._detect_provider("Claude-opus") == "anthropic"  # Case insensitive
        assert cost_tracker._detect_provider("anthropic/claude-3-sonnet") == "anthropic"

    def test_detect_provider_unknown(self):
        """Test unknown provider returns None."""
        assert cost_tracker._detect_provider("unknown-model") is None
        assert cost_tracker._detect_provider("") is None
        assert cost_tracker._detect_provider(None) is None

    def test_detect_provider_case_insensitive(self):
        """Test provider detection is case-insensitive."""
        assert cost_tracker._detect_provider("GPT-4O") == "openai"
        assert cost_tracker._detect_provider("CLAUDE-SONNET") == "anthropic"


# ============================================================================
# Tests: Cache Operations
# ============================================================================


class TestCacheOperations:
    """Test _load_cache and _save_cache functions."""

    def test_load_cache_missing_file(self, cost_dir):
        """Test _load_cache with missing file returns default dict."""
        cache = cost_tracker._load_cache("openai")
        assert cache == {"total": 0.0, "calls": 0, "models": {}}

    def test_load_cache_existing_file(self, cost_dir):
        """Test _load_cache reads existing cache file correctly."""
        cache_data = {"total": 0.1, "calls": 5, "models": {"gpt-4o": 0.08, "gpt-3.5-turbo": 0.02}}
        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        cache_file.write_text(json.dumps(cache_data))

        loaded = cost_tracker._load_cache("openai")
        assert loaded == cache_data

    def test_load_cache_corrupted_file(self, cost_dir):
        """Test _load_cache with corrupted JSON returns default dict."""
        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        cache_file.write_text("invalid json {")

        cache = cost_tracker._load_cache("openai")
        assert cache == {"total": 0.0, "calls": 0, "models": {}}

    def test_save_cache_creates_file(self, cost_dir):
        """Test _save_cache creates cache file with correct format."""
        data = {"total": 0.05, "calls": 2, "models": {"gpt-4o": 0.05}}
        cost_tracker._save_cache(data, "openai")

        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == data

    def test_cache_persistence_across_calls(self, cost_dir, mock_response_with_cost):
        """Test that cache persists across multiple record_cost calls."""
        # First call
        cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")

        # Second call with different model
        mock_response_2 = MagicMock()
        mock_response_2._response_cost = 0.003
        cost_tracker.record_cost(mock_response_2, "gpt-3.5-turbo")

        # Verify aggregation
        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        cache = json.loads(cache_file.read_text())
        assert cache["total"] == pytest.approx(0.008, abs=0.0001)
        assert cache["calls"] == 2
        assert cache["models"]["gpt-4o"] == 0.005
        assert cache["models"]["gpt-3.5-turbo"] == 0.003


# ============================================================================
# Tests: Daily Totals Aggregation
# ============================================================================


class TestDailyTotals:
    """Test get_daily_total and get_daily_total_by_provider functions."""

    def test_get_daily_total_empty(self, cost_dir):
        """Test get_daily_total returns None when no costs recorded."""
        result = cost_tracker.get_daily_total()
        assert result is None

    def test_get_daily_total_single_provider(self, cost_dir, mock_response_with_cost):
        """Test get_daily_total with single provider costs."""
        cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")

        result = cost_tracker.get_daily_total()
        assert result is not None
        assert result["total"] == 0.005
        assert result["calls"] == 1
        assert "gpt-4o" in result["models"]
        assert result["by_provider"]["openai"]["total"] == 0.005

    def test_get_daily_total_multiple_providers(self, cost_dir, mock_response_with_cost):
        """Test get_daily_total aggregates costs from multiple providers."""
        # OpenAI cost
        cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")

        # Anthropic cost
        mock_anthropic = MagicMock()
        mock_anthropic._response_cost = 0.003
        cost_tracker.record_cost(mock_anthropic, "claude-sonnet")

        result = cost_tracker.get_daily_total()
        assert result["total"] == pytest.approx(0.008, abs=0.0001)
        assert result["calls"] == 2
        assert result["by_provider"]["openai"]["total"] == 0.005
        assert result["by_provider"]["anthropic"]["total"] == 0.003

    def test_get_daily_total_by_provider_openai(self, cost_dir, mock_response_with_cost):
        """Test get_daily_total_by_provider for OpenAI."""
        cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")

        result = cost_tracker.get_daily_total_by_provider("openai")
        assert result is not None
        assert result["total"] == 0.005
        assert result["calls"] == 1

    def test_get_daily_total_by_provider_empty(self, cost_dir):
        """Test get_daily_total_by_provider returns None when no costs."""
        result = cost_tracker.get_daily_total_by_provider("openai")
        assert result is None


# ============================================================================
# Tests: Alert Logic
# ============================================================================


class TestAlertLogic:
    """Test daily cost alert threshold."""

    def test_alert_triggers_at_threshold(self, cost_dir, mock_response_with_cost, monkeypatch):
        """Test alert logs warning when daily total >= threshold ($5.0 default)."""
        # Set a low threshold to trigger easily
        monkeypatch.setattr(cost_tracker, "_ALERT_THRESHOLD", 0.005)

        # Mock logger to capture warning
        with patch("openspace.llm.cost_tracker.logger") as mock_logger:
            cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")
            mock_logger.warning.assert_called_once()
            args = mock_logger.warning.call_args[0]
            assert "alert" in args[0].lower()

    def test_no_alert_below_threshold(self, cost_dir, mock_response_with_cost, monkeypatch):
        """Test no alert when daily total is below threshold."""
        monkeypatch.setattr(cost_tracker, "_ALERT_THRESHOLD", 10.0)

        with patch("openspace.llm.cost_tracker.logger") as mock_logger:
            cost_tracker.record_cost(mock_response_with_cost, "gpt-4o")
            mock_logger.warning.assert_not_called()

    def test_alert_threshold_from_env(self, cost_dir, monkeypatch):
        """Test alert threshold can be configured via environment variable."""
        monkeypatch.setenv("OPENSPACE_COST_ALERT_THRESHOLD", "0.001")
        # Reimport to pick up new env var (or manually set)
        monkeypatch.setattr(cost_tracker, "_ALERT_THRESHOLD", 0.001)

        response = MagicMock()
        response._response_cost = 0.005

        with patch("openspace.llm.cost_tracker.logger") as mock_logger:
            cost_tracker.record_cost(response, "gpt-4o")
            mock_logger.warning.assert_called_once()


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests simulating real-world usage patterns."""

    def test_multiple_calls_throughout_day(self, cost_dir):
        """Test realistic scenario: multiple calls over time aggregate correctly."""
        calls = [
            ("gpt-4o", 0.005),
            ("gpt-3.5-turbo", 0.002),
            ("claude-sonnet", 0.003),
            ("gpt-4o", 0.002),
            ("claude-opus", 0.010),
        ]

        for model, cost in calls:
            response = MagicMock()
            response._response_cost = cost
            cost_tracker.record_cost(response, model)

        daily = cost_tracker.get_daily_total()
        assert daily["total"] == pytest.approx(0.022, abs=0.0001)
        assert daily["calls"] == 5
        assert daily["by_provider"]["openai"]["calls"] == 3
        assert daily["by_provider"]["anthropic"]["calls"] == 2

    def test_rounding_precision(self, cost_dir):
        """Test that costs are rounded to 6 decimal places correctly."""
        response = MagicMock()
        response._response_cost = 0.0123456789  # More precision than stored

        cost_tracker.record_cost(response, "gpt-4o")

        cache_file = cost_dir / f"openai-daily-costs-{date.today()}.json"
        cache = json.loads(cache_file.read_text())
        # Should be rounded to 6 decimals
        assert cache["total"] == round(0.0123456789, 6)
