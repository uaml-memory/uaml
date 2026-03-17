"""Tests for UAML Neo4j Sync Engine — uses mock Neo4j driver."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from uaml.core.store import MemoryStore
from uaml.graph.sync import Neo4jSync, SyncStats


# ─── Mock Neo4j Driver ───────────────────────────────────────────────

class MockRecord:
    """Simulates a Neo4j record."""
    def __init__(self, data: dict):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)


class MockResult:
    """Simulates a Neo4j result set."""
    def __init__(self, records: list[dict] = None):
        self._records = [MockRecord(r) for r in (records or [])]
        self._idx = 0

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class MockSession:
    """Simulates a Neo4j session."""
    def __init__(self):
        self.queries: list[tuple[str, dict]] = []
        self._return_data: list[dict] = []

    def run(self, query: str, **kwargs) -> MockResult:
        self.queries.append((query, kwargs))
        return MockResult(self._return_data)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockDriver:
    """Simulates a Neo4j driver."""
    def __init__(self):
        self._session = MockSession()
        self.closed = False

    def session(self, **kwargs) -> MockSession:
        return self._session

    def close(self):
        self.closed = True


# ─── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def store():
    s = MemoryStore(":memory:", agent_id="test")
    yield s
    s.close()


@pytest.fixture
def driver():
    return MockDriver()


@pytest.fixture
def sync(store, driver):
    return Neo4jSync(store, driver=driver)


@pytest.fixture
def populated_sync(store, driver):
    """Sync with populated store."""
    store.learn("Python is great for AI", topic="programming", tags="python,ai", data_layer="knowledge")
    store.learn("Neo4j is a graph database", topic="database", tags="neo4j,graph", data_layer="knowledge")
    store.learn("Team standup notes", topic="team", tags="meeting", data_layer="team")
    return Neo4jSync(store, driver=driver)


# ─── SyncStats ────────────────────────────────────────────────────────

class TestSyncStats:
    def test_empty_stats(self):
        s = SyncStats()
        assert s.total_ops == 0
        assert s.errors == []

    def test_total_ops(self):
        s = SyncStats(nodes_created=3, nodes_updated=2, relationships_created=5)
        assert s.total_ops == 10

    def test_to_dict(self):
        s = SyncStats(nodes_created=1, duration_ms=42.5)
        d = s.to_dict()
        assert d["nodes_created"] == 1
        assert d["duration_ms"] == 42.5
        assert "total_ops" in d


# ─── Initialization ──────────────────────────────────────────────────

class TestInit:
    def test_creates_sync_table(self, sync):
        row = sync.store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='neo4j_sync'"
        ).fetchone()
        assert row is not None

    def test_custom_driver(self, store, driver):
        s = Neo4jSync(store, driver=driver)
        assert s._driver is driver

    def test_import_error_without_neo4j(self, store):
        """Without driver param, should try to import neo4j."""
        # This will either work (if neo4j is installed) or raise ImportError
        try:
            s = Neo4jSync(store, bolt_url="bolt://localhost:7687")
            s.close()
        except ImportError as e:
            assert "neo4j" in str(e).lower()


# ─── Push Knowledge ──────────────────────────────────────────────────

class TestPushKnowledge:
    def test_push_all_empty(self, sync):
        stats = sync.push_all()
        assert stats.nodes_created == 0
        assert stats.errors == []

    def test_push_all(self, populated_sync, driver):
        stats = populated_sync.push_all()
        assert stats.nodes_created == 3
        assert stats.errors == []
        # Verify Cypher queries were sent
        assert len(driver._session.queries) == 3

    def test_push_tracks_sync(self, populated_sync):
        populated_sync.push_all()
        count = populated_sync.store._conn.execute(
            "SELECT COUNT(*) FROM neo4j_sync WHERE entry_type = 'knowledge'"
        ).fetchone()[0]
        assert count == 3

    def test_push_since(self, store, driver):
        store.learn("Old entry", topic="old")
        # Push all first
        sync = Neo4jSync(store, driver=driver)
        sync.push_all()

        old_count = len(driver._session.queries)

        # Add new entry
        store.learn("New entry", topic="new")
        # Push only new
        stats = sync.push_since("2020-01-01")
        # Should include all entries (all created after 2020)
        assert stats.nodes_created >= 1

    def test_push_idempotent(self, populated_sync, driver):
        """Pushing twice should MERGE (not duplicate)."""
        populated_sync.push_all()
        count1 = len(driver._session.queries)
        populated_sync.push_all()
        count2 = len(driver._session.queries)
        # MERGE queries are sent both times (Neo4j handles idempotency)
        assert count2 > count1


# ─── Push Tasks ───────────────────────────────────────────────────────

class TestPushTasks:
    def test_push_with_tasks(self, store, driver):
        store.learn("Some knowledge")
        # Create tasks table and add a task
        store._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                title TEXT,
                status TEXT DEFAULT 'open',
                priority TEXT DEFAULT 'medium',
                project TEXT DEFAULT '',
                agent_id TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        store._conn.execute(
            "INSERT INTO tasks (title, status) VALUES (?, ?)",
            ("Test task", "open")
        )
        store._conn.commit()

        sync = Neo4jSync(store, driver=driver)
        stats = sync.push_all()
        # 1 knowledge + 1 task
        assert stats.nodes_created == 2

    def test_push_without_tasks_table(self, store, driver):
        store.learn("Knowledge only")
        sync = Neo4jSync(store, driver=driver)
        stats = sync.push_all()
        assert stats.nodes_created == 1  # Only knowledge


# ─── Push Reasoning ──────────────────────────────────────────────────

class TestPushReasoning:
    def test_push_with_reasoning(self, store, driver):
        from uaml.core.reasoning import ReasoningTracer

        entry_id = store.learn("Evidence entry", topic="test")
        tracer = ReasoningTracer(store)
        tracer.record(
            decision="Use SQLite",
            reasoning="Lightweight and portable",
            evidence_ids=[entry_id],
            agent_id="test",
        )

        sync = Neo4jSync(store, driver=driver)
        stats = sync.push_all()
        # 1 knowledge + 1 reasoning + 1 evidence relationship
        assert stats.nodes_created == 2
        assert stats.relationships_created == 1


# ─── Sync Status ──────────────────────────────────────────────────────

class TestSyncStatus:
    def test_status_empty(self, sync):
        status = sync.sync_status()
        assert status["synced"]["knowledge"] == 0
        assert status["pending"]["knowledge"] == 0
        assert status["total"]["knowledge"] == 0

    def test_status_after_push(self, populated_sync):
        populated_sync.push_all()
        status = populated_sync.sync_status()
        assert status["synced"]["knowledge"] == 3
        assert status["pending"]["knowledge"] == 0
        assert status["total"]["knowledge"] == 3

    def test_status_with_pending(self, store, driver):
        store.learn("Entry 1")
        store.learn("Entry 2")
        sync = Neo4jSync(store, driver=driver)
        # Don't push — all should be pending
        status = sync.sync_status()
        assert status["pending"]["knowledge"] == 2
        assert status["synced"]["knowledge"] == 0


# ─── Close ────────────────────────────────────────────────────────────

class TestClose:
    def test_close_driver(self, sync, driver):
        sync.close()
        assert driver.closed


# ─── Error Handling ───────────────────────────────────────────────────

class TestErrorHandling:
    def test_cypher_error_captured(self, store):
        """Test that Cypher errors are captured in stats, not raised."""

        class ErrorSession:
            def run(self, query, **kwargs):
                raise RuntimeError("Connection refused")
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass

        class ErrorDriver:
            def session(self, **kwargs): return ErrorSession()
            def close(self): pass

        store.learn("Test entry")
        sync = Neo4jSync(store, driver=ErrorDriver())
        stats = sync.push_all()
        assert stats.nodes_created == 0
        assert len(stats.errors) == 1
        assert "Connection refused" in stats.errors[0]
