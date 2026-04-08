"""Tests für openspace.llm.client — _sanitize_schema und LLMClient."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openspace.llm.client import LLMClient, _sanitize_schema


# ---------------------------------------------------------------------------
# _sanitize_schema
# ---------------------------------------------------------------------------

class TestSanitizeSchema:
    def test_empty_input_returns_defaults(self):
        result = _sanitize_schema({})
        assert result["type"] == "object"
        assert result["properties"] == {}
        assert result["required"] == []

    def test_none_input_returns_defaults(self):
        result = _sanitize_schema(None)
        assert result == {"type": "object", "properties": {}, "required": []}

    def test_valid_object_schema_unchanged(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        result = _sanitize_schema(schema)
        assert result["type"] == "object"
        assert "name" in result["properties"]
        assert result["required"] == ["name"]

    def test_non_object_type_wrapped(self):
        schema = {"type": "string"}
        result = _sanitize_schema(schema)
        assert result["type"] == "object"
        assert "value" in result["properties"]
        assert result["required"] == ["value"]

    def test_title_removed_from_top_level(self):
        schema = {"type": "object", "title": "MyTool", "properties": {}}
        result = _sanitize_schema(schema)
        assert "title" not in result

    def test_title_removed_from_nested_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "param": {"type": "string", "title": "Param Title"}
            },
        }
        result = _sanitize_schema(schema)
        assert "title" not in result["properties"]["param"]

    def test_missing_properties_added(self):
        schema = {"type": "object"}
        result = _sanitize_schema(schema)
        assert "properties" in result
        assert "required" in result

    def test_original_not_mutated(self):
        schema = {"type": "object", "title": "Keep", "properties": {}}
        original = json.dumps(schema)
        _sanitize_schema(schema)
        assert json.dumps(schema) == original


# ---------------------------------------------------------------------------
# LLMClient.__init__
# ---------------------------------------------------------------------------

class TestLLMClientInit:
    def test_defaults(self):
        client = LLMClient()
        assert client.model == "anthropic/claude-haiku-4-5-20251001"
        assert client.max_retries == 3
        assert client.timeout == 120.0
        assert client.enable_thinking is False

    def test_custom_model(self):
        client = LLMClient(model="openai/gpt-4o-mini")
        assert client.model == "openai/gpt-4o-mini"

    def test_custom_retries_and_timeout(self):
        client = LLMClient(max_retries=5, timeout=60.0)
        assert client.max_retries == 5
        assert client.timeout == 60.0

    def test_rate_limit_delay(self):
        client = LLMClient(rate_limit_delay=0.5)
        assert client.rate_limit_delay == 0.5


# ---------------------------------------------------------------------------
# LLMClient._merge_consecutive_system_messages
# ---------------------------------------------------------------------------

class TestMergeConsecutiveSystemMessages:
    def test_empty_messages(self):
        assert LLMClient._merge_consecutive_system_messages([]) == []

    def test_no_consecutive_system_messages(self):
        msgs = [
            {"role": "system", "content": "A"},
            {"role": "user", "content": "B"},
            {"role": "system", "content": "C"},
        ]
        result = LLMClient._merge_consecutive_system_messages(msgs)
        assert len(result) == 3

    def test_consecutive_system_messages_merged(self):
        msgs = [
            {"role": "system", "content": "First"},
            {"role": "system", "content": "Second"},
            {"role": "user", "content": "Hello"},
        ]
        result = LLMClient._merge_consecutive_system_messages(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "First" in result[0]["content"]
        assert "Second" in result[0]["content"]

    def test_single_message_unchanged(self):
        msgs = [{"role": "user", "content": "Hi"}]
        result = LLMClient._merge_consecutive_system_messages(msgs)
        assert result == msgs


# ---------------------------------------------------------------------------
# cost_tracker integration
# ---------------------------------------------------------------------------

class TestCostTracker:
    def test_record_openai_cost(self, tmp_path, monkeypatch):
        from openspace.llm import cost_tracker
        monkeypatch.setattr(cost_tracker, "_CACHE_DIR", tmp_path)

        mock_response = MagicMock()
        mock_response._response_cost = 0.005

        cost = cost_tracker.record_cost(mock_response, "openai/gpt-4o-mini")
        assert cost == pytest.approx(0.005)

        data = cost_tracker.get_daily_total_by_provider("openai")
        assert data is not None
        assert data["total"] == pytest.approx(0.005)

    def test_record_anthropic_cost(self, tmp_path, monkeypatch):
        from openspace.llm import cost_tracker
        monkeypatch.setattr(cost_tracker, "_CACHE_DIR", tmp_path)

        mock_response = MagicMock()
        mock_response._response_cost = 0.012

        cost = cost_tracker.record_cost(mock_response, "anthropic/claude-sonnet-4-6")
        assert cost == pytest.approx(0.012)

        data = cost_tracker.get_daily_total_by_provider("anthropic")
        assert data is not None
        assert data["total"] == pytest.approx(0.012)

    def test_combined_total(self, tmp_path, monkeypatch):
        from openspace.llm import cost_tracker
        monkeypatch.setattr(cost_tracker, "_CACHE_DIR", tmp_path)

        r1 = MagicMock()
        r1._response_cost = 0.005
        r2 = MagicMock()
        r2._response_cost = 0.012

        cost_tracker.record_cost(r1, "openai/gpt-4o-mini")
        cost_tracker.record_cost(r2, "anthropic/claude-sonnet-4-6")

        total = cost_tracker.get_daily_total()
        assert total is not None
        assert total["total"] == pytest.approx(0.017)
        assert total["calls"] == 2
        assert "by_provider" in total

    def test_none_response_returns_none(self):
        from openspace.llm import cost_tracker
        assert cost_tracker.record_cost(None, "openai/gpt-4o") is None
