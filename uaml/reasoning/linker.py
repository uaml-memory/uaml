# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Linker — discover and manage relationships between entries.

Automatically suggests links based on content similarity, shared topics,
and temporal proximity.

Usage:
    from uaml.reasoning.linker import KnowledgeLinker

    linker = KnowledgeLinker(store)
    suggestions = linker.suggest_links(entry_id=1)
    linker.create_link(source_id=1, target_id=2, relation="related_to")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class LinkSuggestion:
    """A suggested link between entries."""
    source_id: int
    target_id: int
    relation: str
    reason: str
    score: float


class KnowledgeLinker:
    """Discover and manage knowledge relationships."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self):
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation TEXT NOT NULL DEFAULT 'related_to',
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),
                UNIQUE(source_id, target_id, relation)
            )
        """)
        self.store._conn.commit()

    def suggest_links(self, entry_id: int, *, limit: int = 5) -> list[LinkSuggestion]:
        """Suggest links for an entry based on content and topic similarity."""
        entry = self.store._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()

        if not entry:
            return []

        suggestions = []

        # Topic-based suggestions
        if entry["topic"]:
            same_topic = self.store._conn.execute(
                """SELECT id, content FROM knowledge
                   WHERE topic = ? AND id != ? LIMIT ?""",
                (entry["topic"], entry_id, limit),
            ).fetchall()

            for r in same_topic:
                overlap = self._word_overlap(entry["content"], r["content"])
                if overlap > 0.2:
                    suggestions.append(LinkSuggestion(
                        source_id=entry_id,
                        target_id=r["id"],
                        relation="same_topic",
                        reason=f"Shared topic '{entry['topic']}', content overlap {overlap:.0%}",
                        score=overlap,
                    ))

        # Content-based suggestions (different topics)
        others = self.store._conn.execute(
            """SELECT id, content, topic FROM knowledge
               WHERE id != ? AND (topic != ? OR topic IS NULL)
               LIMIT 50""",
            (entry_id, entry["topic"] or ""),
        ).fetchall()

        for r in others:
            overlap = self._word_overlap(entry["content"], r["content"])
            if overlap > 0.3:
                suggestions.append(LinkSuggestion(
                    source_id=entry_id,
                    target_id=r["id"],
                    relation="related_to",
                    reason=f"Content overlap {overlap:.0%} across topics",
                    score=overlap,
                ))

        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:limit]

    def create_link(self, source_id: int, target_id: int, relation: str = "related_to") -> bool:
        """Create a link between two entries."""
        try:
            self.store._conn.execute(
                "INSERT OR IGNORE INTO knowledge_links (source_id, target_id, relation) VALUES (?, ?, ?)",
                (source_id, target_id, relation),
            )
            self.store._conn.commit()
            return True
        except Exception:
            return False

    def get_links(self, entry_id: int) -> list[dict]:
        """Get all links for an entry."""
        rows = self.store._conn.execute(
            """SELECT * FROM knowledge_links
               WHERE source_id = ? OR target_id = ?""",
            (entry_id, entry_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def remove_link(self, source_id: int, target_id: int, relation: str = "related_to") -> bool:
        """Remove a link."""
        cursor = self.store._conn.execute(
            "DELETE FROM knowledge_links WHERE source_id = ? AND target_id = ? AND relation = ?",
            (source_id, target_id, relation),
        )
        self.store._conn.commit()
        return cursor.rowcount > 0

    def linked_entries(self, entry_id: int) -> list[dict]:
        """Get all entries linked to this one."""
        rows = self.store._conn.execute(
            """SELECT k.*, kl.relation FROM knowledge k
               JOIN knowledge_links kl ON (
                   (kl.target_id = k.id AND kl.source_id = ?)
                   OR (kl.source_id = k.id AND kl.target_id = ?)
               )""",
            (entry_id, entry_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def _word_overlap(self, a: str, b: str) -> float:
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / min(len(words_a), len(words_b))
