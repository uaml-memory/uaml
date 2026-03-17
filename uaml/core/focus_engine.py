# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Focus Engine — intelligent output filter for context selection.

Controls what data from Neo4j/storage is injected into agent context.
Combines ethical filtering with intelligent selection based on:
- Token budget management
- Temporal decay (newer = higher priority)
- Relevance scoring with configurable threshold
- Sensitivity enforcement
- Deduplication
- Tiered recall (summaries → details → raw)

The Focus Engine reads human-configured rules but the AI agent
CANNOT modify them. Agent operates under the rules, not above them.

Designed for certifiability:
- Every recall decision is logged
- Token usage is tracked and reported
- All parameters are measurable with defined ranges

© 2026 GLG, a.s. — UAML Focus Engine
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from uaml.core.focus_config import FocusEngineConfig, OutputFilterConfig


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RecallCandidate:
    """A candidate record from storage for context injection."""
    entry_id: int
    content: str
    summary: Optional[str] = None
    relevance_score: float = 0.0
    created_at: Optional[str] = None
    sensitivity: int = 1
    category: str = ""
    tokens_estimate: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class RecallDecision:
    """Decision about a single recall candidate.

    Documents why a record was included or excluded.
    """
    entry_id: int
    included: bool
    reason: str
    final_score: float = 0.0
    tokens_used: int = 0


@dataclass
class FocusResult:
    """Result of Focus Engine processing.

    Contains selected records, token usage stats, and audit trail.
    """
    records: list[RecallCandidate] = field(default_factory=list)
    decisions: list[RecallDecision] = field(default_factory=list)
    total_tokens_used: int = 0
    total_candidates: int = 0
    total_selected: int = 0
    total_rejected: int = 0
    budget_remaining: int = 0
    recall_tier_used: int = 1

    @property
    def utilization_pct(self) -> float:
        """Token budget utilization percentage."""
        total = self.total_tokens_used + self.budget_remaining
        if total == 0:
            return 0.0
        return (self.total_tokens_used / total) * 100


@dataclass
class TokenUsageReport:
    """Token usage report for a single Focus Engine invocation.

    Designed for the Token Budget Manager UI.
    """
    budget: int
    used: int
    remaining: int
    records_selected: int
    records_rejected: int
    avg_tokens_per_record: float
    estimated_cost_usd: float
    recall_tier: int


# ---------------------------------------------------------------------------
# Focus Engine
# ---------------------------------------------------------------------------

