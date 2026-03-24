# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Changelog — track what changed and when.

Generates human-readable changelog from audit log and knowledge
modifications. Useful for compliance reporting and team awareness.

Usage:
    from uaml.core.changelog import ChangelogGenerator

    gen = ChangelogGenerator(store)
    log = gen.generate(days=7)
    print(log.to_markdown())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class ChangeEntry:
    """A single change record."""
    timestamp: str
    action: str
    agent_id: str
    topic: str
    summary: str
    entry_id: int = 0


@dataclass
class Changelog:
    """A collection of changes over a period."""
    changes: list[ChangeEntry] = field(default_factory=list)
    period_start: str = ""
    period_end: str = ""

    @property
    def stats(self) -> dict:
        from collections import Counter
        actions = Counter(c.action for c in self.changes)
        agents = Counter(c.agent_id for c in self.changes)
        return {
            "total_changes": len(self.changes),
            "by_action": dict(actions),
            "by_agent": dict(agents),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Knowledge Changelog",
            f"Period: {self.period_start} — {self.period_end}",
            f"Total changes: {len(self.changes)}",
            "",
        ]
        current_date = ""
        for c in self.changes:
            date = c.timestamp[:10] if c.timestamp else ""
            if date != current_date:
                current_date = date
                lines.append(f"\n## {date}\n")

            icon = {"learn": "➕", "update": "✏️", "delete": "🗑️", "purge": "🧹"}.get(c.action, "📝")
            lines.append(f"- {icon} **{c.action}** [{c.topic}] {c.summary} _(by {c.agent_id})_")

        return "\n".join(lines)


class ChangelogGenerator:
    """Generate changelogs from audit log."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def generate(
        self,
        *,
        days: int = 7,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 500,
    ) -> Changelog:
        """Generate changelog for a time period."""
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).isoformat()
        end = now.isoformat()

        where = ["ts >= ?"]
        params: list = [start]

        if agent_id:
            where.append("agent_id = ?")
            params.append(agent_id)
        if action:
            where.append("action = ?")
            params.append(action)

        try:
            rows = self.store._conn.execute(
                f"""SELECT ts, action, agent_id, target_id, details
                    FROM audit_log
                    WHERE {' AND '.join(where)}
                    ORDER BY ts DESC
                    LIMIT ?""",
                params + [limit],
            ).fetchall()
        except Exception:
            return Changelog(period_start=start, period_end=end)

        changes = []
        for r in rows:
            # Try to get topic from knowledge table
            topic = ""
            summary = ""
            target_id = r["target_id"] or 0
            if target_id:
                try:
                    entry = self.store._conn.execute(
                        "SELECT topic, summary FROM knowledge WHERE id = ?",
                        (target_id,),
                    ).fetchone()
                    if entry:
                        topic = entry["topic"] or ""
                        summary = entry["summary"] or ""
                except Exception:
                    pass

            changes.append(ChangeEntry(
                timestamp=r["ts"] or "",
                action=r["action"] or "",
                agent_id=r["agent_id"] or "",
                topic=topic,
                summary=summary or (r["details"] or "")[:100],
                entry_id=target_id,
            ))

        return Changelog(
            changes=changes,
            period_start=start,
            period_end=end,
        )

    def daily_summary(self, date: Optional[str] = None) -> dict:
        """Get a summary for a specific day."""
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        log = self.generate(days=1)
        day_changes = [c for c in log.changes if c.timestamp.startswith(date)]

        return {
            "date": date,
            "changes": len(day_changes),
            "stats": Changelog(changes=day_changes).stats,
        }
