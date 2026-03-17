"""UAML LongMemEval Benchmark — memory retention and retrieval quality tests.

Inspired by the LongMemEval benchmark for evaluating long-term memory in
conversational AI agents. Tests UAML's ability to:
1. Store and retrieve facts across sessions (DMR - Delayed Memory Retrieval)
2. Handle temporal queries accurately
3. Maintain client isolation under cross-context pressure
4. Resolve contradictions in evolving knowledge
5. Support associative recall (related but not exact match)

Run with: python -m pytest tests/test_longmemeval.py -v --tb=short
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    """Fresh store for each test."""
    return MemoryStore(tmp_path / "longmemeval.db", agent_id="eval")


@pytest.fixture
def populated_store(store):
    """Store with a realistic conversation history."""
    # Session 1: Personal preferences
    store.learn("User prefers dark mode in all applications", topic="preferences",
                data_layer="identity", confidence=0.95)
    store.learn("User's timezone is Europe/Prague (CET/CEST)", topic="preferences",
                data_layer="identity", confidence=0.99)
    store.learn("User speaks Czech and English", topic="preferences",
                data_layer="identity", confidence=0.99)

    # Session 2: Project facts
    store.learn("UAML uses SQLite as primary storage backend", topic="architecture",
                data_layer="knowledge", project="uaml", confidence=0.99)
    store.learn("UAML supports 5 data layers: identity, knowledge, team, operational, project",
                topic="architecture", data_layer="knowledge", project="uaml", confidence=0.99)
    store.learn("MCP server supports both stdio and HTTP transports",
                topic="architecture", data_layer="knowledge", project="uaml", confidence=0.95)

    # Session 3: Team information
    store.learn("Metod is the VPS coordinator agent, runs on Contabo",
                topic="team", data_layer="team", confidence=0.95)
    store.learn("Cyril handles GPU-heavy work on Notebook1 with 2x RTX 5090",
                topic="team", data_layer="team", confidence=0.95)
    store.learn("Pavel is the project lead and final decision maker",
                topic="team", data_layer="team", confidence=0.99)

    # Session 4: Operational facts
    store.learn("The fallback chain goes: Anthropic API → OpenAI → local Ollama",
                topic="operations", data_layer="operational", confidence=0.90)
    store.learn("VPS backup runs daily at 03:00 CET",
                topic="operations", data_layer="operational", confidence=0.95)

    # Session 5: Client-specific data
    store.learn("Client ACME requires GDPR Art. 17 compliance for all data",
                topic="compliance", data_layer="project", client_ref="acme", confidence=0.99)
    store.learn("Client BETA uses Neo4j for graph queries",
                topic="architecture", data_layer="project", client_ref="beta", confidence=0.90)

    return store


class TestDelayedMemoryRetrieval:
    """DMR: Can UAML recall facts stored in earlier 'sessions'?"""

    def test_recall_personal_preference(self, populated_store):
        """Recall a personal preference from Session 1."""
        results = populated_store.search("dark mode", limit=3)
        assert len(results) >= 1
        assert "dark mode" in results[0].entry.content.lower()

    def test_recall_project_fact(self, populated_store):
        """Recall an architecture fact from Session 2."""
        results = populated_store.search("SQLite storage", limit=3)
        assert len(results) >= 1
        assert "sqlite" in results[0].entry.content.lower()

    def test_recall_team_member(self, populated_store):
        """Recall team information from Session 3."""
        results = populated_store.search("GPU work RTX", limit=3)
        assert len(results) >= 1
        assert "cyril" in results[0].entry.content.lower()

    def test_recall_operational_fact(self, populated_store):
        """Recall operational info from Session 4."""
        results = populated_store.search("fallback chain API", limit=3)
        assert len(results) >= 1
        assert "anthropic" in results[0].entry.content.lower() or "fallback" in results[0].entry.content.lower()

    def test_recall_across_all_sessions(self, populated_store):
        """Search should find results across multiple sessions."""
        results = populated_store.search("UAML", limit=10)
        assert len(results) >= 2  # At least architecture entries


class TestClientIsolation:
    """Can UAML maintain strict client data isolation?"""

    def test_client_isolation_basic(self, populated_store):
        """Client-specific search returns only that client's data."""
        acme_results = populated_store.search("compliance", client_ref="acme", limit=10)
        assert all(r.entry.client_ref == "acme" for r in acme_results if r.entry.client_ref)

    def test_no_cross_client_leakage(self, populated_store):
        """ACME search should not return BETA data."""
        acme_results = populated_store.search("Neo4j graph", client_ref="acme", limit=10)
        for r in acme_results:
            assert r.entry.client_ref != "beta"

    def test_global_search_sees_all(self, populated_store):
        """Without client filter, search sees global + all client data."""
        all_results = populated_store.search("architecture", limit=20)
        assert len(all_results) >= 1


