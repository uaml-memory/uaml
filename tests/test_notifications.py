"""Tests for UAML Notifications."""

from __future__ import annotations

import pytest

from uaml.core.notifications import NotificationCenter, EventType


class TestNotificationCenter:
    def test_subscribe_and_emit(self):
        nc = NotificationCenter()
        received = []
        nc.subscribe(EventType.LEARN, lambda e: received.append(e))
        nc.emit(EventType.LEARN, {"topic": "test"})
        assert len(received) == 1
        assert received[0]["topic"] == "test"

    def test_decorator(self):
        nc = NotificationCenter()
        received = []

        @nc.on(EventType.SEARCH)
        def handler(event):
            received.append(event)

        nc.emit(EventType.SEARCH, {"query": "hello"})
        assert len(received) == 1

    def test_filter(self):
        nc = NotificationCenter()
        received = []
        nc.subscribe(
            EventType.LEARN, lambda e: received.append(e),
            filter_fn=lambda e: e.get("topic") == "important",
        )
        nc.emit(EventType.LEARN, {"topic": "boring"})
        nc.emit(EventType.LEARN, {"topic": "important"})
        assert len(received) == 1

    def test_throttle(self):
        nc = NotificationCenter()
        count = [0]
        nc.subscribe(EventType.LEARN, lambda e: count.__setitem__(0, count[0]+1),
                     throttle_ms=10000)
        nc.emit(EventType.LEARN, {})
        nc.emit(EventType.LEARN, {})  # Should be throttled
        assert count[0] == 1

    def test_unsubscribe(self):
        nc = NotificationCenter()
        nc.subscribe(EventType.LEARN, lambda e: None, name="temp")
        assert nc.unsubscribe("temp") == 1

    def test_history(self):
        nc = NotificationCenter()
        nc.subscribe(EventType.LEARN, lambda e: None)
        nc.emit(EventType.LEARN, {})
        nc.emit(EventType.SEARCH, {})
        history = nc.history()
        assert len(history) == 2

    def test_history_filter(self):
        nc = NotificationCenter()
        nc.emit(EventType.LEARN, {})
        nc.emit(EventType.SEARCH, {})
        learn_history = nc.history(event_type=EventType.LEARN)
        assert len(learn_history) == 1

    def test_stats(self):
        nc = NotificationCenter()
        nc.subscribe(EventType.LEARN, lambda e: None)
        nc.subscribe(EventType.SEARCH, lambda e: None)
        stats = nc.stats()
        assert stats["total_subscriptions"] == 2

    def test_error_in_callback(self):
        nc = NotificationCenter()
        nc.subscribe(EventType.LEARN, lambda e: 1/0)
        # Should not raise
        notified = nc.emit(EventType.LEARN, {})
        assert notified == 0  # Errored subscriber doesn't count

    def test_multiple_subscribers(self):
        nc = NotificationCenter()
        results = []
        nc.subscribe(EventType.LEARN, lambda e: results.append("a"))
        nc.subscribe(EventType.LEARN, lambda e: results.append("b"))
        nc.emit(EventType.LEARN, {})
        assert results == ["a", "b"]
