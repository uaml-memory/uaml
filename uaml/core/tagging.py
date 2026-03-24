# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Tag Manager — structured tag operations on knowledge entries.

Provides bulk tagging, tag search, tag cloud, and tag normalization.

Usage:
    from uaml.core.tagging import TagManager

    tm = TagManager(store)
    tm.add_tags(entry_id=1, tags=["python", "threading"])
    cloud = tm.tag_cloud()
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from uaml.core.store import MemoryStore


class TagManager:
    """Manage tags on knowledge entries."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def get_tags(self, entry_id: int) -> list[str]:
        """Get tags for an entry."""
        row = self.store._conn.execute(
            "SELECT tags FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row or not row["tags"]:
            return []
        return [t.strip() for t in row["tags"].split(",") if t.strip()]

    def add_tags(self, entry_id: int, tags: list[str]) -> list[str]:
        """Add tags to an entry. Returns updated tag list."""
        existing = set(self.get_tags(entry_id))
        normalized = {self._normalize(t) for t in tags if t.strip()}
        merged = sorted(existing | normalized)
        self.store._conn.execute(
            "UPDATE knowledge SET tags = ? WHERE id = ?",
            (",".join(merged), entry_id),
        )
        self.store._conn.commit()
        return merged

    def remove_tags(self, entry_id: int, tags: list[str]) -> list[str]:
        """Remove tags from an entry. Returns updated tag list."""
        existing = set(self.get_tags(entry_id))
        to_remove = {self._normalize(t) for t in tags}
        remaining = sorted(existing - to_remove)
        self.store._conn.execute(
            "UPDATE knowledge SET tags = ? WHERE id = ?",
            (",".join(remaining), entry_id),
        )
        self.store._conn.commit()
        return remaining

    def replace_tags(self, entry_id: int, tags: list[str]) -> list[str]:
        """Replace all tags on an entry."""
        normalized = sorted({self._normalize(t) for t in tags if t.strip()})
        self.store._conn.execute(
            "UPDATE knowledge SET tags = ? WHERE id = ?",
            (",".join(normalized), entry_id),
        )
        self.store._conn.commit()
        return normalized

    def find_by_tag(self, tag: str, *, limit: int = 50) -> list[dict]:
        """Find entries with a specific tag."""
        normalized = self._normalize(tag)
        rows = self.store._conn.execute(
            """SELECT id, content, topic, tags, confidence
               FROM knowledge
               WHERE tags LIKE ? LIMIT ?""",
            (f"%{normalized}%", limit),
        ).fetchall()
        # Filter for exact tag match (not substring)
        results = []
        for r in rows:
            entry_tags = [t.strip() for t in (r["tags"] or "").split(",")]
            if normalized in entry_tags:
                results.append(dict(r))
        return results

    def tag_cloud(self, *, limit: int = 50) -> list[dict]:
        """Get tag frequency distribution."""
        rows = self.store._conn.execute(
            "SELECT tags FROM knowledge WHERE tags != '' AND tags IS NOT NULL"
        ).fetchall()

        counter = Counter()
        for r in rows:
            for tag in r["tags"].split(","):
                tag = tag.strip()
                if tag:
                    counter[tag] += 1

        return [
            {"tag": tag, "count": count}
            for tag, count in counter.most_common(limit)
        ]

    def rename_tag(self, old_tag: str, new_tag: str) -> int:
        """Rename a tag across all entries. Returns count affected."""
        old_norm = self._normalize(old_tag)
        new_norm = self._normalize(new_tag)
        count = 0

        rows = self.store._conn.execute(
            "SELECT id, tags FROM knowledge WHERE tags LIKE ?",
            (f"%{old_norm}%",),
        ).fetchall()

        for r in rows:
            tags = [t.strip() for t in r["tags"].split(",")]
            if old_norm in tags:
                tags = [new_norm if t == old_norm else t for t in tags]
                self.store._conn.execute(
                    "UPDATE knowledge SET tags = ? WHERE id = ?",
                    (",".join(tags), r["id"]),
                )
                count += 1

        self.store._conn.commit()
        return count

    def _normalize(self, tag: str) -> str:
        """Normalize a tag."""
        return tag.strip().lower().replace(" ", "_")
