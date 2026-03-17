"""Tests for UAML Knowledge Scoring."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.scoring import KnowledgeScorer


@pytest.fixture
def scorer(tmp_path):
    store = MemoryStore(tmp_path / "score.db", agent_id="test")
    store.learn("Python GIL prevents true multithreading. It serializes bytecode.", topic="python", confidence=0.9)
    store.learn("Short", topic="", confidence=0.3)
    store.learn("SQLite is a serverless embedded database. Great for apps.", topic="database", confidence=0.85)
    s = KnowledgeScorer(store)
    yield s
    store.close()


class TestKnowledgeScorer:
    def test_score_entry(self, scorer):
        score = scorer.score_entry(1)
        assert score is not None
        assert 0 <= score.overall <= 1

    def test_high_quality_scores_higher(self, scorer):
        s1 = scorer.score_entry(1)  # Good entry
        s2 = scorer.score_entry(2)  # Poor entry
        assert s1.overall > s2.overall

    def test_completeness(self, scorer):
        s1 = scorer.score_entry(1)
        s2 = scorer.score_entry(2)
        assert s1.completeness > s2.completeness

    def test_freshness(self, scorer):
        score = scorer.score_entry(1)
        assert score.freshness > 0.9  # Just created

    def test_content_quality(self, scorer):
        s1 = scorer.score_entry(1)
        s2 = scorer.score_entry(2)
        assert s1.content_quality > s2.content_quality

    def test_rank_all(self, scorer):
        ranked = scorer.rank_all()
        assert len(ranked) == 3
        assert ranked[0].overall >= ranked[-1].overall

    def test_low_quality(self, scorer):
        low = scorer.low_quality(threshold=0.5)
        for s in low:
            assert s.overall < 0.5

    def test_nonexistent(self, scorer):
        assert scorer.score_entry(999) is None

    def test_to_dict(self, scorer):
        score = scorer.score_entry(1)
        d = score.to_dict()
        assert "overall" in d
        assert "entry_id" in d

    def test_min_score_filter(self, scorer):
        ranked = scorer.rank_all(min_score=0.5)
        for s in ranked:
            assert s.overall >= 0.5
