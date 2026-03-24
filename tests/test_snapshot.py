"""Tests for UAML Snapshot Manager."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.snapshot import SnapshotManager


@pytest.fixture
def sm(tmp_path):
    store = MemoryStore(tmp_path / "snap.db", agent_id="test")
    store.learn("Python GIL info", topic="python", confidence=0.9)
    store.learn("Database tips", topic="database", confidence=0.8)
    s = SnapshotManager(store)
    yield s
    store.close()


class TestSnapshotManager:
    def test_take_snapshot(self, sm):
        snap = sm.take("v1")
        assert snap.total_entries == 2
        assert "python" in snap.topics

    def test_diff_after_add(self, sm):
        sm.take("before")
        sm.store.learn("New entry", topic="new")
        sm.take("after")
        diff = sm.diff("before", "after")
        assert diff.entries_added == 1
        assert diff.net_change == 1
        assert "new" in diff.new_topics

    def test_diff_after_delete(self, sm):
        sm.take("before")
        sm.store.delete_entry(1)
        sm.take("after")
        diff = sm.diff("before", "after")
        assert diff.entries_removed == 1
        assert diff.net_change == -1

    def test_list_snapshots(self, sm):
        sm.take("a")
        sm.take("b")
        lst = sm.list_snapshots()
        assert len(lst) == 2

    def test_get_snapshot(self, sm):
        sm.take("test")
        snap = sm.get("test")
        assert snap is not None
        assert snap.name == "test"

    def test_get_nonexistent(self, sm):
        assert sm.get("nope") is None

    def test_delete_snapshot(self, sm):
        sm.take("temp")
        assert sm.delete("temp") is True
        assert sm.delete("temp") is False

    def test_diff_nonexistent(self, sm):
        assert sm.diff("a", "b") is None

    def test_confidence_change(self, sm):
        sm.take("before")
        sm.store.learn("High confidence", topic="test", confidence=1.0)
        sm.take("after")
        diff = sm.diff("before", "after")
        assert diff.confidence_change != 0

    def test_snapshot_agents(self, sm):
        snap = sm.take("v1")
        assert "test" in snap.agents
