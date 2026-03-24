"""Tests for UAML Temporal Reasoning."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from uaml.core.store import MemoryStore
from uaml.reasoning.temporal import TemporalReasoner


@pytest.fixture
def store_with_data(tmp_path):
    store = MemoryStore(tmp_path / "temporal.db", agent_id="test")

    # Recent entry
    store.learn("Python 3.12 is the current version", topic="python", confidence=0.9)

    # Manually insert an old entry
    old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    store._conn.execute(
        """INSERT INTO knowledge (content, topic, summary, confidence,
           data_layer, source_type, source_origin, created_at, updated_at, agent_id)
           VALUES (?, ?, ?, ?, 'knowledge', 'manual', 'external', ?, ?, 'test')""",
        ("Python 3.10 is recommended", "python", "Old Python version",
         0.7, old_date, old_date),
    )
    store._conn.commit()

    # Another topic
    store.learn("Deploy to 192.168.1.100", topic="deployment", confidence=0.8)

    yield store
    store.close()


class TestTemporalReasoner:
    def test_build_timeline(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        timeline = reasoner.build_timeline()
        assert len(timeline) >= 2
        # Should be sorted by created_at ASC
        assert timeline[0].timestamp <= timeline[-1].timestamp

    def test_timeline_topic_filter(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        timeline = reasoner.build_timeline(topic="python")
        assert all("python" in e.topic for e in timeline)

    def test_find_stale(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        stale = reasoner.find_stale(max_age_days=90)
        assert len(stale) >= 1
        assert stale[0].age_days > 90

    def test_no_stale_with_high_threshold(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        stale = reasoner.find_stale(max_age_days=365)
        assert len(stale) == 0

    def test_detect_conflicts(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        conflicts = reasoner.detect_conflicts(topic="python")
        assert len(conflicts) >= 1
        assert conflicts[0].gap_days > 0

    def test_no_conflicts_without_topic(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        conflicts = reasoner.detect_conflicts()
        assert conflicts == []

    def test_freshness_score(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        # Recent entry should have high freshness
        score = reasoner.freshness_score(1)
        assert score > 0.8

    def test_freshness_old_entry(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        # Old entry (120 days, half_life=30) → ~0.0625
        score = reasoner.freshness_score(2, half_life_days=30)
        assert score < 0.2

    def test_freshness_missing_entry(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        score = reasoner.freshness_score(999)
        assert score == 0.0

    def test_knowledge_age_stats(self, store_with_data):
        reasoner = TemporalReasoner(store_with_data)
        stats = reasoner.knowledge_age_stats()
        assert stats["total"] >= 2
        assert "buckets" in stats
        assert stats["buckets"]["today"] >= 1
        assert stats["buckets"]["older"] >= 1
