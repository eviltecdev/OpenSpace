import json

import pytest

from openspace import mcp_server


@pytest.mark.asyncio
async def test_local_search_skills_does_not_initialize_openspace(monkeypatch, tmp_path):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "demo-local-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: Demo Local Skill
description: Local regression test skill
---

Find me when querying demo local skill.
""",
        encoding="utf-8",
    )

    async def forbidden_get_openspace():
        pytest.fail("_get_openspace should not run for source='local'")

    monkeypatch.setenv("OPENSPACE_HOST_SKILL_DIRS", str(skill_root))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(mcp_server, "_get_openspace", forbidden_get_openspace)
    monkeypatch.setattr(
        "openspace.cloud.embedding.generate_embedding",
        lambda text, api_key=None: None,
    )

    response = await mcp_server.search_skills(
        query="demo local skill",
        source="local",
        limit=5,
        auto_import=False,
    )

    payload = json.loads(response)
    assert payload["count"] >= 1
    assert any(
        item["name"] == "Demo Local Skill"
        for item in payload["results"]
    )


@pytest.mark.asyncio
async def test_local_search_skills_refreshes_registry_between_calls(monkeypatch, tmp_path):
    skill_root = tmp_path / "skills"
    first_skill_dir = skill_root / "first-local-skill"
    first_skill_dir.mkdir(parents=True)
    (first_skill_dir / "SKILL.md").write_text(
        """---
name: First Local Skill
description: First local skill for cache regression coverage
---

First local skill content.
""",
        encoding="utf-8",
    )

    async def forbidden_get_openspace():
        pytest.fail("_get_openspace should not run for source='local'")

    monkeypatch.setenv("OPENSPACE_HOST_SKILL_DIRS", str(skill_root))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setattr(mcp_server, "_get_openspace", forbidden_get_openspace)
    monkeypatch.setattr(
        "openspace.cloud.embedding.generate_embedding",
        lambda text, api_key=None: None,
    )

    first_response = await mcp_server.search_skills(
        query="first local skill",
        source="local",
        limit=5,
        auto_import=False,
    )

    first_payload = json.loads(first_response)
    assert any(
        item["name"] == "First Local Skill"
        for item in first_payload["results"]
    )

    second_skill_dir = skill_root / "second-local-skill"
    second_skill_dir.mkdir(parents=True)
    (second_skill_dir / "SKILL.md").write_text(
        """---
name: Second Local Skill
description: Second local skill created after the first search
---

Second local skill content.
""",
        encoding="utf-8",
    )

    second_response = await mcp_server.search_skills(
        query="second local skill",
        source="local",
        limit=5,
        auto_import=False,
    )

    second_payload = json.loads(second_response)
    assert any(
        item["name"] == "Second Local Skill"
        for item in second_payload["results"]
    )


@pytest.mark.asyncio
async def test_local_search_returns_empty_when_no_registry(monkeypatch):
    """source='local' with no discoverable skills should return empty, not crash."""

    async def forbidden_get_openspace():
        pytest.fail("_get_openspace should not run for source='local'")

    monkeypatch.setattr(mcp_server, "_get_openspace", forbidden_get_openspace)
    monkeypatch.setattr(mcp_server, "_get_local_skill_registry", lambda: None)
    monkeypatch.setattr(
        "openspace.cloud.embedding.generate_embedding",
        lambda text, api_key=None: None,
    )

    response = await mcp_server.search_skills(
        query="anything",
        source="local",
        limit=5,
        auto_import=False,
    )

    payload = json.loads(response)
    assert payload["count"] == 0
    assert payload["results"] == []


@pytest.mark.asyncio
async def test_source_all_still_calls_get_openspace(monkeypatch, tmp_path):
    """source='all' must go through _get_openspace(), not the lightweight path."""
    called = {"openspace": False}

    class FakeRegistry:
        def list_skills(self):
            return []

    class FakeOpenSpace:
        _skill_registry = FakeRegistry()

    async def tracking_get_openspace():
        called["openspace"] = True
        return FakeOpenSpace()

    monkeypatch.delenv("OPENSPACE_HOST_SKILL_DIRS", raising=False)
    monkeypatch.setattr(mcp_server, "_get_openspace", tracking_get_openspace)
    monkeypatch.setattr(
        "openspace.cloud.embedding.generate_embedding",
        lambda text, api_key=None: None,
    )

    await mcp_server.search_skills(
        query="anything",
        source="all",
        limit=5,
        auto_import=False,
    )

    assert called["openspace"], "source='all' should call _get_openspace()"
