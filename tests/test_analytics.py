"""Tests for UAML Search Analytics."""

from __future__ import annotations

import pytest
import time

from uaml.reasoning.analytics import SearchAnalytics


@pytest.fixture
def sa():
    analytics = SearchAnalytics()
    analytics.record_search("python GIL", results_count=5, latency_ms=12.3, agent_id="cyril")
    analytics.record_search("database index", results_count=3, latency_ms=8.1, topic_filter="db")
    analytics.record_search("nonexistent", results_count=0, latency_ms=200.0)
    analytics.record_search("python GIL", results_count=4, latency_ms=10.0, agent_id="cyril")
    return analytics


class TestSearchAnalytics:
    def test_report_total(self, sa):
        report = sa.report()
        assert report["total_searches"] == 4

    def test_avg_latency(self, sa):
        report = sa.report()
        assert report["avg_latency_ms"] > 0

    def test_zero_result_rate(self, sa):
        report = sa.report()
        assert report["zero_result_rate"] == 0.25

    def test_top_queries(self, sa):
        report = sa.report()
        assert report["top_queries"][0]["query"] == "python GIL"
        assert report["top_queries"][0]["count"] == 2

    def test_by_agent(self, sa):
        report = sa.report()
        assert report["by_agent"]["cyril"] == 2

    def test_slow_queries(self, sa):
        slow = sa.slow_queries(threshold_ms=100.0)
        assert len(slow) == 1
        assert slow[0].query == "nonexistent"

    def test_failed_queries(self, sa):
        failed = sa.failed_queries()
        assert len(failed) == 1

    def test_query_frequency(self, sa):
        freq = sa.query_frequency()
        assert freq[0]["query"] == "python GIL"
        assert freq[0]["pct"] == 50.0

    def test_clear_all(self, sa):
        count = sa.clear()
        assert count == 4
        assert sa.report()["total_searches"] == 0

    def test_clear_before(self, sa):
        cutoff = time.time() + 1
        count = sa.clear(before=cutoff)
        assert count == 4

    def test_empty_report(self):
        analytics = SearchAnalytics()
        report = analytics.report()
        assert report["total_searches"] == 0