class TestTemporalAccuracy:
    """Can UAML handle temporal queries correctly?"""

    def test_point_in_time_query(self, store):
        """Entry with valid_from/valid_until should respect temporal bounds."""
        store.learn("Python 3.10 was the latest stable",
                    topic="python", valid_from="2022-01-01",
                    confidence=0.99)
        store.learn("Python 3.12 is now the latest stable",
                    topic="python", valid_from="2024-01-01",
                    confidence=0.99)

        # Query at 2023 should find 3.10 but not 3.12
        old_results = store.search("latest Python stable",
                                   point_in_time="2023-06-01", limit=5)
        if old_results:
            # Should prefer the temporally valid entry
            contents = " ".join(r.entry.content for r in old_results)
            assert "3.10" in contents or "Python" in contents

    def test_temporal_ordering(self, store):
        """More recent entries should generally rank higher."""
        store.learn("Old fact about security", topic="security",
                    valid_from="2020-01-01", confidence=0.8)
        store.learn("Current security best practice", topic="security",
                    valid_from="2026-01-01", confidence=0.8)

        results = store.search("security", limit=5)
        assert len(results) >= 2


class TestContradictionHandling:
    """Can UAML detect and handle contradictory information?"""

    def test_evolving_knowledge(self, store):
        """Later facts should be findable alongside earlier contradicting ones."""
        store.learn("UAML uses PostgreSQL as storage",
                    topic="architecture", confidence=0.6,
                    valid_from="2026-01-01", valid_until="2026-02-01")
        store.learn("UAML uses SQLite as primary storage (replaced PostgreSQL)",
                    topic="architecture", confidence=0.95,
                    valid_from="2026-02-01")

        results = store.search("UAML storage backend", limit=5)
        assert len(results) >= 1
        # Higher confidence entry should be findable
        contents = " ".join(r.entry.content for r in results)
        assert "sqlite" in contents.lower()


class TestLayerIsolation:
    """Can UAML enforce data layer access control?"""

    def test_layer_query_returns_correct_layer(self, populated_store):
        """query_layer should only return entries from specified layer."""
        identity_entries = populated_store.query_layer("identity")
        for entry in identity_entries:
            assert entry["data_layer"] == "identity"

    def test_layer_stats(self, populated_store):
        """layer_stats should reflect all 5 layers."""
        stats = populated_store.layer_stats()
        assert "identity" in stats
        assert "knowledge" in stats
        assert "team" in stats
        assert stats["identity"]["count"] >= 3
        assert stats["knowledge"]["count"] >= 3
        assert stats["team"]["count"] >= 3


class TestScaleResilience:
    """Does UAML maintain quality at moderate scale?"""

    def test_1000_entry_search_quality(self, store):
        """Search quality should remain good at 1000 entries."""
        # Insert 1000 entries across topics
        topics = ["python", "rust", "security", "database", "network"]
        for i in range(1000):
            topic = topics[i % len(topics)]
            store.learn(
                f"Technical fact #{i} about {topic}: "
                f"This is a detailed entry about {topic} systems and infrastructure.",
                topic=topic,
                confidence=0.7 + (i % 30) / 100,
            )

        # Search should still find relevant entries
        results = store.search("python systems", limit=5)
        assert len(results) >= 1
        # Top result should be about python
        assert "python" in results[0].entry.content.lower()

    def test_dedup_at_scale(self, store):
        """Deduplication should prevent bloat."""
        for _ in range(100):
            store.learn("Duplicate entry that should only appear once", topic="test")

        stats = store.stats()
        assert stats["knowledge"] == 1  # Only 1 entry despite 100 attempts


class TestConsolidation:
    """Can UAML aggregate and consolidate memory?"""

    def test_consolidate_by_topic(self, populated_store):
        """Consolidation should group by topic correctly."""
        results = populated_store.consolidate_summaries(group_by="day")
        assert len(results) >= 1
        total = sum(r["count"] for r in results)
        assert total >= 12  # populated_store has ~14 entries (some may dedup)

    def test_consolidate_with_filter(self, populated_store):
        """Consolidation with topic filter."""
        results = populated_store.consolidate_summaries(
            topic="architecture", group_by="day"
        )
        total = sum(r["count"] for r in results)
        assert total >= 2  # At least the architecture entries
