# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Scoring — multi-dimensional quality scoring.

Scores entries on completeness, freshness, confidence, usage,
and provenance to prioritize high-value knowledge.

Usage:
    from uaml.reasoning.scoring import KnowledgeScorer

    scorer = KnowledgeScorer(store)
    score = scorer.score_entry(entry_id=1)
    ranked = scorer.rank_all(limit=20)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class EntryScore:
    """Multi-dimensional score for a knowledge entry."""
    entry_id: int
    topic: str
    overall: float
    completeness: float
    freshness: float
    confidence: float
    content_quality: float

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "topic": self.topic,
            "overall": round(self.overall, 4),
            "completeness": round(self.completeness, 4),
            "freshness": round(self.freshness, 4),
            "confidence": round(self.confidence, 4),
            "content_quality": round(self.content_quality, 4),
        }


class KnowledgeScorer:
    """Score knowledge entries on multiple dimensions."""

    # Weights for overall score
    WEIGHTS = {
        "completeness": 0.25,
        "freshness": 0.20,
        "confidence": 0.30,
        "content_quality": 0.25,
    }

    def __init__(self, store: MemoryStore, *, freshness_half_life_days: int = 90):
        self.store = store
        self.half_life = freshness_half_life_days

    def score_entry(self, entry_id: int) -> Optional[EntryScore]:
        """Score a single entry."""
        row = self.store._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()

        if not row:
            return None

        entry = dict(row)
        completeness = self._score_completeness(entry)
        freshness = self._score_freshness(entry)
        confidence = entry.get("confidence", 0)
        content_quality = self._score_content_quality(entry)

        overall = (
            self.WEIGHTS["completeness"] * completeness +
            self.WEIGHTS["freshness"] * freshness +
            self.WEIGHTS["confidence"] * confidence +
            self.WEIGHTS["content_quality"] * content_quality
        )

        return EntryScore(
            entry_id=entry_id,
            topic=entry.get("topic", ""),
            overall=overall,
            completeness=completeness,
            freshness=freshness,
            confidence=confidence,
            content_quality=content_quality,
        )

    def rank_all(self, *, limit: int = 50, min_score: float = 0.0) -> list[EntryScore]:
        """Rank all entries by overall score."""
        rows = self.store._conn.execute(
            "SELECT id FROM knowledge LIMIT 1000"
        ).fetchall()

        scores = []
        for r in rows:
            score = self.score_entry(r["id"])
            if score and score.overall >= min_score:
                scores.append(score)

        scores.sort(key=lambda s: s.overall, reverse=True)
        return scores[:limit]

    def low_quality(self, *, threshold: float = 0.3, limit: int = 20) -> list[EntryScore]:
        """Find low-quality entries."""
        all_scored = self.rank_all(limit=1000)
        return [s for s in all_scored if s.overall < threshold][:limit]

    def _score_completeness(self, entry: dict) -> float:
        """Score based on metadata completeness."""
        score = 0.0
        checks = [
            ("content", 0.3),
            ("topic", 0.2),
            ("summary", 0.15),
            ("source_type", 0.1),
            ("source_ref", 0.1),
            ("tags", 0.1),
            ("agent_id", 0.05),
        ]
        for field, weight in checks:
            if entry.get(field):
                score += weight
        return min(score, 1.0)

    def _score_freshness(self, entry: dict) -> float:
        """Score based on age using exponential decay."""
        updated = entry.get("updated_at", "")
        if not updated:
            return 0.5

        try:
            updated_dt = datetime.fromisoformat(updated)
            now = datetime.now(timezone.utc)
            age_days = (now - updated_dt).total_seconds() / 86400
            return math.pow(2, -age_days / self.half_life)
        except Exception:
            return 0.5

    def _score_content_quality(self, entry: dict) -> float:
        """Score based on content quality heuristics."""
        content = entry.get("content", "")
        if not content:
            return 0.0

        score = 0.0
        length = len(content)

        # Length score (sweet spot: 50-5000 chars)
        if length < 10:
            score += 0.1
        elif length < 50:
            score += 0.3
        elif length <= 5000:
            score += 0.5
        else:
            score += 0.3  # Very long might be unfocused

        # Has sentences (contains periods)
        if "." in content:
            score += 0.2

        # Word variety
        words = content.lower().split()
        if words:
            unique_ratio = len(set(words)) / len(words)
            score += 0.3 * unique_ratio

        return min(score, 1.0)
