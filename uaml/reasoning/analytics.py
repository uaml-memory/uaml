# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Search Analytics — track and analyze search patterns.

Provides insights into how knowledge is accessed, what's popular,
what's never queried, and search effectiveness.

Usage:
    from uaml.reasoning.analytics import SearchAnalytics

    analytics = SearchAnalytics(store)
    analytics.record_search("python GIL", results_count=5, latency_ms=12.3)
    report = analytics.report()
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional


@dataclass
class SearchEvent:
    """A recorded search event."""
    query: str
    results_count: int
    latency_ms: float
    timestamp: float
    agent_id: str = ""
    topic_filter: str = ""


class SearchAnalytics:
    """Track and analyze search patterns."""

    def __init__(self, store=None):
        self.store = store
        self._events: list[SearchEvent] = []

    def record_search(
        self,
        query: str,
        results_count: int = 0,
        latency_ms: float = 0.0,
        agent_id: str = "",
        topic_filter: str = "",
    ) -> None:
        """Record a search event."""
        self._events.append(SearchEvent(
            query=query,
            results_count=results_count,
            latency_ms=latency_ms,
            timestamp=time.time(),
            agent_id=agent_id,
            topic_filter=topic_filter,
        ))

    def report(self, *, last_hours: int = 24) -> dict:
        """Generate analytics report."""
        cutoff = time.time() - (last_hours * 3600)
        recent = [e for e in self._events if e.timestamp >= cutoff]

        if not recent:
            return {
                "total_searches": 0,
                "avg_latency_ms": 0,
                "avg_results": 0,
                "zero_result_rate": 0,
                "top_queries": [],
                "top_topics": [],
                "by_agent": {},
            }

        latencies = [e.latency_ms for e in recent]
        zero_results = sum(1 for e in recent if e.results_count == 0)

        query_counts = Counter(e.query for e in recent)
        topic_counts = Counter(e.topic_filter for e in recent if e.topic_filter)
        agent_counts = Counter(e.agent_id for e in recent if e.agent_id)

        return {
            "total_searches": len(recent),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
            "avg_results": round(sum(e.results_count for e in recent) / len(recent), 2),
            "zero_result_rate": round(zero_results / len(recent), 4),
            "top_queries": [
                {"query": q, "count": c}
                for q, c in query_counts.most_common(10)
            ],
            "top_topics": [
                {"topic": t, "count": c}
                for t, c in topic_counts.most_common(10)
            ],
            "by_agent": dict(agent_counts),
        }

    def slow_queries(self, threshold_ms: float = 100.0) -> list[SearchEvent]:
        """Get queries slower than threshold."""
        return [e for e in self._events if e.latency_ms > threshold_ms]

    def failed_queries(self) -> list[SearchEvent]:
        """Get queries that returned zero results."""
        return [e for e in self._events if e.results_count == 0]

    def query_frequency(self) -> list[dict]:
        """Get query frequency distribution."""
        counts = Counter(e.query for e in self._events)
        return [
            {"query": q, "count": c, "pct": round(c / len(self._events) * 100, 1)}
            for q, c in counts.most_common(20)
        ]

    def clear(self, *, before: Optional[float] = None) -> int:
        """Clear recorded events. Returns count cleared."""
        if before is None:
            count = len(self._events)
            self._events.clear()
            return count

        old_len = len(self._events)
        self._events = [e for e in self._events if e.timestamp >= before]
        return old_len - len(self._events)
