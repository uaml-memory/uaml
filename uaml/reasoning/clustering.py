# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Clustering — group related entries automatically.

Uses word-overlap similarity to cluster entries into coherent groups
for discovery and organization.

Usage:
    from uaml.reasoning.clustering import KnowledgeClusterer

    clusterer = KnowledgeClusterer(store)
    clusters = clusterer.cluster(min_similarity=0.3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class Cluster:
    """A group of related knowledge entries."""
    id: int
    label: str
    entry_ids: list[int]
    keywords: list[str]
    avg_confidence: float
    size: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "size": self.size,
            "keywords": self.keywords,
            "avg_confidence": round(self.avg_confidence, 4),
            "entry_ids": self.entry_ids,
        }


class KnowledgeClusterer:
    """Cluster knowledge entries by similarity."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def cluster(
        self,
        *,
        min_similarity: float = 0.3,
        max_clusters: int = 20,
        limit: int = 500,
    ) -> list[Cluster]:
        """Cluster entries by content similarity."""
        rows = self.store._conn.execute(
            "SELECT id, content, topic, confidence FROM knowledge LIMIT ?",
            (limit,),
        ).fetchall()

        if not rows:
            return []

        entries = [dict(r) for r in rows]
        assigned = set()
        clusters = []
        cluster_id = 1

        for i, entry in enumerate(entries):
            if entry["id"] in assigned:
                continue

            group = [entry]
            assigned.add(entry["id"])

            for j, other in enumerate(entries):
                if i == j or other["id"] in assigned:
                    continue
                sim = self._similarity(entry["content"], other["content"])
                if sim >= min_similarity:
                    group.append(other)
                    assigned.add(other["id"])

            if len(group) >= 2:
                keywords = self._extract_keywords(group)
                label = group[0]["topic"] or keywords[0] if keywords else f"cluster_{cluster_id}"
                avg_conf = sum(e["confidence"] for e in group) / len(group)

                clusters.append(Cluster(
                    id=cluster_id,
                    label=label,
                    entry_ids=[e["id"] for e in group],
                    keywords=keywords[:5],
                    avg_confidence=avg_conf,
                    size=len(group),
                ))
                cluster_id += 1

                if len(clusters) >= max_clusters:
                    break

        clusters.sort(key=lambda c: c.size, reverse=True)
        return clusters

    def find_outliers(self, *, threshold: float = 0.1) -> list[int]:
        """Find entries that don't belong to any cluster."""
        clusters = self.cluster(min_similarity=threshold)
        clustered = set()
        for c in clusters:
            clustered.update(c.entry_ids)

        all_ids = self.store._conn.execute("SELECT id FROM knowledge").fetchall()
        return [r["id"] for r in all_ids if r["id"] not in clustered]

    def suggest_merges(self, *, min_similarity: float = 0.7) -> list[dict]:
        """Suggest entries that could be merged."""
        clusters = self.cluster(min_similarity=min_similarity)
        return [
            {"cluster_id": c.id, "label": c.label, "entry_ids": c.entry_ids, "size": c.size}
            for c in clusters if c.size >= 2
        ]

    def _similarity(self, a: str, b: str) -> float:
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)  # Jaccard

    def _extract_keywords(self, entries: list[dict]) -> list[str]:
        from collections import Counter
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or", "not", "it", "this", "that", "with"}
        words = Counter()
        for e in entries:
            for w in e["content"].lower().split():
                w = w.strip(".,!?;:()")
                if len(w) > 2 and w not in stopwords:
                    words[w] += 1
        return [w for w, _ in words.most_common(10)]
