"""Tests for UAML Metrics."""

from __future__ import annotations

import time
import pytest

from uaml.core.metrics import MetricsCollector, get_metrics


class TestMetricsCollector:
    def test_track_operation(self):
        m = MetricsCollector()
        with m.track("search"):
            time.sleep(0.01)

        stats = m.get_stats("search")
        assert stats is not None
        assert stats.count == 1
        assert stats.avg_ms >= 5  # At least 5ms

    def test_record_error(self):
        m = MetricsCollector()
        m.record("learn", 5.0, error=True)
        m.record("learn", 3.0)

        stats = m.get_stats("learn")
        assert stats.count == 2
        assert stats.errors == 1
        assert stats.error_rate == 0.5

    def test_summary(self):
        m = MetricsCollector()
        m.record("search", 10.0)
        m.record("search", 20.0)
        m.record("learn", 5.0)

        summary = m.summary()
        assert summary["total_operations"] == 3
        assert "search" in summary["operations"]
        assert summary["operations"]["search"]["count"] == 2
        assert summary["operations"]["search"]["avg_ms"] == 15.0

    def test_min_max(self):
        m = MetricsCollector()
        m.record("op", 5.0)
        m.record("op", 15.0)
        m.record("op", 10.0)

        stats = m.get_stats("op")
        assert stats.min_ms == 5.0
        assert stats.max_ms == 15.0

    def test_reset(self):
        m = MetricsCollector()
        m.record("op", 10.0)
        m.reset()
        assert m.get_stats("op") is None
        assert m.summary()["total_operations"] == 0

    def test_recent_history(self):
        m = MetricsCollector()
        m.record("a", 1.0)
        m.record("b", 2.0)
        recent = m.recent(limit=10)
        assert len(recent) == 2
        assert recent[0]["op"] == "a"

    def test_global_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_exception_in_track(self):
        m = MetricsCollector()
        with pytest.raises(ValueError):
            with m.track("fail"):
                raise ValueError("boom")
        stats = m.get_stats("fail")
        assert stats.errors == 1
