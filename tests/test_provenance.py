"""Tests for UAML Provenance Tracker."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.audit.provenance import ProvenanceTracker


@pytest.fixture
def tracker(tmp_path):
    store = MemoryStore(tmp_path / "prov.db", agent_id="test")
    store.learn("Test entry", topic="test")
    t = ProvenanceTracker(store)
    yield t
    store.close()


class TestProvenanceTracker:
    def test_record_origin(self, tracker):
        rid = tracker.record_origin(1, source="api", agent="cyril")
        assert rid > 0

    def test_get_chain(self, tracker):
        tracker.record_origin(1, source="manual", agent="cyril")
        tracker.record_transform(1, "enriched", agent="metod", details="added tags")
        chain = tracker.get_chain(1)
        assert len(chain) == 2
        assert chain[0].action == "created"
        assert chain[1].action == "enriched"

    def test_entry_origin(self, tracker):
        tracker.record_origin(1, source="import", agent="cyril")
        origin = tracker.entry_origin(1)
        assert origin is not None
        assert origin.source == "import"

    def test_no_origin(self, tracker):
        assert tracker.entry_origin(999) is None

    def test_agent_contributions(self, tracker):
        tracker.record_origin(1, source="api", agent="cyril")
        tracker.record_transform(1, "enriched", agent="cyril")
        contrib = tracker.agent_contributions("cyril")
        assert contrib["total_actions"] == 2

    def test_stats(self, tracker):
        tracker.record_origin(1, source="a", agent="x")
        stats = tracker.stats()
        assert stats["total_records"] >= 1

    def test_parent_chain(self, tracker):
        r1 = tracker.record_origin(1, source="api")
        r2 = tracker.record_transform(1, "merged", parent_record_id=r1)
        chain = tracker.get_chain(1)
        assert chain[-1].parent_id == r1

    def test_multiple_entries(self, tracker):
        tracker.record_origin(1, source="a")
        tracker.record_origin(2, source="b")  # entry 2 may not exist but provenance still records
        chain1 = tracker.get_chain(1)
        chain2 = tracker.get_chain(2)
        assert len(chain1) == 1
        assert len(chain2) == 1
