# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Temporal Reasoning — time-aware knowledge operations.

Provides timeline construction, knowledge decay detection,
temporal conflict resolution, and freshness scoring.

Usage:
    from uaml.reasoning.temporal import TemporalReasoner

    reasoner = TemporalReasoner(store)
    timeline = reasoner.build_timeline(topic="deployment")
    stale = reasoner.find_stale(max_age_days=90)
    conflicts = reasoner.detect_conflicts(topic="server-config")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class TimelineEntry:
    """A point on the knowledge timeline."""
    entry_id: int
    timestamp: str
    topic: str
    summary: str
    data_layer: str
    confidence: float


@dataclass
class StaleEntry:
    """An entry detected as potentially stale."""
    entry_id: int
    topic: str
    summary: str
    age_days: int
    confidence: float
    reason: str


@dataclass
class TemporalConflict:
    """Two entries that may contradict each other in time."""
    older_id: int
    newer_id: int
    topic: str
    older_summary: str
    newer_summary: str
    gap_days: int


class TemporalReasoner:
    """Time-aware reasoning over memory content."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def build_timeline(
        self,
        topic: Optional[str] = None,
        *,
        limit: int = 50,
        data_layer: Optional[str] = None,
    ) -> list[TimelineEntry]:
        """Build a chronological timeline of knowledge entries.

        Args:
            topic: Filter by topic
            data_layer: Filter by data layer
            limit: Max entries to return
        """
        where = ["1=1"]
        params: list = []

        if topic:
            where.append("topic LIKE ?")
            params.append(f"%{topic}%")
        if data_layer:
            where.append("data_layer = ?")
            params.append(data_layer)

        query = f"""
            SELECT id, created_at, topic, summary, data_layer, confidence
            FROM knowledge
            WHERE {' AND '.join(where)}
            ORDER BY created_at ASC
            LIMIT ?
        """
        params.append(limit)

        rows = self.store._conn.execute(query, params).fetchall()
        return [
            TimelineEntry(
                entry_id=r["id"],
                timestamp=r["created_at"],
                topic=r["topic"] or "",
                summary=r["summary"] or "",
                data_layer=r["data_layer"] or "",
                confidence=r["confidence"] or 0.5,
            )
            for r in rows
        ]

    def find_stale(
        self,
        max_age_days: int = 90,
        *,
        min_confidence: float = 0.0,
    ) -> list[StaleEntry]:
        """Find entries that may be stale based on age.

        Args:
            max_age_days: Entries older than this are considered stale
            min_confidence: Only check entries with at least this confidence
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

        rows = self.store._conn.execute(
            """
            SELECT id, topic, summary, created_at, updated_at, confidence
            FROM knowledge
            WHERE (updated_at < ? OR (updated_at IS NULL AND created_at < ?))
              AND confidence >= ?
              
            ORDER BY created_at ASC
            """,
            (cutoff, cutoff, min_confidence),
        ).fetchall()

        now = datetime.now(timezone.utc)
        result = []
        for r in rows:
            ts = r["updated_at"] or r["created_at"]
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age = (now - dt).days
            except (ValueError, AttributeError):
                age = max_age_days + 1

            reason = f"Last updated {age} days ago (threshold: {max_age_days})"
            if r["confidence"] and r["confidence"] < 0.5:
                reason += ", low confidence"

            result.append(StaleEntry(
                entry_id=r["id"],
                topic=r["topic"] or "",
                summary=r["summary"] or "",
                age_days=age,
                confidence=r["confidence"] or 0.5,
                reason=reason,
            ))

        return result

    def detect_conflicts(
        self,
        topic: Optional[str] = None,
        *,
        min_gap_days: int = 0,
    ) -> list[TemporalConflict]:
        """Detect entries on the same topic that may conflict in time.

        Entries on the same topic with different content created at
        different times may represent updates that supersede older info.

        Args:
            topic: Filter by topic (required for meaningful results)
            min_gap_days: Minimum time gap to consider a potential conflict
        """
        if not topic:
            return []

        rows = self.store._conn.execute(
            """
            SELECT id, created_at, topic, summary, content
            FROM knowledge
            WHERE topic LIKE ? 
            ORDER BY created_at ASC
            """,
            (f"%{topic}%",),
        ).fetchall()

        conflicts = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                older = rows[i]
                newer = rows[j]

                # Calculate time gap
                try:
                    dt_old = datetime.fromisoformat(
                        (older["created_at"] or "").replace("Z", "+00:00")
                    )
                    dt_new = datetime.fromisoformat(
                        (newer["created_at"] or "").replace("Z", "+00:00")
                    )
                    gap = (dt_new - dt_old).days
                except (ValueError, AttributeError):
                    gap = 0

                if gap < min_gap_days:
                    continue

                # Simple content similarity check — if summaries differ significantly
                s_old = (older["summary"] or older["content"] or "")[:200]
                s_new = (newer["summary"] or newer["content"] or "")[:200]

                if s_old != s_new and gap > 0:
                    conflicts.append(TemporalConflict(
                        older_id=older["id"],
                        newer_id=newer["id"],
                        topic=topic,
                        older_summary=s_old,
                        newer_summary=s_new,
                        gap_days=gap,
                    ))

        return conflicts

    def freshness_score(self, entry_id: int, *, half_life_days: int = 30) -> float:
        """Calculate a freshness score (0.0–1.0) for an entry using exponential decay.

        Score = 2^(-age/half_life)
        - Age 0 → 1.0
        - Age = half_life → 0.5
        - Age = 2×half_life → 0.25

        Args:
            entry_id: Entry ID
            half_life_days: Number of days for score to halve
        """
        row = self.store._conn.execute(
            "SELECT updated_at, created_at FROM knowledge WHERE id = ?",
            (entry_id,),
        ).fetchone()

        if not row:
            return 0.0

        ts = row["updated_at"] or row["created_at"]
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - dt).days
        except (ValueError, AttributeError):
            return 0.0

        import math
        score = math.pow(2, -age_days / half_life_days)
        return round(min(1.0, max(0.0, score)), 4)

    def knowledge_age_stats(self) -> dict:
        """Get age distribution statistics for all active knowledge."""
        rows = self.store._conn.execute(
            """
            SELECT created_at, updated_at FROM knowledge
            WHERE 1=1
            """,
        ).fetchall()

        if not rows:
            return {"total": 0, "avg_age_days": 0, "buckets": {}}

        now = datetime.now(timezone.utc)
        ages = []
        for r in rows:
            ts = r["updated_at"] or r["created_at"]
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ages.append((now - dt).days)
            except (ValueError, AttributeError):
                pass

        if not ages:
            return {"total": len(rows), "avg_age_days": 0, "buckets": {}}

        buckets = {
            "today": sum(1 for a in ages if a == 0),
            "this_week": sum(1 for a in ages if a <= 7),
            "this_month": sum(1 for a in ages if a <= 30),
            "this_quarter": sum(1 for a in ages if a <= 90),
            "older": sum(1 for a in ages if a > 90),
        }

        return {
            "total": len(rows),
            "avg_age_days": round(sum(ages) / len(ages), 1),
            "min_age_days": min(ages),
            "max_age_days": max(ages),
            "buckets": buckets,
        }
