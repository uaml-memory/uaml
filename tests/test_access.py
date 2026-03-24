"""Tests for UAML Access Logger."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.audit.access import AccessLogger


@pytest.fixture
def logger(tmp_path):
    store = MemoryStore(tmp_path / "acc.db", agent_id="test")
    store.learn("Test entry", topic="test")
    l = AccessLogger(store)
    l.log_access("cyril", 1, "read")
    l.log_access("metod", 1, "read")
    l.log_access("cyril", 1, "update", "modified content")
    yield l
    store.close()


class TestAccessLogger:
    def test_log_access(self, logger):
        rid = logger.log_access("cyril", 1, "read")
        assert rid > 0

    def test_access_report(self, logger):
        report = logger.access_report(1)
        assert report["total_accesses"] >= 3
        assert "cyril" in report["by_agent"]

    def test_agent_activity(self, logger):
        activity = logger.agent_activity("cyril")
        assert activity["total_actions"] >= 2

    def test_recent(self, logger):
        records = logger.recent(limit=10)
        assert len(records) >= 3
        assert records[0].action in ("read", "update")

    def test_purge_old(self, logger):
        # Nothing old enough to purge
        removed = logger.purge_old(days=1)
        assert removed == 0

    def test_empty_report(self, logger):
        report = logger.access_report(999)
        assert report["total_accesses"] == 0

    def test_details(self, logger):
        records = logger.recent()
        detail_records = [r for r in records if r.details]
        assert len(detail_records) >= 1
