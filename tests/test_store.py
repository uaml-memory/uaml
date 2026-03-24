"""Tests for UAML MemoryStore."""

import os
import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """Create a temporary MemoryStore for testing."""
    db_path = tmp_path / "test_memory.db"
    s = MemoryStore(db_path, agent_id="test-agent")
    yield s
    s.close()


class TestMemoryStore:
    def test_init_creates_db(self, store):
        assert store.db_path.exists()

    def test_learn_basic(self, store):
        entry_id = store.learn("Python is a programming language")
        assert entry_id > 0

    def test_learn_with_metadata(self, store):
        entry_id = store.learn(
            "SQLite uses WAL mode for concurrent reads",
            topic="database",
            tags="sqlite,wal,concurrency",
            confidence=0.95,
            source_ref="https://sqlite.org/wal.html",
        )
        assert entry_id > 0

    def test_learn_dedup(self, store):
        """Identical content should not create duplicate entries."""
        id1 = store.learn("Duplicate test content")
        id2 = store.learn("Duplicate test content")
        assert id1 == id2

    def test_learn_dedup_disabled(self, store):
        """With dedup=False, identical content creates new entry."""
        id1 = store.learn("Duplicate test content", dedup=False)
        id2 = store.learn("Duplicate test content", dedup=False)
        assert id1 != id2

    def test_search_basic(self, store):
        store.learn("Python GIL prevents true multithreading", topic="python")
        store.learn("Rust has no garbage collector", topic="rust")

        results = store.search("GIL multithreading")
        assert len(results) > 0
        assert "GIL" in results[0].entry.content

    def test_search_empty(self, store):
        results = store.search("nonexistent query xyz123")
        assert len(results) == 0

    def test_search_by_topic(self, store):
        store.learn("Python is great", topic="python")
        store.learn("Rust is fast", topic="rust")

        results = store.search("is", topic="python")
        assert len(results) >= 1
        assert all(r.entry.topic == "python" for r in results)

    def test_search_by_project(self, store):
        store.learn("UAML schema design", project="uaml")
        store.learn("ANPR camera setup", project="anpr")

        results = store.search("design setup", project="uaml")
        assert all(r.entry.project == "uaml" for r in results)

    def test_search_by_client(self, store):
        """Client isolation — entries from client A shouldn't appear for client B."""
        store.learn("Client A secret data", client_ref="client_a")
        store.learn("Client B secret data", client_ref="client_b")

        results_a = store.search("secret data", client_ref="client_a")
        assert all(r.entry.client_ref == "client_a" for r in results_a)

    def test_temporal_query(self, store):
        """Point-in-time query — the killer feature."""
        store.learn(
            "Old privacy law applies",
            valid_from="2020-01-01",
            valid_until="2023-12-31",
            topic="law",
        )
        store.learn(
            "New GDPR revision applies",
            valid_from="2024-01-01",
            topic="law",
        )

        # Query at 2022 — should find old law
        results_2022 = store.point_in_time("privacy law", "2022-06-15")
        assert any("Old" in r.entry.content for r in results_2022)

        # Query at 2025 — should find new law
        results_2025 = store.point_in_time("privacy law GDPR", "2025-06-15")
        assert any("GDPR" in r.entry.content for r in results_2025)

    def test_stats(self, store):
        store.learn("Entry 1", topic="test")
        store.learn("Entry 2", topic="test")
        store.learn("Entry 3", topic="other")

        stats = store.stats()
        assert stats["knowledge"] == 3
        assert stats["top_topics"]["test"] == 2

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "ctx_test.db"
        with MemoryStore(db_path) as store:
            store.learn("context manager test")
            results = store.search("context manager")
            assert len(results) > 0

    def test_audit_log(self, store):
        store.learn("Audited entry")
        stats = store.stats()
        assert stats["audit_log"] > 0

    def test_entity_lookup_missing(self, store):
        result = store.get_entity("NonExistentEntity")
        assert result is None

    def test_consolidate_summaries_empty(self, store):
        """Consolidate on empty DB returns empty list."""
        results = store.consolidate_summaries()
        assert results == []

    def test_consolidate_summaries_basic(self, store):
        """Consolidate returns grouped entries."""
        store.learn("Entry A", topic="python")
        store.learn("Entry B", topic="python")
        store.learn("Entry C", topic="rust")

        results = store.consolidate_summaries(group_by="day")
        assert len(results) >= 1
        # All entries should be in today's bucket
        total = sum(r["count"] for r in results)
        assert total == 3
        # Should have sample entries
        assert len(results[0]["sample_entries"]) <= 3
        # Topics should be collected
        topics = results[0]["topics"]
        assert "python" in topics

    def test_consolidate_summaries_with_filter(self, store):
        """Consolidate respects topic filter."""
        store.learn("Python fact", topic="python")
        store.learn("Rust fact", topic="rust")

        results = store.consolidate_summaries(topic="python", group_by="day")
        total = sum(r["count"] for r in results)
        assert total == 1

    def test_proactive_recall_basic(self, store):
        """Proactive recall returns structured result."""
        store.learn("SQLite is used as the primary database", topic="architecture")
        store.learn("PostgreSQL is used for analytics", topic="architecture")

        result = store.proactive_recall("database storage backend")
        assert "memories" in result
        assert "rules" in result
        assert "lessons" in result
        assert "context_summary" in result
        assert len(result["memories"]) >= 1

    def test_proactive_recall_empty(self, store):
        """Proactive recall on empty DB returns empty results."""
        result = store.proactive_recall("anything")
        assert result["memories"] == []
        assert result["context_summary"]["total_found"] == 0

    def test_proactive_recall_with_confidence_filter(self, store):
        """Proactive recall respects min_confidence."""
        store.learn("High confidence fact", topic="test", confidence=0.95)
        store.learn("Low confidence guess", topic="test", confidence=0.3)

        result = store.proactive_recall("fact about testing", min_confidence=0.8)
        # Should only include high confidence entry
        for m in result["memories"]:
            if "confidence" in m:
                assert m["confidence"] >= 0.8
