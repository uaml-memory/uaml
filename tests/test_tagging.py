"""Tests for UAML Tag Manager."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.tagging import TagManager


@pytest.fixture
def tm(tmp_path):
    store = MemoryStore(tmp_path / "tag.db", agent_id="test")
    store.learn("Python GIL info", topic="python", tags="python,threading")
    store.learn("Database indexing", topic="database", tags="sql,performance")
    store.learn("No tags entry", topic="misc")
    t = TagManager(store)
    yield t
    store.close()


class TestTagManager:
    def test_get_tags(self, tm):
        tags = tm.get_tags(1)
        assert "python" in tags
        assert "threading" in tags

    def test_get_tags_empty(self, tm):
        assert tm.get_tags(3) == []

    def test_add_tags(self, tm):
        result = tm.add_tags(1, ["concurrency", "cpython"])
        assert "concurrency" in result
        assert "python" in result  # existing preserved

    def test_remove_tags(self, tm):
        result = tm.remove_tags(1, ["threading"])
        assert "threading" not in result
        assert "python" in result

    def test_replace_tags(self, tm):
        result = tm.replace_tags(1, ["new_tag"])
        assert result == ["new_tag"]

    def test_find_by_tag(self, tm):
        entries = tm.find_by_tag("python")
        assert len(entries) >= 1
        assert entries[0]["topic"] == "python"

    def test_tag_cloud(self, tm):
        cloud = tm.tag_cloud()
        assert len(cloud) >= 4
        tags = [c["tag"] for c in cloud]
        assert "python" in tags

    def test_rename_tag(self, tm):
        count = tm.rename_tag("python", "python3")
        assert count >= 1
        tags = tm.get_tags(1)
        assert "python3" in tags
        assert "python" not in tags

    def test_normalize(self, tm):
        result = tm.add_tags(3, ["My Tag", "UPPER"])
        assert "my_tag" in result
        assert "upper" in result

    def test_add_duplicate(self, tm):
        tm.add_tags(1, ["python"])  # Already exists
        tags = tm.get_tags(1)
        assert tags.count("python") == 1
