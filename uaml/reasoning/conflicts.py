# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Conflict Resolver — detect and resolve contradictions in knowledge.

Finds entries that contradict each other based on topic overlap
and temporal relationships, then suggests resolutions.

Usage:
    from uaml.reasoning.conflicts import ConflictResolver

    resolver = ConflictResolver(store)
    conflicts = resolver.detect()
    resolver.resolve(conflict_id, strategy="keep_newest")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class Conflict:
    """A detected knowledge conflict."""
    id: int
    entry_a_id: int
    entry_b_id: int
    topic: str
    reason: str
    severity: str  # low, medium, high
    suggested_action: str

    @property
    def entries(self) -> tuple[int, int]:
        return (self.entry_a_id, self.entry_b_id)


class ConflictResolver:
    """Detect and resolve knowledge conflicts."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._conflicts: list[Conflict] = []
        self._next_id = 1

    def detect(self, *, topic: Optional[str] = None) -> list[Conflict]:
        """Detect conflicts in the knowledge store."""
        self._conflicts.clear()
        self._next_id = 1

        where = "WHERE k1.id < k2.id"
        params: list = []

        if topic:
            where += " AND k1.topic = ? AND k2.topic = ?"
            params.extend([topic, topic])
        else:
            where += " AND k1.topic = k2.topic AND k1.topic != ''"

        rows = self.store._conn.execute(
            f"""SELECT k1.id as id1, k2.id as id2,
                       k1.topic, k1.content as c1, k2.content as c2,
                       k1.confidence as conf1, k2.confidence as conf2,
                       k1.updated_at as u1, k2.updated_at as u2
                FROM knowledge k1
                JOIN knowledge k2 {where}
                LIMIT 200""",
            params,
        ).fetchall()

        for r in rows:
            # Check for potential conflicts
            overlap = self._word_overlap(r["c1"], r["c2"])

            if overlap > 0.6:
                # High overlap — possible duplicate or contradiction
                severity = "high" if overlap > 0.8 else "medium"

                if r["conf1"] != r["conf2"]:
                    reason = f"Same topic, {overlap:.0%} content overlap, different confidence ({r['conf1']:.0%} vs {r['conf2']:.0%})"
                    action = "keep_highest_confidence"
                elif r["u1"] != r["u2"]:
                    reason = f"Same topic, {overlap:.0%} content overlap, different timestamps"
                    action = "keep_newest"
                else:
                    reason = f"Same topic, {overlap:.0%} content overlap — possible duplicate"
                    action = "merge"

                conflict = Conflict(
                    id=self._next_id,
                    entry_a_id=r["id1"],
                    entry_b_id=r["id2"],
                    topic=r["topic"],
                    reason=reason,
                    severity=severity,
                    suggested_action=action,
                )
                self._conflicts.append(conflict)
                self._next_id += 1

        return self._conflicts

    def resolve(self, conflict_id: int, strategy: str = "keep_newest") -> bool:
        """Resolve a conflict.

        Strategies:
            keep_newest: Keep the most recent entry, delete older
            keep_highest_confidence: Keep higher confidence
            keep_both: Mark as reviewed, keep both
            merge: Keep entry A, delete B
        """
        conflict = next((c for c in self._conflicts if c.id == conflict_id), None)
        if not conflict:
            return False

        if strategy == "keep_both":
            self._conflicts = [c for c in self._conflicts if c.id != conflict_id]
            return True

        # Get entries
        a = self.store._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (conflict.entry_a_id,)
        ).fetchone()
        b = self.store._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (conflict.entry_b_id,)
        ).fetchone()

        if not a or not b:
            return False

        if strategy == "keep_newest":
            delete_id = conflict.entry_a_id if (a["updated_at"] or "") < (b["updated_at"] or "") else conflict.entry_b_id
        elif strategy == "keep_highest_confidence":
            delete_id = conflict.entry_a_id if a["confidence"] < b["confidence"] else conflict.entry_b_id
        elif strategy == "merge":
            delete_id = conflict.entry_b_id
        else:
            return False

        self.store.delete_entry(delete_id)
        self._conflicts = [c for c in self._conflicts if c.id != conflict_id]
        return True

    def summary(self) -> dict:
        """Get conflict summary."""
        from collections import Counter
        severities = Counter(c.severity for c in self._conflicts)
        topics = Counter(c.topic for c in self._conflicts)

        return {
            "total_conflicts": len(self._conflicts),
            "by_severity": dict(severities),
            "top_topics": dict(topics.most_common(5)),
        }

    def _word_overlap(self, a: str, b: str) -> float:
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / min(len(words_a), len(words_b))
