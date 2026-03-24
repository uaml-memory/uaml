# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Metrics — lightweight instrumentation for memory operations.

Collects operation counts, latencies, and error rates without
external dependencies. Designed for observability dashboards.

Usage:
    from uaml.core.metrics import MetricsCollector

    metrics = MetricsCollector()
    with metrics.track("search"):
        results = store.search("query")

    print(metrics.summary())
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional


@dataclass
class OperationStats:
    """Stats for a single operation type."""
    count: int = 0
    errors: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.count if self.count > 0 else 0.0

    @property
    def error_rate(self) -> float:
        return self.errors / self.count if self.count > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "errors": self.errors,
            "error_rate": round(self.error_rate, 4),
            "avg_ms": round(self.avg_ms, 2),
            "min_ms": round(self.min_ms, 2) if self.min_ms != float("inf") else 0,
            "max_ms": round(self.max_ms, 2),
            "total_ms": round(self.total_ms, 2),
        }


class _Timer:
    """Context manager for tracking operation duration."""

    def __init__(self, collector: "MetricsCollector", operation: str):
        self._collector = collector
        self._operation = operation
        self._start = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._collector.record(self._operation, elapsed_ms, error=exc_type is not None)
        return False  # Don't suppress exceptions


class MetricsCollector:
    """Thread-safe metrics collector for UAML operations."""

    def __init__(self, *, max_history: int = 1000):
        self._stats: dict[str, OperationStats] = defaultdict(OperationStats)
        self._history: list[dict] = []
        self._max_history = max_history
        self._lock = threading.Lock()
        self._start_time = time.monotonic()

    def track(self, operation: str) -> _Timer:
        """Context manager to track an operation's duration.

        Usage:
            with metrics.track("search"):
                store.search("query")
        """
        return _Timer(self, operation)

    def record(self, operation: str, elapsed_ms: float, *, error: bool = False) -> None:
        """Record a completed operation."""
        with self._lock:
            stats = self._stats[operation]
            stats.count += 1
            stats.total_ms += elapsed_ms
            stats.min_ms = min(stats.min_ms, elapsed_ms)
            stats.max_ms = max(stats.max_ms, elapsed_ms)
            if error:
                stats.errors += 1

            if len(self._history) < self._max_history:
                self._history.append({
                    "op": operation,
                    "ms": round(elapsed_ms, 2),
                    "error": error,
                    "ts": time.time(),
                })

    def get_stats(self, operation: str) -> Optional[OperationStats]:
        """Get stats for a specific operation."""
        with self._lock:
            return self._stats.get(operation)

    def summary(self) -> dict:
        """Get a summary of all collected metrics."""
        with self._lock:
            uptime_s = time.monotonic() - self._start_time
            total_ops = sum(s.count for s in self._stats.values())
            total_errors = sum(s.errors for s in self._stats.values())

            return {
                "uptime_seconds": round(uptime_s, 1),
                "total_operations": total_ops,
                "total_errors": total_errors,
                "operations": {
                    op: stats.to_dict()
                    for op, stats in sorted(self._stats.items())
                },
            }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._stats.clear()
            self._history.clear()
            self._start_time = time.monotonic()

    def recent(self, limit: int = 20) -> list[dict]:
        """Get recent operation history."""
        with self._lock:
            return list(self._history[-limit:])


# Global singleton (optional convenience)
_global: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get or create the global MetricsCollector."""
    global _global
    if _global is None:
        _global = MetricsCollector()
    return _global
