# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Snapshot — point-in-time snapshots for comparison.

Creates lightweight snapshots of the knowledge store state
for diffing, rollback planning, and progress tracking.

Usage:
    from uaml.core.snapshot import SnapshotManager

    sm = SnapshotManager(store)
    snap1 = sm.take("before_import")
    # ... do operations ...
    snap2 = sm.take("after_import")
    diff = sm.diff(snap1, snap2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class Snapshot:
    """A point-in-time snapshot of knowledge store state."""
    name: str
    timestamp: str
    total_entries: int
    topics: dict  # topic -> count
    avg_confidence: float
    data_layers: dict  # layer -> count
    agents: list[str]
    entry_ids: set = field(default_factory=set, repr=False)


@dataclass
class SnapshotDiff:
    """Difference between two snapshots."""
    before: str
    after: str
    entries_added: int
    entries_removed: int
    net_change: int
    new_topics: list[str]
    removed_topics: list[str]
    confidence_change: float


class SnapshotManager:
    """Manage knowledge store snapshots."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._snapshots: dict[str, Snapshot] = {}

    def take(self, name: str) -> Snapshot:
        """Take a snapshot of current state."""
        total = self.store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

        # Topic distribution
        topic_rows = self.store._conn.execute(
            "SELECT topic, COUNT(*) as cnt FROM knowledge GROUP BY topic"
        ).fetchall()
        topics = {r["topic"] or "(none)": r["cnt"] for r in topic_rows}

        # Average confidence
        avg_row = self.store._conn.execute(
            "SELECT AVG(confidence) as avg FROM knowledge"
        ).fetchone()
        avg_conf = avg_row["avg"] or 0

        # Data layers
        layer_rows = self.store._conn.execute(
            "SELECT data_layer, COUNT(*) as cnt FROM knowledge GROUP BY data_layer"
        ).fetchall()
        layers = {str(r["data_layer"] or "default"): r["cnt"] for r in layer_rows}

        # Agents
        agent_rows = self.store._conn.execute(
            "SELECT DISTINCT agent_id FROM knowledge WHERE agent_id != ''"
        ).fetchall()
        agents = [r["agent_id"] for r in agent_rows]

        # Entry IDs for diff
        id_rows = self.store._conn.execute("SELECT id FROM knowledge").fetchall()
        entry_ids = {r["id"] for r in id_rows}

        snapshot = Snapshot(
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_entries=total,
            topics=topics,
            avg_confidence=round(avg_conf, 4),
            data_layers=layers,
            agents=agents,
            entry_ids=entry_ids,
        )

        self._snapshots[name] = snapshot
        return snapshot

    def diff(self, name_a: str, name_b: str) -> Optional[SnapshotDiff]:
        """Compare two snapshots."""
        a = self._snapshots.get(name_a)
        b = self._snapshots.get(name_b)
        if not a or not b:
            return None

        added = len(b.entry_ids - a.entry_ids)
        removed = len(a.entry_ids - b.entry_ids)

        new_topics = [t for t in b.topics if t not in a.topics]
        removed_topics = [t for t in a.topics if t not in b.topics]

        return SnapshotDiff(
            before=name_a,
            after=name_b,
            entries_added=added,
            entries_removed=removed,
            net_change=added - removed,
            new_topics=new_topics,
            removed_topics=removed_topics,
            confidence_change=round(b.avg_confidence - a.avg_confidence, 4),
        )

    def list_snapshots(self) -> list[dict]:
        """List all snapshots."""
        return [
            {
                "name": s.name,
                "timestamp": s.timestamp,
                "total_entries": s.total_entries,
                "topics": len(s.topics),
            }
            for s in self._snapshots.values()
        ]

    def get(self, name: str) -> Optional[Snapshot]:
        """Get a snapshot by name."""
        return self._snapshots.get(name)

    def delete(self, name: str) -> bool:
        """Delete a snapshot."""
        if name in self._snapshots:
            del self._snapshots[name]
            return True
        return False
