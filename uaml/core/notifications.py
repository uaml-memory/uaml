# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Notifications — event-driven alerts for memory operations.

Subscribe to events (learn, search, purge, security) and receive
notifications via callbacks. Supports filtering and throttling.

Usage:
    from uaml.core.notifications import NotificationCenter, EventType

    nc = NotificationCenter()

    @nc.on(EventType.LEARN)
    def on_learn(event):
        print(f"New entry: {event['topic']}")

    nc.emit(EventType.LEARN, {"topic": "test", "id": 1})
"""

from __future__ import annotations

import enum
import time
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


class EventType(enum.Enum):
    """Event types in the UAML system."""
    LEARN = "learn"
    SEARCH = "search"
    UPDATE = "update"
    DELETE = "delete"
    PURGE = "purge"
    EXPORT = "export"
    SECURITY_ALERT = "security_alert"
    COMPLIANCE_ISSUE = "compliance_issue"
    STALE_DETECTED = "stale_detected"
    FEDERATION_SHARE = "federation_share"
    ERROR = "error"


@dataclass
class Subscription:
    """A notification subscription."""
    name: str
    event_type: EventType
    callback: Callable
    filter_fn: Optional[Callable] = None
    throttle_ms: int = 0
    enabled: bool = True
    _last_fired: float = 0.0


class NotificationCenter:
    """Central event notification hub."""

    def __init__(self):
        self._subs: dict[EventType, list[Subscription]] = {e: [] for e in EventType}
        self._history: list[dict] = []
        self._max_history: int = 500
        self._lock = threading.Lock()

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable,
        *,
        name: str = "",
        filter_fn: Optional[Callable] = None,
        throttle_ms: int = 0,
    ) -> Subscription:
        """Subscribe to an event type.

        Args:
            event_type: Event to listen for
            callback: Function to call with event data
            name: Subscriber name
            filter_fn: Optional filter — callback only fires if filter returns True
            throttle_ms: Minimum ms between calls (0 = no throttle)
        """
        sub = Subscription(
            name=name or callback.__name__,
            event_type=event_type,
            callback=callback,
            filter_fn=filter_fn,
            throttle_ms=throttle_ms,
        )
        with self._lock:
            self._subs[event_type].append(sub)
        return sub

    def on(self, event_type: EventType, **kwargs):
        """Decorator to subscribe to an event.

        @nc.on(EventType.LEARN)
        def handler(event):
            ...
        """
        def decorator(fn):
            self.subscribe(event_type, fn, **kwargs)
            return fn
        return decorator

    def unsubscribe(self, name: str) -> int:
        """Remove subscriptions by name."""
        removed = 0
        with self._lock:
            for et in EventType:
                before = len(self._subs[et])
                self._subs[et] = [s for s in self._subs[et] if s.name != name]
                removed += before - len(self._subs[et])
        return removed

    def emit(self, event_type: EventType, data: Optional[dict] = None) -> int:
        """Emit an event. Returns number of subscribers notified."""
        data = data or {}
        data["_event"] = event_type.value
        data["_timestamp"] = time.time()
        notified = 0

        with self._lock:
            subs = list(self._subs[event_type])

        for sub in subs:
            if not sub.enabled:
                continue

            # Apply filter
            if sub.filter_fn and not sub.filter_fn(data):
                continue

            # Apply throttle
            now = time.monotonic() * 1000
            if sub.throttle_ms > 0 and (now - sub._last_fired) < sub.throttle_ms:
                continue

            try:
                sub.callback(data)
                sub._last_fired = now
                notified += 1
            except Exception:
                pass  # Don't let subscriber errors break emission

        # Record history
        with self._lock:
            self._history.append({
                "event": event_type.value,
                "data_keys": list(data.keys()),
                "notified": notified,
                "ts": data["_timestamp"],
            })
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        return notified

    def history(self, limit: int = 20, event_type: Optional[EventType] = None) -> list[dict]:
        """Get recent event history."""
        with self._lock:
            items = self._history
            if event_type:
                items = [h for h in items if h["event"] == event_type.value]
            return list(items[-limit:])

    def stats(self) -> dict:
        """Notification system statistics."""
        with self._lock:
            total = sum(len(s) for s in self._subs.values())
            active = sum(
                sum(1 for s in subs if s.enabled)
                for subs in self._subs.values()
            )
            return {
                "total_subscriptions": total,
                "active_subscriptions": active,
                "history_size": len(self._history),
                "subscriptions": {
                    et.value: len(self._subs[et])
                    for et in EventType
                    if self._subs[et]
                },
            }
