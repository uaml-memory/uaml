# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Versioning — track changes to entries over time.

Every update to a knowledge entry creates a version snapshot,
enabling rollback, diff, and audit of knowledge evolution.

Usage:
    from uaml.core.versioning import VersionManager

    vm = VersionManager(store)
    vm.update_entry(entry_id=1, content="Updated fact", reason="Correction")
    history = vm.get_history(entry_id=1)
    vm.rollback(entry_id=1, version=1)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class EntryVersion:
    """A historical version of a knowledge entry."""
    version: int
    entry_id: int
    content: str
    summary: str
    topic: str
    confidence: float
    tags: str
    reason: str
    created_at: str
    agent_id: str = ""


class VersionManager:
    """Manage knowledge entry versions with history and rollback."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._conn = store._conn
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                tags TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(entry_id, version)
            )
        """)
        self._conn.commit()

    def _snapshot(self, entry_id: int, reason: str = "") -> Optional[int]:
        """Take a snapshot of the current entry state."""
        row = self._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()

        if not row:
            return None

        # Get next version number
        max_v = self._conn.execute(
            "SELECT MAX(version) as v FROM knowledge_versions WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        version = (max_v["v"] or 0) + 1

        self._conn.execute(
            """INSERT INTO knowledge_versions
               (entry_id, version, content, summary, topic, confidence, tags, reason, agent_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id, version,
                row["content"] or "", row["summary"] or "",
                row["topic"] or "", row["confidence"] or 0.5,
                row["tags"] or "", reason,
                row["agent_id"] or "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return version

    def update_entry(
        self,
        entry_id: int,
        *,
        content: Optional[str] = None,
        summary: Optional[str] = None,
        topic: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[str] = None,
        reason: str = "",
    ) -> Optional[int]:
        """Update an entry with automatic version snapshot.

        Takes a snapshot before applying changes, then updates.
        Returns the new version number, or None if entry not found.
        """
        # Snapshot current state
        version = self._snapshot(entry_id, reason=reason)
        if version is None:
            return None

        # Build update
        updates = []
        params = []
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if summary is not None:
            updates.append("summary = ?")
            params.append(summary)
        if topic is not None:
            updates.append("topic = ?")
            params.append(topic)
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(max(0.0, min(1.0, confidence)))
        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)

        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(entry_id)
            self._conn.execute(
                f"UPDATE knowledge SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            self._conn.commit()

        return version

    def get_history(self, entry_id: int, *, limit: int = 50) -> list[EntryVersion]:
        """Get version history for an entry."""
        rows = self._conn.execute(
            """SELECT * FROM knowledge_versions
               WHERE entry_id = ?
               ORDER BY version DESC LIMIT ?""",
            (entry_id, limit),
        ).fetchall()

        return [
            EntryVersion(
                version=r["version"],
                entry_id=r["entry_id"],
                content=r["content"],
                summary=r["summary"],
                topic=r["topic"],
                confidence=r["confidence"],
                tags=r["tags"],
                reason=r["reason"],
                created_at=r["created_at"],
                agent_id=r["agent_id"],
            )
            for r in rows
        ]

    def get_version(self, entry_id: int, version: int) -> Optional[EntryVersion]:
        """Get a specific version of an entry."""
        row = self._conn.execute(
            "SELECT * FROM knowledge_versions WHERE entry_id = ? AND version = ?",
            (entry_id, version),
        ).fetchone()

        if not row:
            return None

        return EntryVersion(
            version=row["version"],
            entry_id=row["entry_id"],
            content=row["content"],
            summary=row["summary"],
            topic=row["topic"],
            confidence=row["confidence"],
            tags=row["tags"],
            reason=row["reason"],
            created_at=row["created_at"],
            agent_id=row["agent_id"],
        )

    def rollback(self, entry_id: int, version: int, *, reason: str = "rollback") -> bool:
        """Rollback an entry to a previous version.

        Creates a new version snapshot (of current state) before rolling back.
        """
        target = self.get_version(entry_id, version)
        if target is None:
            return False

        # Snapshot current state before rollback
        self._snapshot(entry_id, reason=f"pre-rollback to v{version}")

        # Apply the old version
        self._conn.execute(
            """UPDATE knowledge SET
               content = ?, summary = ?, topic = ?,
               confidence = ?, tags = ?, updated_at = ?
               WHERE id = ?""",
            (
                target.content, target.summary, target.topic,
                target.confidence, target.tags,
                datetime.now(timezone.utc).isoformat(),
                entry_id,
            ),
        )
        self._conn.commit()
        return True

    def diff(self, entry_id: int, v1: int, v2: int) -> dict:
        """Compare two versions of an entry."""
        ver1 = self.get_version(entry_id, v1)
        ver2 = self.get_version(entry_id, v2)

        if not ver1 or not ver2:
            return {"error": "Version not found"}

        changes = {}
        for field_name in ("content", "summary", "topic", "confidence", "tags"):
            val1 = getattr(ver1, field_name)
            val2 = getattr(ver2, field_name)
            if val1 != val2:
                changes[field_name] = {"from": val1, "to": val2}

        return {
            "entry_id": entry_id,
            "from_version": v1,
            "to_version": v2,
            "changes": changes,
            "changed_fields": list(changes.keys()),
        }

    def version_count(self, entry_id: int) -> int:
        """Count versions for an entry."""
        row = self._conn.execute(
            "SELECT COUNT(*) as c FROM knowledge_versions WHERE entry_id = ?",
            (entry_id,),
        ).fetchone()
        return row["c"] if row else 0
