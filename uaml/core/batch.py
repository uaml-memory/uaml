# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Batch Operations — bulk learn/search/update for MemoryStore.

Provides efficient batch operations for importing large datasets,
bulk searches, and mass updates.

Usage:
    from uaml.core.batch import BatchProcessor

    proc = BatchProcessor(store)
    results = proc.batch_learn([
        {"content": "Fact 1", "topic": "t1"},
        {"content": "Fact 2", "topic": "t2"},
    ])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class BatchLearnResult:
    """Result of a batch learn operation."""
    total: int = 0
    stored: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.stored / self.total if self.total > 0 else 0.0


@dataclass
class BatchSearchResult:
    """Result of a batch search operation."""
    queries: int = 0
    total_results: int = 0
    results: dict[str, list] = field(default_factory=dict)


class BatchProcessor:
    """Efficient batch operations for MemoryStore."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def batch_learn(
        self,
        items: list[dict],
        *,
        defaults: Optional[dict] = None,
        dedup: bool = True,
        continue_on_error: bool = True,
    ) -> BatchLearnResult:
        """Learn multiple entries at once.

        Args:
            items: List of dicts with at minimum 'content' key.
                   Optional: topic, summary, source_ref, tags, confidence,
                   data_layer, project, client_ref, valid_from, valid_until
            defaults: Default values for missing fields
            dedup: Enable deduplication
            continue_on_error: If True, continue after individual failures

        Returns:
            BatchLearnResult with counts
        """
        result = BatchLearnResult(total=len(items))
        defs = defaults or {}

        for i, item in enumerate(items):
            try:
                content = item.get("content", "")
                if not content:
                    result.skipped += 1
                    continue

                entry_id = self.store.learn(
                    content,
                    topic=item.get("topic", defs.get("topic", "")),
                    summary=item.get("summary", defs.get("summary", "")),
                    source_ref=item.get("source_ref", defs.get("source_ref", "")),
                    tags=item.get("tags", defs.get("tags", "")),
                    confidence=item.get("confidence", defs.get("confidence", 0.8)),
                    data_layer=item.get("data_layer", defs.get("data_layer", "knowledge")),
                    project=item.get("project", defs.get("project")),
                    client_ref=item.get("client_ref", defs.get("client_ref")),
                    valid_from=item.get("valid_from", defs.get("valid_from")),
                    valid_until=item.get("valid_until", defs.get("valid_until")),
                    dedup=dedup,
                )

                if entry_id:
                    result.stored += 1
                else:
                    result.skipped += 1

            except Exception as e:
                result.errors.append(f"item[{i}]: {e}")
                if not continue_on_error:
                    break

        return result

    def batch_search(
        self,
        queries: list[str],
        *,
        limit: int = 5,
        topic: Optional[str] = None,
        project: Optional[str] = None,
    ) -> BatchSearchResult:
        """Search for multiple queries at once.

        Args:
            queries: List of search query strings
            limit: Max results per query
            topic: Filter by topic
            project: Filter by project

        Returns:
            BatchSearchResult keyed by query
        """
        result = BatchSearchResult(queries=len(queries))

        for query in queries:
            try:
                results = self.store.search(
                    query,
                    limit=limit,
                    topic=topic,
                    project=project,
                )
                result.results[query] = [
                    {
                        "id": r.entry.id,
                        "score": round(r.score, 4),
                        "topic": r.entry.topic,
                        "summary": r.entry.summary,
                        "content": r.entry.content[:300],
                    }
                    for r in results
                ]
                result.total_results += len(results)
            except Exception:
                result.results[query] = []

        return result

    def batch_tag(
        self,
        entry_ids: list[int],
        tags: str,
        *,
        append: bool = True,
    ) -> int:
        """Add or replace tags for multiple entries.

        Args:
            entry_ids: List of entry IDs to tag
            tags: Tags to apply (comma-separated)
            append: If True, append to existing tags; if False, replace

        Returns:
            Number of entries updated
        """
        updated = 0
        for eid in entry_ids:
            try:
                if append:
                    row = self.store._conn.execute(
                        "SELECT tags FROM knowledge WHERE id = ?", (eid,)
                    ).fetchone()
                    if row:
                        existing = row["tags"] or ""
                        existing_set = set(t.strip() for t in existing.split(",") if t.strip())
                        new_set = set(t.strip() for t in tags.split(",") if t.strip())
                        merged = ",".join(sorted(existing_set | new_set))
                        self.store._conn.execute(
                            "UPDATE knowledge SET tags = ? WHERE id = ?",
                            (merged, eid),
                        )
                        updated += 1
                else:
                    self.store._conn.execute(
                        "UPDATE knowledge SET tags = ? WHERE id = ?",
                        (tags, eid),
                    )
                    updated += 1
            except Exception:
                pass

        self.store._conn.commit()
        return updated

    def batch_update_confidence(
        self,
        updates: dict[int, float],
    ) -> int:
        """Update confidence for multiple entries.

        Args:
            updates: Dict of {entry_id: new_confidence}

        Returns:
            Number of entries updated
        """
        updated = 0
        for eid, conf in updates.items():
            try:
                conf = max(0.0, min(1.0, conf))
                self.store._conn.execute(
                    "UPDATE knowledge SET confidence = ? WHERE id = ?",
                    (conf, eid),
                )
                updated += 1
            except Exception:
                pass

        self.store._conn.commit()
        return updated

    def export_filtered(
        self,
        *,
        topic: Optional[str] = None,
        data_layer: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 1000,
    ) -> list[dict]:
        """Export filtered entries as dicts.

        Args:
            topic: Filter by topic
            data_layer: Filter by data layer
            min_confidence: Minimum confidence threshold
            limit: Max entries

        Returns:
            List of entry dicts
        """
        where = ["confidence >= ?"]
        params: list = [min_confidence]

        if topic:
            where.append("topic LIKE ?")
            params.append(f"%{topic}%")
        if data_layer:
            where.append("data_layer = ?")
            params.append(data_layer)

        rows = self.store._conn.execute(
            f"""
            SELECT id, topic, summary, content, confidence, data_layer,
                   tags, source_ref, created_at
            FROM knowledge
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        return [dict(r) for r in rows]
