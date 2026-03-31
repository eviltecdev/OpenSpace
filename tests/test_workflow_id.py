"""Tests for workflow ID uniqueness and discovery."""

from pathlib import Path
from unittest.mock import patch

import pytest

from openspace import dashboard_server


def _make_workflow(path: Path):
    """Create a minimal workflow directory with metadata.json."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.json").write_text("{}", encoding="utf-8")


class TestWorkflowId:
    def test_same_leaf_name_different_roots_get_unique_ids(self, tmp_path):
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        wf_a = root_a / "task1"
        wf_b = root_b / "task1"
        _make_workflow(wf_a)
        _make_workflow(wf_b)

        with patch.object(dashboard_server, "WORKFLOW_ROOTS", [root_a, root_b]):
            id_a = dashboard_server._workflow_id(wf_a)
            id_b = dashboard_server._workflow_id(wf_b)

        assert id_a != id_b
        assert id_a.startswith("task1_")
        assert id_b.startswith("task1_")

    def test_id_contains_dir_name_and_hash(self, tmp_path):
        root = tmp_path / "root"
        wf = root / "my-task"
        _make_workflow(wf)

        with patch.object(dashboard_server, "WORKFLOW_ROOTS", [root]):
            wf_id = dashboard_server._workflow_id(wf)

        assert wf_id.startswith("my-task_")
        assert len(wf_id) == len("my-task_") + 8  # 8-char hex hash

    def test_separator_collision_produces_different_ids(self, tmp_path):
        """Regression: a dir named 'a__b' must not collide with path a/b."""
        root = tmp_path / "root"
        flat = root / "a__b"
        nested = root / "a" / "b"
        _make_workflow(flat)
        _make_workflow(nested)

        with patch.object(dashboard_server, "WORKFLOW_ROOTS", [root]):
            id_flat = dashboard_server._workflow_id(flat)
            id_nested = dashboard_server._workflow_id(nested)

        assert id_flat != id_nested

    def test_workflow_outside_roots_still_works(self, tmp_path):
        wf = tmp_path / "orphan_workflow"
        _make_workflow(wf)

        with patch.object(dashboard_server, "WORKFLOW_ROOTS", []):
            wf_id = dashboard_server._workflow_id(wf)

        assert wf_id.startswith("orphan_workflow_")


class TestDiscoverWorkflowDirs:
    def test_same_name_workflows_both_discovered(self, tmp_path):
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        _make_workflow(root_a / "task1")
        _make_workflow(root_b / "task1")

        with patch.object(dashboard_server, "WORKFLOW_ROOTS", [root_a, root_b]):
            dirs = dashboard_server._discover_workflow_dirs()

        assert len(dirs) == 2

    def test_get_workflow_dir_resolves_correct_path(self, tmp_path):
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        _make_workflow(root_a / "task1")
        _make_workflow(root_b / "task1")

        with patch.object(dashboard_server, "WORKFLOW_ROOTS", [root_a, root_b]):
            id_a = dashboard_server._workflow_id(root_a / "task1")
            id_b = dashboard_server._workflow_id(root_b / "task1")
            found_a = dashboard_server._get_workflow_dir(id_a)
            found_b = dashboard_server._get_workflow_dir(id_b)

        assert found_a.resolve() == (root_a / "task1").resolve()
        assert found_b.resolve() == (root_b / "task1").resolve()
