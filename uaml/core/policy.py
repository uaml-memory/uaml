# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Policy resolution for context budgeting and output complexity.

This module introduces a small but concrete implementation layer for:
- recall tier selection,
- output complexity selection,
- model-aware budgeting,
- provenance policy defaults.

The goal is to reduce unnecessary token usage for cloud models while keeping
local-rich and audit-sensitive workflows capable of deeper context.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class QueryClass(str, Enum):
    """High-level task classification."""

    CASUAL = "casual"
    FACTUAL = "factual"
    OPERATIONAL = "operational"
    PLANNING = "planning"
    STRATEGIC = "strategic"
    AUDIT = "audit"


class RiskLevel(str, Enum):
    """Risk classification for policy decisions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecallTier(str, Enum):
    """How much memory should be injected into the prompt."""

    NONE = "none"
    MICRO = "micro"
    STANDARD = "standard"
    FULL = "full"


class OutputProfile(str, Enum):
    """How complex and detailed the generated answer should be."""

    BRIEF = "brief"
    STANDARD = "standard"
    DEEP = "deep"
    AUDIT = "audit"


class ResponseScope(str, Enum):
    """How far the assistant may expand beyond the user's direct request."""

    DIRECT = "direct"          # Answer only what was asked
    GUIDED = "guided"          # Small next-step hints are allowed
    STRATEGIC = "strategic"    # Broader synthesis and recommendations allowed


class ModelProfile(str, Enum):
    """Policy-oriented model classes.

    The important distinction is not just cloud vs local, but also:
    - context window strength,
    - token price pressure,
    - reasoning capability.
    """

    CLOUD_FAST = "cloud_fast"
    CLOUD_STANDARD = "cloud_standard"
    CLOUD_LARGE_CONTEXT = "cloud_large_context"
    CLOUD_EXPENSIVE = "cloud_expensive"
    LOCAL_WEAK = "local_weak"
    LOCAL_RICH = "local_rich"
    CERTIFICATION = "certification"


class ProvenanceMode(str, Enum):
    """How much provenance to include by default."""

    OFF = "off"
    MINIMAL = "minimal"
    FULL = "full"


@dataclass(frozen=True)
class PolicyDecision:
    """Resolved policy decision for one request."""

    recall_tier: RecallTier
    output_profile: OutputProfile
    response_scope: ResponseScope
    budget_tokens: int
    provenance_mode: ProvenanceMode


_BUDGETS: dict[RecallTier, tuple[int, int]] = {
    RecallTier.NONE: (0, 0),
    RecallTier.MICRO: (100, 300),
    RecallTier.STANDARD: (300, 900),
    RecallTier.FULL: (900, 2500),
}


def _mid_budget(tier: RecallTier) -> int:
    low, high = _BUDGETS[tier]
    return (low + high) // 2


