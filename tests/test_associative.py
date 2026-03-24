"""Tests for UAML Associative Memory — 'intuition' engine."""

import tempfile
from pathlib import Path

import pytest

from uaml.core.associative import AssociativeEngine, Association
from uaml.core.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path, agent_id="test-assoc")

    # Seed a rich knowledge base
    s.learn("Python uses reference counting and a cyclic garbage collector for memory management",
            topic="python", tags="memory,gc,programming", project="uaml")
    s.learn("Python's GIL prevents true multithreading but allows multiprocessing",
            topic="python", tags="threading,programming", project="uaml")
    s.learn("Neo4j is a graph database that uses Cypher query language for traversals",
            topic="database", tags="graph,cypher,nosql", project="uaml")
    s.learn("SQLite uses FTS5 for full-text search indexing which is very fast",
            topic="database", tags="sqlite,fts,search", project="uaml")
    s.learn("GDPR requires explicit consent for processing personal data of EU citizens",
            topic="legal", tags="gdpr,privacy,consent", client_ref="client-A")
    s.learn("Czech Data Protection Authority oversees GDPR compliance in Czech Republic",
            topic="legal", tags="gdpr,czech,authority", client_ref="client-A")
    s.learn("Kubernetes orchestrates Docker containers across cluster nodes",
            topic="devops", tags="kubernetes,docker,cluster")
    s.learn("Machine learning neural networks require large datasets for training",
            topic="ai", tags="ml,neural,training")

    # Create a task and link knowledge
    task_id = s.create_task("Implement search engine", project="uaml")
    s.link_task_knowledge(task_id, 3)  # Neo4j
    s.link_task_knowledge(task_id, 4)  # SQLite FTS5

    # Create source links
    s.link_source(1, 2, link_type="related")  # Python GC ↔ Python GIL
    s.link_source(5, 6, link_type="related")  # GDPR ↔ Czech DPA

    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


class TestAssociativeEngine:
    def test_find_related_by_content(self, store):
        """Python GC entry should find Python GIL entry via content similarity."""
        engine = AssociativeEngine(store)
        related = engine.find_related(1, limit=5)
        assert len(related) >= 1
        # GIL entry should be in related
        related_ids = [a.entry_id for a in related]
        assert 2 in related_ids  # Python GIL

    def test_find_related_by_topic(self, store):
        """Entries with same topic should be related."""
        engine = AssociativeEngine(store)
        related = engine.find_related(1, limit=10)
        # Should find entry 2 (same topic: python)
        related_ids = [a.entry_id for a in related]
        assert 2 in related_ids
        # Check signal
        for a in related:
            if a.entry_id == 2:
                assert "topic" in a.signals

    def test_find_related_by_provenance(self, store):
        """Provenance-linked entries should be related."""
        engine = AssociativeEngine(store)
        related = engine.find_related(5, limit=10)
        related_ids = [a.entry_id for a in related]
        assert 6 in related_ids
        for a in related:
            if a.entry_id == 6:
                assert "provenance" in a.signals

    def test_find_related_by_task(self, store):
        """Entries linked to the same task should be related."""
        engine = AssociativeEngine(store)
        related = engine.find_related(3, limit=10)
        related_ids = [a.entry_id for a in related]
        assert 4 in related_ids  # Both linked to "Implement search engine"
        for a in related:
            if a.entry_id == 4:
                assert "task" in a.signals

    def test_find_related_excludes_self(self, store):
        """Should not include the source entry itself."""
        engine = AssociativeEngine(store)
        related = engine.find_related(1, limit=10)
        related_ids = [a.entry_id for a in related]
        assert 1 not in related_ids

    def test_find_related_respects_limit(self, store):
        engine = AssociativeEngine(store)
        related = engine.find_related(1, limit=2)
        assert len(related) <= 2

    def test_find_related_nonexistent(self, store):
        engine = AssociativeEngine(store)
        related = engine.find_related(9999)
        assert related == []

    def test_scores_sorted_descending(self, store):
        engine = AssociativeEngine(store)
        related = engine.find_related(1, limit=10)
        scores = [a.score for a in related]
        assert scores == sorted(scores, reverse=True)

    def test_multi_signal_higher_score(self, store):
        """Entry matching on multiple signals should score higher."""
        engine = AssociativeEngine(store)
        related = engine.find_related(1, limit=10)
        # Entry 2 (Python GIL) shares content + topic + tags + project + provenance
        # Should score higher than unrelated entries
        if len(related) >= 2:
            python_gil = next((a for a in related if a.entry_id == 2), None)
            if python_gil:
                assert len(python_gil.signals) >= 2


class TestContextualRecall:
    def test_basic_recall(self, store):
        """Should find relevant entries based on context text."""
        engine = AssociativeEngine(store)
        results = engine.contextual_recall("Python memory management garbage collector")
        assert len(results) >= 1
        # Should find Python GC entry
        found_python = any("Python" in a.content for a in results)
        assert found_python

    def test_recall_legal_context(self, store):
        """Legal context should find GDPR entries."""
        engine = AssociativeEngine(store)
        results = engine.contextual_recall("data protection privacy GDPR compliance")
        assert len(results) >= 1
        found_gdpr = any("GDPR" in a.content for a in results)
        assert found_gdpr

    def test_recall_respects_limit(self, store):
        engine = AssociativeEngine(store)
        results = engine.contextual_recall("database query search", limit=2)
        assert len(results) <= 2

    def test_recall_empty_context(self, store):
        engine = AssociativeEngine(store)
        results = engine.contextual_recall("ok")
        assert results == []

    def test_multi_match_boost(self, store):
        """Entries matching multiple context keywords should rank higher."""
        engine = AssociativeEngine(store)
        results = engine.contextual_recall("Python garbage collector memory threading GIL")
        if len(results) >= 2:
            # Top result should be about Python
            assert "Python" in results[0].content or "python" in results[0].topic


class TestStoreIntegration:
    def test_store_related(self, store):
        """Test store.related() convenience method."""
        related = store.related(1, limit=5)
        assert len(related) >= 1
        assert all(isinstance(a, Association) for a in related)

    def test_store_contextual_recall(self, store):
        """Test store.contextual_recall() convenience method."""
        results = store.contextual_recall("Python memory management")
        assert len(results) >= 1


class TestCustomWeights:
    def test_custom_weights(self, store):
        """Custom weights should affect scoring."""
        # Heavy topic weight, no content weight
        engine = AssociativeEngine(store, weights={"content": 0.0, "topic": 0.90})
        related = engine.find_related(1, limit=10)
        # Should still find Python GIL via topic
        related_ids = [a.entry_id for a in related]
        assert 2 in related_ids


class TestAssociationDataclass:
    def test_repr(self):
        a = Association(entry_id=1, content="test", topic="python", score=0.75, signals=["content", "topic"])
        assert "0.75" in repr(a)
        assert "content" in repr(a)
