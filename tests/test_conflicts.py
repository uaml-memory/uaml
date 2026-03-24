"""Tests for UAML Conflict Resolver."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.conflicts import ConflictResolver


@pytest.fixture
def resolver(tmp_path):
    store = MemoryStore(tmp_path / "conf.db", agent_id="test")
    # Create overlapping entries in same topic
    store.learn("Python GIL prevents true multithreading in CPython interpreter", topic="python", confidence=0.9)
    store.learn("Python GIL prevents true multithreading in the CPython runtime", topic="python", confidence=0.7)
    # Non-overlapping
    store.learn("SQLite is a serverless database engine", topic="database", confidence=0.8)
    r = ConflictResolver(store)
    yield r
    store.close()


class TestConflictResolver:
    def test_detect_conflicts(self, resolver):
        conflicts = resolver.detect()
        assert len(conflicts) >= 1
        assert conflicts[0].topic == "python"

    def test_conflict_severity(self, resolver):
        conflicts = resolver.detect()
        assert conflicts[0].severity in ("high", "medium")

    def test_resolve_keep_newest(self, resolver):
        conflicts = resolver.detect()
        assert resolver.resolve(conflicts[0].id, "keep_newest") is True

    def test_resolve_keep_highest(self, resolver):
        conflicts = resolver.detect()
        assert resolver.resolve(conflicts[0].id, "keep_highest_confidence") is True

    def test_resolve_keep_both(self, resolver):
        conflicts = resolver.detect()
        assert resolver.resolve(conflicts[0].id, "keep_both") is True

    def test_resolve_merge(self, resolver):
        conflicts = resolver.detect()
        assert resolver.resolve(conflicts[0].id, "merge") is True

    def test_resolve_nonexistent(self, resolver):
        assert resolver.resolve(999, "keep_both") is False

    def test_summary(self, resolver):
        resolver.detect()
        summary = resolver.summary()
        assert summary["total_conflicts"] >= 1
        assert "python" in summary["top_topics"]

    def test_filter_by_topic(self, resolver):
        conflicts = resolver.detect(topic="database")
        # No conflicts expected in database topic (only 1 entry)
        assert len(conflicts) == 0

    def test_no_conflicts_different_topics(self, tmp_path):
        store = MemoryStore(tmp_path / "nc.db", agent_id="test")
        store.learn("Python info", topic="python")
        store.learn("Database info", topic="database")
        r = ConflictResolver(store)
        assert len(r.detect()) == 0
        store.close()
