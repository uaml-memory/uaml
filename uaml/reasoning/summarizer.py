# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Summarizer — compress and summarize knowledge entries.

Generates summaries at various levels: micro (one-line), compact (paragraph),
and full (detailed). Works without LLM using extractive methods.

Usage:
    from uaml.reasoning.summarizer import KnowledgeSummarizer

    summarizer = KnowledgeSummarizer(store)
    summary = summarizer.topic_summary("python")
    overview = summarizer.store_overview()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class TopicSummary:
    """Summary of a knowledge topic."""
    topic: str
    entry_count: int
    avg_confidence: float
    key_points: list[str]
    date_range: tuple[str, str] = ("", "")

    def to_text(self) -> str:
        lines = [f"## {self.topic} ({self.entry_count} entries, avg confidence: {self.avg_confidence:.0%})"]
        for point in self.key_points:
            lines.append(f"- {point}")
        return "\n".join(lines)


@dataclass
class StoreOverview:
    """High-level overview of the knowledge store."""
    total_entries: int = 0
    topics: list[TopicSummary] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    date_range: tuple[str, str] = ("", "")

    def to_markdown(self) -> str:
        lines = [
            f"# Knowledge Store Overview",
            f"Total entries: {self.total_entries}",
            f"Topics: {len(self.topics)}",
            f"Agents: {', '.join(self.agents) if self.agents else 'none'}",
            "",
        ]
        for ts in self.topics:
            lines.append(ts.to_text())
            lines.append("")
        return "\n".join(lines)


class KnowledgeSummarizer:
    """Summarize knowledge entries extractively."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def topic_summary(self, topic: str, *, max_points: int = 5) -> TopicSummary:
        """Summarize entries for a topic."""
        rows = self.store._conn.execute(
            """SELECT content, confidence, summary, created_at
               FROM knowledge WHERE topic = ?
               ORDER BY confidence DESC, updated_at DESC""",
            (topic,),
        ).fetchall()

        if not rows:
            return TopicSummary(topic=topic, entry_count=0, avg_confidence=0, key_points=[])

        confidences = [r["confidence"] for r in rows]
        avg_conf = sum(confidences) / len(confidences)

        # Extract key points from summaries or first sentences
        points = []
        for r in rows[:max_points]:
            text = r["summary"] or r["content"]
            # Take first sentence
            point = text.split(".")[0].strip()
            if point and len(point) > 10:
                points.append(point[:200])

        dates = [r["created_at"] for r in rows if r["created_at"]]
        date_range = (min(dates), max(dates)) if dates else ("", "")

        return TopicSummary(
            topic=topic,
            entry_count=len(rows),
            avg_confidence=avg_conf,
            key_points=points,
            date_range=date_range,
        )

    def store_overview(self) -> StoreOverview:
        """Generate overview of the entire store."""
        total = self.store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

        # Get topics
        topic_rows = self.store._conn.execute(
            """SELECT topic, COUNT(*) as cnt, AVG(confidence) as avg_conf
               FROM knowledge WHERE topic != ''
               GROUP BY topic ORDER BY cnt DESC LIMIT 20"""
        ).fetchall()

        topics = []
        for r in topic_rows:
            ts = self.topic_summary(r["topic"], max_points=3)
            topics.append(ts)

        # Get agents
        agent_rows = self.store._conn.execute(
            "SELECT DISTINCT agent_id FROM knowledge WHERE agent_id != ''"
        ).fetchall()
        agents = [r["agent_id"] for r in agent_rows]

        # Date range
        dr = self.store._conn.execute(
            "SELECT MIN(created_at), MAX(created_at) FROM knowledge"
        ).fetchone()
        date_range = (dr[0] or "", dr[1] or "")

        return StoreOverview(
            total_entries=total,
            topics=topics,
            agents=agents,
            date_range=date_range,
        )

    def compress_entry(self, entry_id: int) -> str:
        """Generate a one-line summary of an entry."""
        row = self.store._conn.execute(
            "SELECT content, topic, summary FROM knowledge WHERE id = ?",
            (entry_id,),
        ).fetchone()

        if not row:
            return ""

        if row["summary"]:
            return row["summary"][:200]

        content = row["content"]
        # First sentence
        first = content.split(".")[0].strip()
        if len(first) > 10:
            return first[:200]

        return content[:200]
