# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Deduplication Engine — find and merge duplicate knowledge entries.

Goes beyond simple content_hash matching: uses similarity scoring
to find near-duplicates and offers merge strategies.

Usage:
    from uaml.core.dedup import DedupEngine

    engine = DedupEngine(store)
    duplicates = engine.find_duplicates(threshold=0.85)
    engine.merge_duplicates(duplicates, strategy="keep_newest")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class DuplicateGroup:
    """A group of duplicate entries."""
    entry_ids: list[int]
    topics: list[str]
    similarity: float
    sample_content: str


class DedupEngine:
    """Find and resolve duplicate knowledge entries."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._conn = store._conn

    def find_exact_duplicates(self) -> list[DuplicateGroup]:
        """Find entries with identical content_hash."""
        rows = self._conn.execute("""
            SELECT content_hash, GROUP_CONCAT(id) as ids,
                   GROUP_CONCAT(topic, '|') as topics,
                   MIN(content) as sample
            FROM knowledge
            WHERE content_hash IS NOT NULL AND content_hash != ''
            GROUP BY content_hash
            HAVING COUNT(*) > 1
        """).fetchall()

        groups = []
        for r in rows:
            ids = [int(i) for i in r["ids"].split(",")]
            topics = r["topics"].split("|") if r["topics"] else []
            groups.append(DuplicateGroup(
                entry_ids=ids,
                topics=topics,
                similarity=1.0,
                sample_content=(r["sample"] or "")[:200],
            ))
        return groups

    def find_near_duplicates(
        self,
        *,
        threshold: float = 0.85,
        limit: int = 1000,
    ) -> list[DuplicateGroup]:
        """Find entries with similar content using word overlap.

        Uses Jaccard similarity on word sets for fast approximate matching.
        For exact matches, use find_exact_duplicates().

        Args:
            threshold: Minimum Jaccard similarity (0.0–1.0)
            limit: Max entries to compare
        """
        rows = self._conn.execute(
            "SELECT id, content, topic FROM knowledge ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()

        # Build word sets
        entries = []
        for r in rows:
            words = set((r["content"] or "").lower().split())
            if len(words) >= 3:  # Skip very short entries
                entries.append({
                    "id": r["id"],
                    "words": words,
                    "topic": r["topic"] or "",
                    "content": r["content"] or "",
                })

        # Pairwise comparison
        groups: list[DuplicateGroup] = []
        seen: set[int] = set()

        for i in range(len(entries)):
            if entries[i]["id"] in seen:
                continue
            group_ids = [entries[i]["id"]]
            group_topics = [entries[i]["topic"]]

            for j in range(i + 1, len(entries)):
                if entries[j]["id"] in seen:
                    continue

                # Jaccard similarity
                intersection = entries[i]["words"] & entries[j]["words"]
                union = entries[i]["words"] | entries[j]["words"]
                sim = len(intersection) / len(union) if union else 0

                if sim >= threshold:
                    group_ids.append(entries[j]["id"])
                    group_topics.append(entries[j]["topic"])
                    seen.add(entries[j]["id"])

            if len(group_ids) > 1:
                seen.add(entries[i]["id"])
                groups.append(DuplicateGroup(
                    entry_ids=group_ids,
                    topics=group_topics,
                    similarity=threshold,
                    sample_content=entries[i]["content"][:200],
                ))

        return groups

    def merge_group(
        self,
        group: DuplicateGroup,
        *,
        strategy: str = "keep_newest",
    ) -> int:
        """Merge a duplicate group.

        Strategies:
        - keep_newest: Keep the most recently created entry, delete others
        - keep_highest_confidence: Keep entry with highest confidence
        - keep_first: Keep the first (oldest) entry

        Returns the ID of the kept entry.
        """
        if len(group.entry_ids) < 2:
            return group.entry_ids[0] if group.entry_ids else 0

        rows = self._conn.execute(
            f"SELECT id, created_at, confidence FROM knowledge WHERE id IN ({','.join('?' * len(group.entry_ids))})",
            group.entry_ids,
        ).fetchall()

        if not rows:
            return 0

        if strategy == "keep_newest":
            keeper = max(rows, key=lambda r: r["created_at"] or "")
        elif strategy == "keep_highest_confidence":
            keeper = max(rows, key=lambda r: r["confidence"] or 0)
        elif strategy == "keep_first":
            keeper = min(rows, key=lambda r: r["created_at"] or "")
        else:
            keeper = rows[0]

        keep_id = keeper["id"]
        delete_ids = [r["id"] for r in rows if r["id"] != keep_id]

        for did in delete_ids:
            self._conn.execute("DELETE FROM knowledge WHERE id = ?", (did,))

        self._conn.commit()
        return keep_id

    def auto_dedup(
        self,
        *,
        strategy: str = "keep_newest",
        dry_run: bool = True,
    ) -> dict:
        """Run full deduplication.

        Args:
            strategy: Merge strategy
            dry_run: If True, report but don't delete

        Returns:
            Summary with counts
        """
        exact = self.find_exact_duplicates()
        result = {
            "exact_groups": len(exact),
            "exact_duplicates": sum(len(g.entry_ids) - 1 for g in exact),
            "merged": 0,
            "dry_run": dry_run,
            "strategy": strategy,
        }

        if not dry_run:
            for group in exact:
                self.merge_group(group, strategy=strategy)
                result["merged"] += len(group.entry_ids) - 1

        return result

    def stats(self) -> dict:
        """Deduplication statistics."""
        total = self._conn.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]
        with_hash = self._conn.execute(
            "SELECT COUNT(*) as c FROM knowledge WHERE content_hash IS NOT NULL AND content_hash != ''"
        ).fetchone()["c"]
        exact = self.find_exact_duplicates()

        return {
            "total_entries": total,
            "entries_with_hash": with_hash,
            "exact_duplicate_groups": len(exact),
            "exact_duplicates": sum(len(g.entry_ids) - 1 for g in exact),
        }
