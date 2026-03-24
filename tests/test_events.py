"""Tests for UAML Event Store."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.events import EventStore


@pytest.fixture
def es(tmp_path):
    store = MemoryStore(tmp_path / "ev.db", agent_id="test")
    e = EventStore(store)
    yield e
    store.close()


class TestEventStore:
    def test_emit(self, es):
        eid = es.emit("learn", entry_id=1, agent_id="cyril", data={"topic": "python"})
        assert eid > 0

    def test_replay(self, es):
        es.emit("learn", entry_id=1)
        es.emit("update", entry_id=1)
        events = es.replay(entry_id=1)
        assert len(events) == 2
        assert events[0].event_type == "learn"

    def test_replay_filter_type(self, es):
        es.emit("learn", entry_id=1)
        es.emit("delete", entry_id=2)
        events = es.replay(event_type="learn")
        assert all(e.event_type == "learn" for e in events)

    def test_listener(self, es):
        received = []
        es.on("learn", lambda e: received.append(e))
        es.emit("learn", entry_id=1)
        assert len(received) == 1

    def test_count(self, es):
        es.emit("learn")
        es.emit("learn")
        es.emit("delete")
        assert es.count() == 3
        assert es.count("learn") == 2

    def test_stats(self, es):
        es.emit("learn")
        es.emit("update")
        stats = es.stats()
        assert stats["total_events"] == 2
        assert "learn" in stats["by_type"]

    def test_data_preserved(self, es):
        es.emit("learn", data={"key": "value", "nested": {"a": 1}})
        events = es.replay()
        assert events[0].data["key"] == "value"
        assert events[0].data["nested"]["a"] == 1

    def test_replay_since(self, es):
        es.emit("learn")
        events = es.replay(since="2020-01-01")
        assert len(events) >= 1

    def test_empty_replay(self, es):
        events = es.replay(entry_id=999)
        assert events == []

    def test_listener_error_handled(self, es):
        es.on("learn", lambda e: 1/0)  # Will raise
        eid = es.emit("learn")  # Should not crash
        assert eid > 0
