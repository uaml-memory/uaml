# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Access Logger — track who accessed what and when.

Provides detailed access logging for compliance (GDPR Art. 30,
ISO 27001 A.8.15) and security monitoring.

Usage:
    from uaml.audit.access import AccessLogger

    logger = AccessLogger(store)
    logger.log_access(agent_id="cyril", entry_id=1, action="read")
    report = logger.access_report(entry_id=1)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class AccessRecord:
    """A single access record."""
    id: int
    agent_id: str
    entry_id: int
    action: str
    timestamp: str
    details: str = ""


class AccessLogger:
    """Track and report data access patterns."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self):
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                entry_id INTEGER,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                ts TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
            )
        """)
        self.store._conn.commit()

    def log_access(
        self,
        agent_id: str,
        entry_id: int,
        action: str,
        details: str = "",
    ) -> int:
        """Log an access event. Returns record ID."""
        cursor = self.store._conn.execute(
            "INSERT INTO access_log (agent_id, entry_id, action, details) VALUES (?, ?, ?, ?)",
            (agent_id, entry_id, action, details),
        )
        self.store._conn.commit()
        return cursor.lastrowid

    def access_report(self, entry_id: int) -> dict:
        """Get access report for an entry."""
        rows = self.store._conn.execute(
            "SELECT * FROM access_log WHERE entry_id = ? ORDER BY ts DESC",
            (entry_id,),
        ).fetchall()

        from collections import Counter
        agents = Counter(r["agent_id"] for r in rows)
        actions = Counter(r["action"] for r in rows)

        return {
            "entry_id": entry_id,
            "total_accesses": len(rows),
            "by_agent": dict(agents),
            "by_action": dict(actions),
            "first_access": rows[-1]["ts"] if rows else None,
            "last_access": rows[0]["ts"] if rows else None,
        }

    def agent_activity(self, agent_id: str, *, days: int = 7) -> dict:
        """Get activity report for an agent."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.store._conn.execute(
            "SELECT * FROM access_log WHERE agent_id = ? AND ts >= ? ORDER BY ts DESC",
            (agent_id, cutoff),
        ).fetchall()

        from collections import Counter
        actions = Counter(r["action"] for r in rows)
        entries = set(r["entry_id"] for r in rows if r["entry_id"])

        return {
            "agent_id": agent_id,
            "total_actions": len(rows),
            "unique_entries": len(entries),
            "by_action": dict(actions),
            "period_days": days,
        }

    def recent(self, *, limit: int = 50) -> list[AccessRecord]:
        """Get recent access records."""
        rows = self.store._conn.execute(
            "SELECT * FROM access_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()

        return [
            AccessRecord(
                id=r["id"],
                agent_id=r["agent_id"],
                entry_id=r["entry_id"] or 0,
                action=r["action"],
                timestamp=r["ts"],
                details=r["details"] or "",
            )
            for r in rows
        ]

    def purge_old(self, *, days: int = 365) -> int:
        """Purge access logs older than N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = self.store._conn.execute(
            "DELETE FROM access_log WHERE ts < ?", (cutoff,)
        )
        self.store._conn.commit()
        return cursor.rowcount
