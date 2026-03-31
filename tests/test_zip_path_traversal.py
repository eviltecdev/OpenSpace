"""Regression tests for zip extraction and import_skill path traversal."""

import io
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _get_extract_zip():
    import importlib
    mod = importlib.import_module("openspace.cloud.client")
    return mod.OpenSpaceClient._extract_zip


class TestExtractZip:
    def test_normal_file_extracted(self, tmp_path):
        extract = _get_extract_zip()
        zip_data = _make_zip({"hello.txt": b"world"})
        result = extract(zip_data, tmp_path)
        assert "hello.txt" in result
        assert (tmp_path / "hello.txt").read_bytes() == b"world"

    def test_dotdot_prefix_blocked(self, tmp_path):
        extract = _get_extract_zip()
        zip_data = _make_zip({"../escape.txt": b"bad"})
        result = extract(zip_data, tmp_path)
        assert result == []

    def test_nested_traversal_blocked(self, tmp_path):
        """The real bug: nested/../../escape.txt bypassed the old startswith check."""
        extract = _get_extract_zip()
        zip_data = _make_zip({"nested/../../escape.txt": b"bad"})
        result = extract(zip_data, tmp_path)
        assert result == []
        assert not (tmp_path.parent / "escape.txt").exists()

    def test_absolute_path_blocked(self, tmp_path):
        extract = _get_extract_zip()
        zip_data = _make_zip({"/etc/passwd": b"bad"})
        result = extract(zip_data, tmp_path)
        assert result == []


class TestImportSkillNameTraversal:
    def test_malicious_record_name_sanitized(self, tmp_path):
        from openspace.cloud.client import OpenSpaceClient

        client = OpenSpaceClient.__new__(OpenSpaceClient)
        target_dir = tmp_path / "skills"
        target_dir.mkdir()

        malicious_name = "../../escapedir"
        skill_id = "safe_skill_id"
        zip_data = _make_zip({"SKILL.md": b"---\nname: test\n---\ncontent"})

        with patch.object(client, "fetch_record", return_value={"name": malicious_name}), \
             patch.object(client, "download_artifact", return_value=zip_data):
            result = client.import_skill(skill_id, target_dir)

        assert result["status"] == "success"
        resolved = Path(result["local_path"]).resolve()
        assert resolved.is_relative_to(target_dir.resolve())
        assert not (tmp_path.parent / "escapedir").exists()

    def test_normal_record_name_works(self, tmp_path):
        from openspace.cloud.client import OpenSpaceClient

        client = OpenSpaceClient.__new__(OpenSpaceClient)
        target_dir = tmp_path / "skills"
        target_dir.mkdir()

        zip_data = _make_zip({"SKILL.md": b"---\nname: test\n---\ncontent"})

        with patch.object(client, "fetch_record", return_value={"name": "my-skill"}), \
             patch.object(client, "download_artifact", return_value=zip_data):
            result = client.import_skill("some_id", target_dir)

        assert result["status"] == "success"
        assert (target_dir / "my-skill" / "SKILL.md").exists()
