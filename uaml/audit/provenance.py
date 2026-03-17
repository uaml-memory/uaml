# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Provenance Tracker — track origin and transformation history.

Records complete lineage of knowledge entries: where they came from,
how they were transformed, and who touched them.

Usage:
    from uaml.audit.provenance import ProvenanceTracker

    tracker = ProvenanceTracker(store)
    tracker.record_origin(entry_id=1, source="api", agent="cyril")
    chain = tracker.get_chain(entry_id=1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class ProvenanceRecord:
    """A single provenance record."""
    id: int
    entry_id: int
    action: str  # created, transformed, merged, split, imported, enriched
    agent_id: str
    source: str
    details: str
    timestamp: str
    parent_id: Optional[int] = None  # Previous provenance record


class ProvenanceTracker:
    """Track knowledge provenance and lineage."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self):
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS provenance_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                agent_id TEXT DEFAULT '',
                source TEXT DEFAULT '',
                details TEXT DEFAULT '',
                parent_id INTEGER,
                ts TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
            )
        """)
        self.store._conn.commit()

    def record_origin(
        self,
        entry_id: int,
        source: str,
        agent: str = "",
        details: str = "",
    ) -> int:
        """Record the origin of an entry."""
        return self._record(entry_id, "created", agent, source, details)

    def record_transform(
        self,
        entry_id: int,
        action: str,
        agent: str = "",
        details: str = "",
        parent_record_id: Optional[int] = None,
    ) -> int:
        """Record a transformation of an entry."""
        return self._record(entry_id, action, agent, "", details, parent_record_id)

    def _record(
        self,
        entry_id: int,
        action: str,
        agent: str,
        source: str,
        details: str,
        parent_id: Optional[int] = None,
    ) -> int:
        cursor = self.store._conn.execute(
            """INSERT INTO provenance_log (entry_id, action, agent_id, source, details, parent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entry_id, action, agent, source, details, parent_id),
        )
        self.store._conn.commit()
        return cursor.lastrowid

    def get_chain(self, entry_id: int) -> list[ProvenanceRecord]:
        """Get full provenance chain for an entry."""
        rows = self.store._conn.execute(
            "SELECT * FROM provenance_log WHERE entry_id = ? ORDER BY ts ASC",
            (entry_id,),
        ).fetchall()

        return [
            ProvenanceRecord(
                id=r["id"],
                entry_id=r["entry_id"],
                action=r["action"],
                agent_id=r["agent_id"],
                source=r["source"],
                details=r["details"],
                timestamp=r["ts"],
                parent_id=r["parent_id"],
            )
            for r in rows
        ]

    def entry_origin(self, entry_id: int) -> Optional[ProvenanceRecord]:
        """Get the original creation record."""
        chain = self.get_chain(entry_id)
        created = [r for r in chain if r.action == "created"]
        return created[0] if created else (chain[0] if chain else None)

    def agent_contributions(self, agent_id: str) -> dict:
        """Get contribution summary for an agent."""
        from collections import Counter
        rows = self.store._conn.execute(
            "SELECT action FROM provenance_log WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()

        actions = Counter(r["action"] for r in rows)
        return {
            "agent_id": agent_id,
            "total_actions": len(rows),
            "by_action": dict(actions),
        }

    def stats(self) -> dict:
        """Provenance statistics."""
        total = self.store._conn.execute("SELECT COUNT(*) FROM provenance_log").fetchone()[0]
        from collections import Counter
        rows = self.store._conn.execute("SELECT action FROM provenance_log").fetchall()
        actions = Counter(r["action"] for r in rows)

        return {
            "total_records": total,
            "by_action": dict(actions),
        }
