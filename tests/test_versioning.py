"""Tests for UAML Knowledge Versioning."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.versioning import VersionManager


@pytest.fixture
def vm(tmp_path):
    store = MemoryStore(tmp_path / "ver.db", agent_id="test")
    store.learn("Original content", topic="test", summary="Original")
    manager = VersionManager(store)
    yield manager
    store.close()


class TestVersionManager:
    def test_update_creates_version(self, vm):
        ver = vm.update_entry(1, content="Updated content", reason="Fix typo")
        assert ver == 1
        history = vm.get_history(1)
        assert len(history) == 1
        assert history[0].content == "Original content"

    def test_multiple_updates(self, vm):
        vm.update_entry(1, content="Version 2")
        vm.update_entry(1, content="Version 3")
        history = vm.get_history(1)
        assert len(history) == 2
        assert history[0].version == 2  # Most recent first
        assert history[1].version == 1

    def test_rollback(self, vm):
        vm.update_entry(1, content="Changed", reason="test")
        ok = vm.rollback(1, version=1)
        assert ok is True

        # Current content should be original
        row = vm._conn.execute("SELECT content FROM knowledge WHERE id = 1").fetchone()
        assert row["content"] == "Original content"

    def test_rollback_nonexistent(self, vm):
        assert vm.rollback(1, version=999) is False

    def test_diff(self, vm):
        vm.update_entry(1, content="New content", confidence=0.95)
        diff = vm.diff(1, 1, 2)
        # v1 exists (snapshot of original), v2 exists (snapshot before second update... wait)
        # Actually after one update we have v1 only
        # Let's do another update
        vm.update_entry(1, topic="new-topic")
        diff = vm.diff(1, 1, 2)
        assert "changes" in diff
        assert len(diff["changed_fields"]) > 0

    def test_get_version(self, vm):
        vm.update_entry(1, content="Changed")
        v = vm.get_version(1, 1)
        assert v is not None
        assert v.content == "Original content"

    def test_version_not_found(self, vm):
        assert vm.get_version(1, 999) is None

    def test_update_nonexistent_entry(self, vm):
        result = vm.update_entry(999, content="test")
        assert result is None

    def test_version_count(self, vm):
        assert vm.version_count(1) == 0
        vm.update_entry(1, content="v2")
        assert vm.version_count(1) == 1
        vm.update_entry(1, content="v3")
        assert vm.version_count(1) == 2

    def test_partial_update(self, vm):
        vm.update_entry(1, topic="new-topic")
        row = vm._conn.execute("SELECT topic, content FROM knowledge WHERE id = 1").fetchone()
        assert row["topic"] == "new-topic"
        assert row["content"] == "Original content"  # Unchanged