class FocusEngine:
    """Intelligent output filter for context selection.

    Applies human-configured rules to select the best data
    for agent context within the token budget.
    """

    # Approximate cost per 1K input tokens (Claude Sonnet class)
    COST_PER_1K_TOKENS = 0.003

    def __init__(self, config: FocusEngineConfig):
        self._config = config
        self._ofc = config.output_filter

    @property
    def config(self) -> OutputFilterConfig:
        """Current output filter configuration (read-only for agents)."""
        return self._ofc

    def process(
        self,
        candidates: Sequence[RecallCandidate],
        *,
        model_context_window: int = 128000,
        query_context: str = "",
    ) -> FocusResult:
        """Process recall candidates through the Focus Engine.

        Steps:
        1. Filter by sensitivity threshold
        2. Filter by minimum relevance score
        3. Apply temporal decay to scores
        4. Deduplicate similar records
        5. Select by recall tier (summary vs detail vs raw)
        6. Fill token budget greedily by final score

        Args:
            candidates: Raw recall candidates from storage/search
            model_context_window: Total context window of the model
            query_context: Current query for relevance boosting

        Returns:
            FocusResult with selected records and audit trail
        """
        result = FocusResult(total_candidates=len(candidates))

        # Calculate effective budget
        max_budget_from_pct = int(
            model_context_window * (self._ofc.max_context_percentage / 100)
        )
        effective_budget = min(self._ofc.token_budget_per_query, max_budget_from_pct)
        result.budget_remaining = effective_budget

        # Working list
        scored: list[tuple[float, RecallCandidate]] = []

        for candidate in candidates:
            # Step 1: Sensitivity check
            if candidate.sensitivity > self._ofc.sensitivity_threshold:
                result.decisions.append(RecallDecision(
                    entry_id=candidate.entry_id,
                    included=False,
                    reason=f"Sensitivity {candidate.sensitivity} > threshold {self._ofc.sensitivity_threshold}",
                ))
                result.total_rejected += 1
                continue

            # Step 2: Relevance check
            if candidate.relevance_score < self._ofc.min_relevance_score:
                result.decisions.append(RecallDecision(
                    entry_id=candidate.entry_id,
                    included=False,
                    reason=f"Relevance {candidate.relevance_score:.3f} < threshold {self._ofc.min_relevance_score}",
                ))
                result.total_rejected += 1
                continue

            # Step 3: Temporal decay
            final_score = self._apply_temporal_decay(
                candidate.relevance_score, candidate.created_at
            )

            # Estimate tokens
            content = self._select_content_by_tier(candidate)
            tokens = self._estimate_tokens(content)
            candidate.tokens_estimate = tokens

            scored.append((final_score, candidate))

        # Step 4: Deduplicate
        scored = self._deduplicate(scored)

        # Step 5: Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Step 6: Fill budget greedily
        tokens_used = 0
        selected_count = 0

        for final_score, candidate in scored:
            if selected_count >= self._ofc.max_records:
                result.decisions.append(RecallDecision(
                    entry_id=candidate.entry_id,
                    included=False,
                    reason=f"Max records limit reached ({self._ofc.max_records})",
                    final_score=final_score,
                ))
                result.total_rejected += 1
                continue

            content = self._select_content_by_tier(candidate)
            tokens = self._estimate_tokens(content)

            # Compress if needed
            if tokens > self._ofc.compress_above_tokens and candidate.summary:
                content = candidate.summary
                tokens = self._estimate_tokens(content)

            if tokens_used + tokens > effective_budget:
                result.decisions.append(RecallDecision(
                    entry_id=candidate.entry_id,
                    included=False,
                    reason=f"Token budget exhausted ({tokens_used}/{effective_budget})",
                    final_score=final_score,
                    tokens_used=0,
                ))
                result.total_rejected += 1
                continue

            # Include this record
            tokens_used += tokens
            selected_count += 1
            result.records.append(candidate)
            result.decisions.append(RecallDecision(
                entry_id=candidate.entry_id,
                included=True,
                reason="Selected",
                final_score=final_score,
                tokens_used=tokens,
            ))

        result.total_tokens_used = tokens_used
        result.total_selected = selected_count
        result.budget_remaining = effective_budget - tokens_used
        result.recall_tier_used = self._ofc.recall_tier

        return result

    def get_token_usage_report(self, result: FocusResult) -> TokenUsageReport:
        """Generate a token usage report from a FocusResult.

        Designed for the Token Budget Manager UI display.
        """
        avg_tokens = (
            result.total_tokens_used / result.total_selected
            if result.total_selected > 0 else 0
        )
        estimated_cost = (result.total_tokens_used / 1000) * self.COST_PER_1K_TOKENS

        return TokenUsageReport(
            budget=result.total_tokens_used + result.budget_remaining,
            used=result.total_tokens_used,
            remaining=result.budget_remaining,
            records_selected=result.total_selected,
            records_rejected=result.total_rejected,
            avg_tokens_per_record=round(avg_tokens, 1),
            estimated_cost_usd=round(estimated_cost, 6),
            recall_tier=result.recall_tier_used,
        )

    def _apply_temporal_decay(
        self, score: float, created_at: Optional[str]
    ) -> float:
        """Apply temporal decay to relevance score.

        Uses exponential decay based on age and configured halflife.
        """
        if not created_at or self._ofc.temporal_decay_factor == 0:
            return score

        try:
            if isinstance(created_at, str):
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                return score

            now = datetime.now(timezone.utc)
            age_days = max(0, (now - created).total_seconds() / 86400)

            halflife = self._ofc.temporal_decay_halflife_days
            decay = math.exp(-0.693 * age_days / halflife)  # ln(2) ≈ 0.693
            decay_applied = 1.0 - self._ofc.temporal_decay_factor * (1.0 - decay)

            return score * max(0.0, decay_applied)
        except (ValueError, TypeError):
            return score

    def _select_content_by_tier(self, candidate: RecallCandidate) -> str:
        """Select content based on recall tier setting.

        Tier 1: summary if available, else truncated content
        Tier 2: full content
        Tier 3: full content + metadata
        """
        tier = self._ofc.recall_tier

        if tier == 1:
            # Summaries preferred
            if candidate.summary:
                return candidate.summary
            # Truncate to compress_above_tokens
            max_chars = self._ofc.compress_above_tokens * 4
            if len(candidate.content) > max_chars:
                return candidate.content[:max_chars] + "..."
            return candidate.content

        elif tier == 2:
            return candidate.content

        else:  # tier 3
            parts = [candidate.content]
            if candidate.metadata:
                parts.append(f"[metadata: {candidate.metadata}]")
            return "\n".join(parts)

    def _deduplicate(
        self, scored: list[tuple[float, RecallCandidate]]
    ) -> list[tuple[float, RecallCandidate]]:
        """Remove near-duplicate records.

        Uses simple character-level similarity as a fast approximation.
        Full cosine similarity would require embeddings.
        """
        if len(scored) <= 1:
            return scored

        threshold = self._ofc.dedup_similarity
        result = []
        seen_hashes: list[str] = []

        for score, candidate in scored:
            content_normalized = candidate.content.strip().lower()
            # Simple hash-based dedup for exact/near-exact matches
            content_hash = content_normalized[:200]

            is_dup = False
            for seen in seen_hashes:
                similarity = self._char_similarity(content_hash, seen)
                if similarity >= threshold:
                    is_dup = True
                    break

            if not is_dup:
                result.append((score, candidate))
                seen_hashes.append(content_hash)

        return result

    @staticmethod
    def _char_similarity(a: str, b: str) -> float:
        """Simple character-level Jaccard similarity."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        set_a = set(a.split())
        set_b = set(b.split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Approximate token count (4 chars ≈ 1 token)."""
        return max(1, len(text) // 4)
