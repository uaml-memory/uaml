"""Tests for UAML Deduplication Engine."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.dedup import DedupEngine


@pytest.fixture
def engine(tmp_path):
    store = MemoryStore(tmp_path / "dedup.db", agent_id="test")
    # Create exact duplicates
    store.learn("Exact duplicate content here", topic="test", dedup=False)
    store.learn("Exact duplicate content here", topic="test", dedup=False)
    # Create unique entry
    store.learn("Completely different content about something else", topic="other")
    # Create near duplicate
    store.learn("Exact duplicate content here with minor change", topic="test")

    eng = DedupEngine(store)
    yield eng
    store.close()


class TestDedupEngine:
    def test_find_exact_duplicates(self, engine):
        groups = engine.find_exact_duplicates()
        assert len(groups) >= 1
        assert groups[0].similarity == 1.0

    def test_find_near_duplicates(self, engine):
        groups = engine.find_near_duplicates(threshold=0.7)
        # Should find groups with high word overlap
        assert isinstance(groups, list)

    def test_merge_keep_newest(self, engine):
        groups = engine.find_exact_duplicates()
        if groups:
            kept = engine.merge_group(groups[0], strategy="keep_newest")
            assert kept > 0

    def test_merge_keep_highest_confidence(self, tmp_path):
        store = MemoryStore(tmp_path / "conf.db", agent_id="test")
        store.learn("Same content", confidence=0.5, dedup=False)
        store.learn("Same content", confidence=0.9, dedup=False)

        eng = DedupEngine(store)
        groups = eng.find_exact_duplicates()
        if groups:
            kept = eng.merge_group(groups[0], strategy="keep_highest_confidence")
            row = store._conn.execute(
                "SELECT confidence FROM knowledge WHERE id = ?", (kept,)
            ).fetchone()
            assert row["confidence"] == 0.9
        store.close()

    def test_auto_dedup_dry_run(self, engine):
        result = engine.auto_dedup(dry_run=True)
        assert result["dry_run"] is True
        assert result["merged"] == 0
        assert result["exact_groups"] >= 1

    def test_auto_dedup_execute(self, engine):
        result = engine.auto_dedup(dry_run=False, strategy="keep_newest")
        assert result["dry_run"] is False
        assert result["merged"] >= 1

    def test_stats(self, engine):
        stats = engine.stats()
        assert stats["total_entries"] >= 3
        assert "exact_duplicate_groups" in stats

    def test_empty_store(self, tmp_path):
        store = MemoryStore(tmp_path / "empty.db", agent_id="test")
        eng = DedupEngine(store)
        groups = eng.find_exact_duplicates()
        assert groups == []
        store.close()