def resolve_policy(
    query_class: QueryClass,
    model_profile: ModelProfile,
    risk_level: RiskLevel = RiskLevel.LOW,
) -> PolicyDecision:
    """Resolve recall tier, output complexity, budget, and provenance mode.

    This is intentionally deterministic and conservative.
    It can later be replaced or extended by a configurable policy engine.
    """

    # Certification / audit mode always wins.
    if model_profile == ModelProfile.CERTIFICATION or query_class == QueryClass.AUDIT:
        return PolicyDecision(
            recall_tier=RecallTier.FULL,
            output_profile=OutputProfile.AUDIT,
            response_scope=ResponseScope.STRATEGIC,
            budget_tokens=_mid_budget(RecallTier.FULL),
            provenance_mode=ProvenanceMode.FULL,
        )

    if query_class == QueryClass.CASUAL:
        return PolicyDecision(
            recall_tier=RecallTier.NONE,
            output_profile=OutputProfile.BRIEF,
            response_scope=ResponseScope.DIRECT,
            budget_tokens=0,
            provenance_mode=ProvenanceMode.OFF,
        )

    if model_profile in {ModelProfile.CLOUD_FAST, ModelProfile.CLOUD_EXPENSIVE}:
        if query_class == QueryClass.FACTUAL:
            return PolicyDecision(
                recall_tier=RecallTier.MICRO,
                output_profile=OutputProfile.BRIEF,
                response_scope=ResponseScope.DIRECT,
                budget_tokens=_mid_budget(RecallTier.MICRO),
                provenance_mode=ProvenanceMode.MINIMAL if risk_level != RiskLevel.LOW else ProvenanceMode.OFF,
            )
        if query_class in {QueryClass.OPERATIONAL, QueryClass.PLANNING}:
            return PolicyDecision(
                recall_tier=RecallTier.MICRO,
                output_profile=OutputProfile.STANDARD,
                response_scope=ResponseScope.GUIDED,
                budget_tokens=_mid_budget(RecallTier.MICRO),
                provenance_mode=ProvenanceMode.MINIMAL,
            )
        return PolicyDecision(
            recall_tier=RecallTier.STANDARD,
            output_profile=OutputProfile.STANDARD,
            response_scope=ResponseScope.GUIDED,
            budget_tokens=_mid_budget(RecallTier.STANDARD),
            provenance_mode=ProvenanceMode.MINIMAL,
        )

    if model_profile == ModelProfile.CLOUD_STANDARD:
        if query_class == QueryClass.FACTUAL:
            tier = RecallTier.MICRO
            profile = OutputProfile.BRIEF
            scope = ResponseScope.DIRECT
        elif query_class in {QueryClass.OPERATIONAL, QueryClass.PLANNING}:
            tier = RecallTier.STANDARD
            profile = OutputProfile.STANDARD
            scope = ResponseScope.GUIDED
        else:
            tier = RecallTier.STANDARD
            profile = OutputProfile.DEEP
            scope = ResponseScope.STRATEGIC
        return PolicyDecision(
            recall_tier=tier,
            output_profile=profile,
            response_scope=scope,
            budget_tokens=_mid_budget(tier),
            provenance_mode=ProvenanceMode.MINIMAL,
        )

    if model_profile == ModelProfile.CLOUD_LARGE_CONTEXT:
        if query_class == QueryClass.STRATEGIC:
            return PolicyDecision(
                recall_tier=RecallTier.FULL if risk_level == RiskLevel.HIGH else RecallTier.STANDARD,
                output_profile=OutputProfile.DEEP,
                response_scope=ResponseScope.STRATEGIC,
                budget_tokens=_mid_budget(RecallTier.FULL if risk_level == RiskLevel.HIGH else RecallTier.STANDARD),
                provenance_mode=ProvenanceMode.MINIMAL if risk_level != RiskLevel.HIGH else ProvenanceMode.FULL,
            )
        return PolicyDecision(
            recall_tier=RecallTier.STANDARD,
            output_profile=OutputProfile.STANDARD,
            response_scope=ResponseScope.GUIDED,
            budget_tokens=_mid_budget(RecallTier.STANDARD),
            provenance_mode=ProvenanceMode.MINIMAL,
        )

    if model_profile == ModelProfile.LOCAL_WEAK:
        if query_class == QueryClass.FACTUAL:
            tier = RecallTier.MICRO
            scope = ResponseScope.DIRECT
        elif query_class in {QueryClass.OPERATIONAL, QueryClass.PLANNING}:
            tier = RecallTier.MICRO
            scope = ResponseScope.GUIDED
        else:
            tier = RecallTier.STANDARD
            scope = ResponseScope.GUIDED
        return PolicyDecision(
            recall_tier=tier,
            output_profile=OutputProfile.BRIEF if query_class != QueryClass.STRATEGIC else OutputProfile.STANDARD,
            response_scope=scope,
            budget_tokens=_mid_budget(tier),
            provenance_mode=ProvenanceMode.MINIMAL if risk_level == RiskLevel.HIGH else ProvenanceMode.OFF,
        )

    # LOCAL_RICH default path.
    tier = RecallTier.MICRO
    profile = OutputProfile.BRIEF
    scope = ResponseScope.DIRECT
    provenance = ProvenanceMode.OFF

    if query_class in {QueryClass.OPERATIONAL, QueryClass.PLANNING}:
        tier = RecallTier.STANDARD
        profile = OutputProfile.STANDARD
        scope = ResponseScope.GUIDED
        provenance = ProvenanceMode.MINIMAL
    elif query_class == QueryClass.STRATEGIC:
        tier = RecallTier.FULL if risk_level == RiskLevel.HIGH else RecallTier.STANDARD
        profile = OutputProfile.DEEP
        scope = ResponseScope.STRATEGIC
        provenance = ProvenanceMode.MINIMAL if risk_level != RiskLevel.HIGH else ProvenanceMode.FULL
    elif query_class == QueryClass.FACTUAL:
        tier = RecallTier.MICRO
        profile = OutputProfile.BRIEF
        scope = ResponseScope.DIRECT

    return PolicyDecision(
        recall_tier=tier,
        output_profile=profile,
        response_scope=scope,
        budget_tokens=_mid_budget(tier),
        provenance_mode=provenance,
    )
