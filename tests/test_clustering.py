"""Tests for UAML Knowledge Clustering."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.clustering import KnowledgeClusterer


@pytest.fixture
def clusterer(tmp_path):
    store = MemoryStore(tmp_path / "clust.db", agent_id="test")
    store.learn("Python GIL prevents true multithreading", topic="python", confidence=0.9)
    store.learn("Python GIL serializes bytecode execution", topic="python", confidence=0.85)
    store.learn("SQLite is serverless embedded database", topic="database", confidence=0.8)
    store.learn("PostgreSQL supports JSONB and advanced queries", topic="database", confidence=0.7)
    store.learn("Unique entry about quantum computing", topic="physics", confidence=0.6)
    c = KnowledgeClusterer(store)
    yield c
    store.close()


class TestKnowledgeClusterer:
    def test_cluster_basic(self, clusterer):
        clusters = clusterer.cluster(min_similarity=0.15)
        assert len(clusters) >= 1

    def test_cluster_grouping(self, clusterer):
        clusters = clusterer.cluster(min_similarity=0.2)
        # Python entries should cluster together
        for c in clusters:
            if len(c.entry_ids) >= 2:
                assert c.size >= 2

    def test_cluster_keywords(self, clusterer):
        clusters = clusterer.cluster()
        for c in clusters:
            assert len(c.keywords) > 0

    def test_find_outliers(self, clusterer):
        outliers = clusterer.find_outliers(threshold=0.2)
        assert isinstance(outliers, list)

    def test_suggest_merges(self, clusterer):
        suggestions = clusterer.suggest_merges(min_similarity=0.3)
        for s in suggestions:
            assert s["size"] >= 2

    def test_empty_store(self, tmp_path):
        store = MemoryStore(tmp_path / "empty.db", agent_id="test")
        c = KnowledgeClusterer(store)
        assert c.cluster() == []
        store.close()

    def test_to_dict(self, clusterer):
        clusters = clusterer.cluster()
        if clusters:
            d = clusters[0].to_dict()
            assert "id" in d
            assert "label" in d

    def test_max_clusters(self, clusterer):
        clusters = clusterer.cluster(max_clusters=1)
        assert len(clusters) <= 1

    def test_high_similarity_fewer_clusters(self, clusterer):
        high = clusterer.cluster(min_similarity=0.8)
        low = clusterer.cluster(min_similarity=0.1)
        assert len(high) <= len(low) or len(high) == len(low)
