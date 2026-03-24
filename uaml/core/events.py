# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Event Store — event sourcing for knowledge mutations.

Records all state changes as immutable events, enabling replay,
audit, and temporal queries.

Usage:
    from uaml.core.events import EventStore, EventType

    es = EventStore(store)
    es.emit("learn", entry_id=1, data={"topic": "python"})
    events = es.replay(entry_id=1)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from uaml.core.store import MemoryStore


@dataclass
class Event:
    """An immutable event record."""
    id: int
    event_type: str
    entry_id: int
    agent_id: str
    data: dict
    timestamp: str


class EventStore:
    """Append-only event store for knowledge mutations."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()
        self._listeners: dict[str, list[Callable]] = {}

    def _ensure_table(self):
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entry_id INTEGER DEFAULT 0,
                agent_id TEXT DEFAULT '',
                data TEXT DEFAULT '{}',
                ts TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
            )
        """)
        self.store._conn.commit()

    def emit(
        self,
        event_type: str,
        *,
        entry_id: int = 0,
        agent_id: str = "",
        data: Optional[dict] = None,
    ) -> int:
        """Emit an event. Returns event ID."""
        cursor = self.store._conn.execute(
            "INSERT INTO event_log (event_type, entry_id, agent_id, data) VALUES (?, ?, ?, ?)",
            (event_type, entry_id, agent_id, json.dumps(data or {})),
        )
        self.store._conn.commit()

        event = Event(
            id=cursor.lastrowid,
            event_type=event_type,
            entry_id=entry_id,
            agent_id=agent_id,
            data=data or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Notify listeners
        for handler in self._listeners.get(event_type, []):
            try:
                handler(event)
            except Exception:
                pass

        return cursor.lastrowid

    def replay(
        self,
        *,
        entry_id: Optional[int] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Replay events with optional filters."""
        where = []
        params: list = []

        if entry_id is not None:
            where.append("entry_id = ?")
            params.append(entry_id)
        if event_type:
            where.append("event_type = ?")
            params.append(event_type)
        if since:
            where.append("ts >= ?")
            params.append(since)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.store._conn.execute(
            f"SELECT * FROM event_log {where_clause} ORDER BY ts ASC LIMIT ?",
            params + [limit],
        ).fetchall()

        return [
            Event(
                id=r["id"],
                event_type=r["event_type"],
                entry_id=r["entry_id"],
                agent_id=r["agent_id"],
                data=json.loads(r["data"]),
                timestamp=r["ts"],
            )
            for r in rows
        ]

    def on(self, event_type: str, handler: Callable) -> None:
        """Register event listener."""
        self._listeners.setdefault(event_type, [])
        self._listeners[event_type].append(handler)

    def count(self, event_type: Optional[str] = None) -> int:
        """Count events."""
        if event_type:
            return self.store._conn.execute(
                "SELECT COUNT(*) FROM event_log WHERE event_type = ?",
                (event_type,),
            ).fetchone()[0]
        return self.store._conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]

    def stats(self) -> dict:
        """Event statistics."""
        from collections import Counter
        rows = self.store._conn.execute("SELECT event_type FROM event_log").fetchall()
        types = Counter(r["event_type"] for r in rows)
        return {
            "total_events": len(rows),
            "by_type": dict(types),
        }
