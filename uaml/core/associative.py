# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Associative Memory — "intuition" engine for UAML.

Finds related entries through multiple signals:
1. **Content similarity** — FTS5 BM25 scoring on matching terms
2. **Co-occurrence** — shared topic, tags, project, client
3. **Temporal proximity** — entries created close together in time
4. **Provenance links** — source_links graph traversal
5. **Task connections** — entries linked to the same task

This is the 5th memory type (alongside episodic, semantic, procedural, reasoning)
— associative/contextual recall that mimics human intuition.

Usage:
    from uaml.core.associative import AssociativeEngine

    engine = AssociativeEngine(store)
    related = engine.find_related(entry_id=42, limit=5)
    triggered = engine.contextual_recall("deploying Neo4j on production", limit=3)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class Association:
    """A single association between entries."""

    entry_id: int
    content: str
    topic: str
    score: float  # Combined relevance score (0-1)
    signals: list[str]  # Which signals contributed (content, topic, temporal, provenance, task)

    def __repr__(self):
        return f"Association(id={self.entry_id}, score={self.score:.2f}, signals={self.signals})"


class AssociativeEngine:
    """Find related entries through multiple association signals.

    Combines content similarity, metadata overlap, temporal proximity,
    and graph links into a single ranked result set.
    """

    # Weight per signal type (tunable)
    WEIGHTS = {
        "content": 0.35,   # FTS5 BM25 content match
        "topic": 0.20,     # Same topic
        "tags": 0.15,      # Shared tags
        "project": 0.10,   # Same project
        "temporal": 0.05,  # Created within time window
        "provenance": 0.10,  # source_links connection
        "task": 0.05,      # Linked to same task
    }

    def __init__(self, store: MemoryStore, weights: dict | None = None):
        self.store = store
        if weights:
            self.WEIGHTS = {**self.WEIGHTS, **weights}

    def find_related(
        self,
        entry_id: int,
        *,
        limit: int = 10,
        min_score: float = 0.05,
        exclude_self: bool = True,
    ) -> list[Association]:
        """Find entries related to a given entry.

        Combines all association signals into a ranked list.
        """
        # Get the source entry
        row = self.store.conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return []

        entry = dict(row)
        scores: dict[int, dict] = {}  # entry_id → {score, signals, content, topic}

        # 1. Content similarity (FTS5)
        self._score_content(entry, scores, limit * 3)

        # 2. Topic match
        self._score_topic(entry, scores)

        # 3. Tag overlap
        self._score_tags(entry, scores)

        # 4. Project match
        self._score_project(entry, scores)

        # 5. Temporal proximity
        self._score_temporal(entry, scores)

        # 6. Provenance links
        self._score_provenance(entry_id, scores)

        # 7. Task connections
        self._score_tasks(entry_id, scores)

        # Build results
        results = []
        for eid, data in scores.items():
            if exclude_self and eid == entry_id:
                continue
            if data["score"] < min_score:
                continue
            results.append(Association(
                entry_id=eid,
                content=data.get("content", ""),
                topic=data.get("topic", ""),
                score=min(data["score"], 1.0),
                signals=data.get("signals", []),
            ))

        results.sort(key=lambda a: a.score, reverse=True)
        return results[:limit]

    def contextual_recall(
        self,
        context: str,
        *,
        limit: int = 5,
        min_score: float = 0.05,
    ) -> list[Association]:
        """Proactive recall based on situational context.

        Given a text context (e.g., current conversation topic),
        finds relevant knowledge entries that might be useful — without
        an explicit query. This is "intuition".
        """
        scores: dict[int, dict] = {}

        # Extract key terms from context for FTS search
        # Use words > 3 chars, skip common words
        words = set(re.findall(r'\b\w{4,}\b', context.lower()))
        stop_words = {"this", "that", "with", "from", "have", "been", "will", "would",
                      "could", "should", "about", "their", "there", "which", "these",
                      "those", "what", "when", "where", "into", "also", "some", "more",
                      "than", "then", "very", "just", "jako", "jsou", "není", "bylo",
                      "bude", "může", "musí", "také", "nebo", "když", "ještě", "tohle"}
        keywords = words - stop_words

        if not keywords:
            return []

        # Search with individual keywords (broader recall)
        for keyword in list(keywords)[:8]:  # Limit to 8 keywords to prevent overload
            try:
                rows = self.store.conn.execute(
                    "SELECT k.id, k.content, k.topic, k.tags, k.project, "
                    "knowledge_fts.rank as fts_rank "
                    "FROM knowledge k "
                    "JOIN knowledge_fts ON k.id = knowledge_fts.rowid "
                    "WHERE knowledge_fts MATCH ? "
                    "ORDER BY knowledge_fts.rank "
                    "LIMIT 10",
                    (keyword,),
                ).fetchall()
            except Exception:
                continue

            for row in rows:
                eid = row["id"]
                if eid not in scores:
                    scores[eid] = {
                        "score": 0.0,
                        "signals": [],
                        "content": row["content"],
                        "topic": row["topic"],
                    }
                # FTS rank is negative (closer to 0 = better)
                fts_score = min(1.0, abs(row["fts_rank"]) * 0.1)
                scores[eid]["score"] += fts_score * self.WEIGHTS["content"]
                if "content" not in scores[eid]["signals"]:
                    scores[eid]["signals"].append("content")

        # Boost entries matching multiple keywords
        for eid, data in scores.items():
            content_lower = data["content"].lower()
            match_count = sum(1 for kw in keywords if kw in content_lower)
            if match_count > 1:
                data["score"] *= (1.0 + 0.2 * (match_count - 1))
                if "multi_match" not in data["signals"]:
                    data["signals"].append("multi_match")

        # Build results
        results = []
        for eid, data in scores.items():
            if data["score"] < min_score:
                continue
            results.append(Association(
                entry_id=eid,
                content=data["content"],
                topic=data.get("topic", ""),
                score=min(data["score"], 1.0),
                signals=data.get("signals", []),
            ))

        results.sort(key=lambda a: a.score, reverse=True)
        return results[:limit]

    # ── Signal scorers ──

    def _score_content(self, entry: dict, scores: dict, limit: int) -> None:
        """Score by FTS5 content similarity."""
        # Extract key terms from content for matching
        content = entry.get("content", "")
        words = re.findall(r'\b\w{4,}\b', content)
        if not words:
            return

        # Use top 5 longest words as query terms
        query_terms = sorted(set(words), key=len, reverse=True)[:5]
        query = " OR ".join(query_terms)

        try:
            rows = self.store.conn.execute(
                "SELECT k.id, k.content, k.topic, knowledge_fts.rank as fts_rank "
                "FROM knowledge k "
                "JOIN knowledge_fts ON k.id = knowledge_fts.rowid "
                "WHERE knowledge_fts MATCH ? "
                "ORDER BY knowledge_fts.rank "
                "LIMIT ?",
                (query, limit),
            ).fetchall()
        except Exception:
            return

        for row in rows:
            eid = row["id"]
            if eid not in scores:
                scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
            fts_score = min(1.0, abs(row["fts_rank"]) * 0.1)
            scores[eid]["score"] += fts_score * self.WEIGHTS["content"]
            if "content" not in scores[eid]["signals"]:
                scores[eid]["signals"].append("content")

    def _score_topic(self, entry: dict, scores: dict) -> None:
        """Score entries with the same topic."""
        topic = entry.get("topic")
        if not topic:
            return

        rows = self.store.conn.execute(
            "SELECT id, content, topic FROM knowledge WHERE topic = ? LIMIT 50",
            (topic,),
        ).fetchall()
        for row in rows:
            eid = row["id"]
            if eid not in scores:
                scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
            scores[eid]["score"] += self.WEIGHTS["topic"]
            if "topic" not in scores[eid]["signals"]:
                scores[eid]["signals"].append("topic")

    def _score_tags(self, entry: dict, scores: dict) -> None:
        """Score entries with overlapping tags."""
        tags = entry.get("tags", "")
        if not tags:
            return

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            rows = self.store.conn.execute(
                "SELECT id, content, topic FROM knowledge WHERE tags LIKE ? LIMIT 30",
                (f"%{tag}%",),
            ).fetchall()
            for row in rows:
                eid = row["id"]
                if eid not in scores:
                    scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
                scores[eid]["score"] += self.WEIGHTS["tags"] / max(len(tag_list), 1)
                if "tags" not in scores[eid]["signals"]:
                    scores[eid]["signals"].append("tags")

    def _score_project(self, entry: dict, scores: dict) -> None:
        """Score entries in the same project."""
        project = entry.get("project")
        if not project:
            return

        rows = self.store.conn.execute(
            "SELECT id, content, topic FROM knowledge WHERE project = ? LIMIT 50",
            (project,),
        ).fetchall()
        for row in rows:
            eid = row["id"]
            if eid not in scores:
                scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
            scores[eid]["score"] += self.WEIGHTS["project"]
            if "project" not in scores[eid]["signals"]:
                scores[eid]["signals"].append("project")

    def _score_temporal(self, entry: dict, scores: dict) -> None:
        """Score entries created within a time window (±1 hour)."""
        created = entry.get("created_at")
        if not created:
            return

        rows = self.store.conn.execute(
            "SELECT id, content, topic FROM knowledge "
            "WHERE created_at BETWEEN datetime(?, '-1 hour') AND datetime(?, '+1 hour') "
            "LIMIT 30",
            (created, created),
        ).fetchall()
        for row in rows:
            eid = row["id"]
            if eid not in scores:
                scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
            scores[eid]["score"] += self.WEIGHTS["temporal"]
            if "temporal" not in scores[eid]["signals"]:
                scores[eid]["signals"].append("temporal")

    def _score_provenance(self, entry_id: int, scores: dict) -> None:
        """Score entries connected via source_links."""
        # Outgoing links
        rows = self.store.conn.execute(
            "SELECT sl.target_id as linked_id, k.content, k.topic "
            "FROM source_links sl JOIN knowledge k ON sl.target_id = k.id "
            "WHERE sl.source_id = ?",
            (entry_id,),
        ).fetchall()

        # Incoming links
        rows2 = self.store.conn.execute(
            "SELECT sl.source_id as linked_id, k.content, k.topic "
            "FROM source_links sl JOIN knowledge k ON sl.source_id = k.id "
            "WHERE sl.target_id = ?",
            (entry_id,),
        ).fetchall()

        for row in list(rows) + list(rows2):
            eid = row["linked_id"]
            if eid not in scores:
                scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
            scores[eid]["score"] += self.WEIGHTS["provenance"]
            if "provenance" not in scores[eid]["signals"]:
                scores[eid]["signals"].append("provenance")

    def _score_tasks(self, entry_id: int, scores: dict) -> None:
        """Score entries linked to the same tasks."""
        # Find tasks linked to this entry
        task_ids = self.store.conn.execute(
            "SELECT task_id FROM task_knowledge WHERE entry_id = ?",
            (entry_id,),
        ).fetchall()

        for task_row in task_ids:
            # Find other entries linked to the same task
            rows = self.store.conn.execute(
                "SELECT tk.entry_id, k.content, k.topic "
                "FROM task_knowledge tk JOIN knowledge k ON tk.entry_id = k.id "
                "WHERE tk.task_id = ? AND tk.entry_id != ?",
                (task_row["task_id"], entry_id),
            ).fetchall()
            for row in rows:
                eid = row["entry_id"]
                if eid not in scores:
                    scores[eid] = {"score": 0.0, "signals": [], "content": row["content"], "topic": row["topic"]}
                scores[eid]["score"] += self.WEIGHTS["task"]
                if "task" not in scores[eid]["signals"]:
                    scores[eid]["signals"].append("task")
