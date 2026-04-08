"""Tests für openspace.skill_engine.store — SQLite CRUD-Operationen."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from openspace.skill_engine.store import SkillStore
from openspace.skill_engine.types import (
    ExecutionAnalysis,
    SkillCategory,
    SkillJudgment,
    SkillLineage,
    SkillOrigin,
    SkillRecord,
    SkillVisibility,
)


def _make_record(name: str = "test-skill", skill_id: str | None = None) -> SkillRecord:
    """Helper: minimaler gültiger SkillRecord."""
    return SkillRecord(
        skill_id=skill_id or f"skill-{uuid.uuid4().hex[:8]}",
        name=name,
        description="A test skill",
        path="/tmp/skills/test",
        lineage=SkillLineage(origin=SkillOrigin.IMPORTED),
    )


@pytest.fixture
def store(tmp_path: Path):
    """SkillStore mit isolierter Temp-DB pro Test."""
    db = tmp_path / "test.db"
    s = SkillStore(db_path=db)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Grundlegende CRUD
# ---------------------------------------------------------------------------

class TestSaveAndLoad:
    def test_save_and_load_record(self, store: SkillStore):
        record = _make_record()
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert loaded is not None
        assert loaded.skill_id == record.skill_id
        assert loaded.name == record.name

    def test_load_nonexistent_returns_none(self, store: SkillStore):
        assert store.load_record("does-not-exist") is None

    def test_upsert_updates_existing(self, store: SkillStore):
        record = _make_record()
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        record.description = "Updated description"
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert loaded.description == "Updated description"

    def test_load_all_empty(self, store: SkillStore):
        result = store.load_all()
        assert result == {}

    def test_load_all_returns_saved_records(self, store: SkillStore):
        r1 = _make_record("skill-a")
        r2 = _make_record("skill-b")
        asyncio.get_event_loop().run_until_complete(
            store.save_records([r1, r2])
        )
        result = store.load_all(active_only=False)
        assert len(result) == 2
        assert r1.skill_id in result
        assert r2.skill_id in result

    def test_load_all_active_only(self, store: SkillStore):
        active = _make_record("active-skill")
        inactive = _make_record("inactive-skill")
        inactive.is_active = False
        asyncio.get_event_loop().run_until_complete(
            store.save_records([active, inactive])
        )
        result = store.load_all(active_only=True)
        assert len(result) == 1
        assert active.skill_id in result


# ---------------------------------------------------------------------------
# Statistiken & Deaktivierung
# ---------------------------------------------------------------------------

class TestSkillProperties:
    def test_inactive_skill_excluded_from_active_load(self, store: SkillStore):
        record = _make_record()
        record.is_active = False
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        assert store.load_record(record.skill_id) is not None  # load_record ignoriert is_active
        assert record.skill_id not in store.load_all(active_only=True)

    def test_category_stored_correctly(self, store: SkillStore):
        record = _make_record()
        record.category = SkillCategory.TOOL_GUIDE
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert loaded.category == SkillCategory.TOOL_GUIDE

    def test_tags_stored_and_loaded(self, store: SkillStore):
        record = _make_record()
        record.tags = ["python", "testing", "automation"]
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert set(loaded.tags) == {"python", "testing", "automation"}

    def test_tool_dependencies_stored(self, store: SkillStore):
        record = _make_record()
        record.tool_dependencies = ["shell", "read_file"]
        record.critical_tools = ["shell"]
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert "shell" in loaded.tool_dependencies
        assert "shell" in loaded.critical_tools


# ---------------------------------------------------------------------------
# ExecutionAnalysis
# ---------------------------------------------------------------------------

class TestExecutionAnalysis:
    def _make_analysis(self, skill_id: str, task_id: str | None = None) -> ExecutionAnalysis:
        return ExecutionAnalysis(
            task_id=task_id or f"task-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(),
            task_completed=True,
            execution_note="Test run",
            skill_judgments=[
                SkillJudgment(skill_id=skill_id, skill_applied=True, note="Applied correctly")
            ],
        )

    def test_save_and_load_analysis(self, store: SkillStore):
        record = _make_record()
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        analysis = self._make_analysis(record.skill_id)
        asyncio.get_event_loop().run_until_complete(store.record_analysis(analysis))
        loaded = store.load_analyses(skill_id=record.skill_id, limit=10)
        assert len(loaded) == 1
        assert loaded[0].task_id == analysis.task_id
        assert loaded[0].task_completed is True

    def test_multiple_analyses_for_skill(self, store: SkillStore):
        record = _make_record()
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        for _ in range(3):
            analysis = self._make_analysis(record.skill_id)
            asyncio.get_event_loop().run_until_complete(store.record_analysis(analysis))
        loaded = store.load_analyses(skill_id=record.skill_id, limit=10)
        assert len(loaded) == 3

    def test_analysis_limit_respected(self, store: SkillStore):
        record = _make_record()
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        for _ in range(5):
            analysis = self._make_analysis(record.skill_id)
            asyncio.get_event_loop().run_until_complete(store.record_analysis(analysis))
        loaded = store.load_analyses(skill_id=record.skill_id, limit=2)
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------

class TestLineage:
    def test_lineage_origin_stored(self, store: SkillStore):
        record = _make_record()
        record.lineage = SkillLineage(
            origin=SkillOrigin.CAPTURED,
            generation=0,
            change_summary="Captured from task",
        )
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert loaded.lineage.origin == SkillOrigin.CAPTURED
        assert loaded.lineage.change_summary == "Captured from task"

    def test_lineage_generation_stored(self, store: SkillStore):
        record = _make_record()
        record.lineage = SkillLineage(origin=SkillOrigin.FIXED, generation=3)
        asyncio.get_event_loop().run_until_complete(store.save_record(record))
        loaded = store.load_record(record.skill_id)
        assert loaded.lineage.generation == 3


# ---------------------------------------------------------------------------
# Store lifecycle
# ---------------------------------------------------------------------------

class TestStoreClosed:
    def test_close_is_idempotent(self, tmp_path: Path):
        db = tmp_path / "close_test.db"
        store = SkillStore(db_path=db)
        store.close()
        store.close()  # Should not raise

    def test_operations_after_close_raise(self, tmp_path: Path):
        db = tmp_path / "closed.db"
        store = SkillStore(db_path=db)
        store.close()
        with pytest.raises(RuntimeError, match="closed"):
            store.load_record("any-id")
