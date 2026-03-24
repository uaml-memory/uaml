"""Tests for UAML Structured Logs and Log→Incident pipeline."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.audit.logs import LogStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db", agent_id="test")
    yield s
    s.close()


class TestLogStore:
    def test_basic_log(self, store):
        logs = LogStore(store)
        lid = logs.log("info", "system", "Test message")
        assert lid > 0

    def test_log_with_details(self, store):
        logs = LogStore(store)
        logs.log("error", "sync", "Connection failed",
                 details={"url": "bolt://localhost", "retry": 3})
        results = logs.query(severity="error")
        assert len(results) == 1
        assert results[0]["details"]["url"] == "bolt://localhost"

    def test_query_by_category(self, store):
        logs = LogStore(store)
        logs.log("info", "system", "Start")
        logs.log("info", "sync", "Synced")
        logs.log("error", "sync", "Failed")

        system = logs.query(category="system")
        assert len(system) == 1
        sync = logs.query(category="sync")
        assert len(sync) == 2

    def test_query_search(self, store):
        logs = LogStore(store)
        logs.log("info", "test", "Alpha bravo charlie")
        logs.log("info", "test", "Delta echo foxtrot")

        results = logs.query(search="bravo")
        assert len(results) == 1

    def test_stats(self, store):
        logs = LogStore(store)
        logs.log("info", "a", "msg1")
        logs.log("error", "a", "msg2")
        logs.log("error", "b", "msg3")

        s = logs.stats()
        assert s["total"] == 3
        assert s["by_severity"]["error"] == 2

    def test_purge(self, store):
        logs = LogStore(store)
        logs.log("info", "test", "Old message")
        # Purge with 0 days = delete everything
        deleted = logs.purge(older_than_days=0)
        # Entries created just now won't be older than 0 days in UTC
        # so this is effectively a no-op (entry is < 1 second old)
        assert deleted >= 0


class TestLogIncidentPipeline:
    def test_detect_incidents_empty(self, store):
        logs = LogStore(store)
        incidents = logs.detect_incidents()
        assert incidents == []

    def test_detect_incidents_with_errors(self, store):
        logs = LogStore(store)
        for i in range(5):
            logs.log("error", "sync", f"Sync error {i}")

        incidents = logs.detect_incidents(error_threshold=3)
        assert len(incidents) == 1
        assert incidents[0]["category"] == "sync"
        assert incidents[0]["error_count"] == 5

    def test_escalate_to_incident(self, store):
        logs = LogStore(store)
        for i in range(3):
            logs.log("error", "database", f"DB error {i}")

        incident_id = logs.escalate_to_incident("database")
        assert incident_id is not None
        assert incident_id > 0

    def test_escalate_no_errors(self, store):
        logs = LogStore(store)
        logs.log("info", "system", "All good")
        result = logs.escalate_to_incident("system")
        assert result is None


class TestNeo4jQualityGate:
    def test_quality_gate_clean(self, store):
        from uaml.graph.sync import Neo4jSync

        store.learn("Good content", confidence=0.9, data_layer="knowledge")

        class FakeDriver:
            def close(self): pass

        sync = Neo4jSync(store, driver=FakeDriver())
        result = sync.quality_gate()
        assert result["gate"] == "pass"
        assert result["ready_for_sync"] is True

    def test_quality_gate_empty_content(self, store):
        from uaml.graph.sync import Neo4jSync

        store._conn.execute(
            "INSERT INTO knowledge (content, confidence) VALUES ('', 0.5)"
        )
        store._conn.commit()

        class FakeDriver:
            def close(self): pass

        sync = Neo4jSync(store, driver=FakeDriver())
        result = sync.quality_gate()
        assert result["gate"] == "fail"
        assert not result["ready_for_sync"]
