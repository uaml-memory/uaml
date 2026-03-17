"""Tests for UAML Embeddings."""

from __future__ import annotations

import pytest

from uaml.core.embeddings import EmbeddingEngine


@pytest.fixture
def engine():
    return EmbeddingEngine(backend="tfidf")


class TestEmbeddingEngine:
    def test_tfidf_embed(self, engine):
        vec = engine.embed("Python is great for machine learning")
        assert isinstance(vec, list)
        assert len(vec) > 0
        assert all(isinstance(v, float) for v in vec)

    def test_empty_embed(self, engine):
        vec = engine.embed("")
        assert vec == []

    def test_similarity_identical(self, engine):
        score = engine.similarity("Python AI", "Python AI")
        assert score == 1.0

    def test_similarity_related(self, engine):
        score = engine.similarity(
            "Python machine learning artificial intelligence",
            "Machine learning with Python and deep learning",
        )
        assert score > 0.3

    def test_similarity_unrelated(self, engine):
        score = engine.similarity("Python programming", "Cooking recipes pasta")
        assert score == 0.0

    def test_similarity_empty(self, engine):
        assert engine.similarity("", "text") == 0.0
        assert engine.similarity("text", "") == 0.0

    def test_cosine_similarity(self, engine):
        sim = engine.cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert abs(sim - 1.0) < 0.001

    def test_cosine_orthogonal(self, engine):
        sim = engine.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 0.001

    def test_batch_similarity(self, engine):
        docs = ["Python programming", "Machine learning", "Cooking recipes"]
        results = engine.batch_similarity("Python ML", docs)
        assert len(results) == 3
        assert results[0][1] >= results[1][1]  # Sorted by score

    def test_find_most_similar(self, engine):
        docs = ["Python AI framework", "SQLite database", "Machine learning model"]
        results = engine.find_most_similar("Python machine learning", docs, top_k=2)
        assert len(results) <= 2

    def test_find_with_min_score(self, engine):
        docs = ["Python AI", "Cooking pasta", "Baking bread"]
        results = engine.find_most_similar("Python", docs, min_score=0.3)
        assert all(r["score"] >= 0.3 for r in results)

    def test_bow_backend(self):
        engine = EmbeddingEngine(backend="bow")
        vec = engine.embed("hello world hello")
        assert isinstance(vec, list)

    def test_unknown_backend(self):
        engine = EmbeddingEngine(backend="unknown")
        with pytest.raises(ValueError):
            engine.embed("test")

    def test_update_idf(self, engine):
        engine.update_idf(["Python is great", "Python and AI", "Cooking food"])
        assert "python" in engine._idf_cache
        assert engine._doc_count == 3
