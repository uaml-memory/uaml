# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Input Filter Stages — pluggable ingest pipeline stages.

These stages integrate with IngestPipeline to enforce Focus Engine
input filter rules before data enters Neo4j/storage.

Each stage reads configuration from FocusEngineConfig (input_filter section)
and rejects items that violate the rules.

Designed for certifiability:
- Every rejection is logged with reason
- Every stage is independently testable
- Configuration is human-controlled only

© 2026 GLG, a.s. — UAML Focus Engine
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from uaml.core.focus_config import FocusEngineConfig, InputFilterConfig
from uaml.ingest.pipeline import IngestItem


# ---------------------------------------------------------------------------
# PII patterns (conservative defaults — extendable)
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_intl": re.compile(r"\+\d{1,3}[\s.-]?\d{3,14}"),
    "phone_cz": re.compile(r"\b\d{3}[\s]?\d{3}[\s]?\d{3}\b"),
    "czech_birth_number": re.compile(r"\b\d{6}/?\d{3,4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{0,4}\b"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "czech_ico": re.compile(r"\bIČO?:\s*\d{8}\b"),
    "czech_dic": re.compile(r"\bDIČ:\s*CZ\d{8,10}\b"),
}


@dataclass
class PIIDetectionResult:
    """Result of PII detection scan."""
    has_pii: bool = False
    detected_types: list[str] = field(default_factory=list)
    match_count: int = 0


@dataclass
class FilterAuditEntry:
    """Audit log entry for filter decisions.

    Every accept/reject is logged for compliance and traceability.
    """
    timestamp: str
    stage: str
    item_hash: str
    decision: str  # "accept", "reject"
    reason: str = ""
    config_snapshot: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-process)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Simple sliding window rate limiter."""

    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Check if request is within rate limit.

        Returns True if allowed, False if rate limited.
        """
        now = time.monotonic()
        window = self._windows[key]
        # Remove expired entries
        cutoff = now - window_seconds
        self._windows[key] = [t for t in window if t > cutoff]
        window = self._windows[key]

        if len(window) >= limit:
            return False

        window.append(now)
        return True


# Global rate limiter instance
_rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# Filter stages
# ---------------------------------------------------------------------------

def _content_hash(content: str) -> str:
    """Generate SHA-256 hash of content for dedup and audit."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def create_length_filter(config: InputFilterConfig):
    """Create a min-length filter stage.

    Rejects items shorter than config.min_entry_length characters.
    """
    def length_filter(item: IngestItem) -> IngestItem:
        if len(item.content.strip()) < config.min_entry_length:
            item.rejected = True
            item.reject_reason = (
                f"Content too short: {len(item.content.strip())} chars "
                f"< minimum {config.min_entry_length}"
            )
        return item
    return length_filter


def create_max_tokens_filter(config: InputFilterConfig):
    """Create a max-tokens filter stage.

    Rejects items exceeding config.max_entry_tokens.
    Uses approximate tokenization (4 chars ≈ 1 token).
    """
    def max_tokens_filter(item: IngestItem) -> IngestItem:
        approx_tokens = len(item.content) // 4
        if approx_tokens > config.max_entry_tokens:
            item.rejected = True
            item.reject_reason = (
                f"Content too large: ~{approx_tokens} tokens "
                f"> maximum {config.max_entry_tokens}"
            )
        return item
    return max_tokens_filter


def create_pii_detector(config: InputFilterConfig):
    """Create a PII detection stage.

    Scans content for PII patterns and tags item metadata.
    Does NOT reject — marks for downstream handling.
    """
    def pii_detector(item: IngestItem) -> IngestItem:
        if not config.pii_detection:
            return item

        result = detect_pii(item.content)
        if result.has_pii:
            item.metadata["pii_detected"] = True
            item.metadata["pii_types"] = result.detected_types
            item.metadata["pii_match_count"] = result.match_count
            # Auto-tag sensitivity
            item.metadata.setdefault("sensitivity", 3)
            if "health" in str(result.detected_types) or "credit_card" in result.detected_types:
                item.metadata["sensitivity"] = 5

        return item
    return pii_detector


def create_category_filter(config: InputFilterConfig):
    """Create a category enforcement stage.

    Checks item category against allowed/denied categories.
    Rejects items in denied categories.
    """
    def category_filter(item: IngestItem) -> IngestItem:
        category = item.metadata.get("category", item.topic or "").lower()

        if not category and config.require_classification:
            item.rejected = True
            item.reject_reason = "No category assigned and require_classification=true"
            return item

        if category in config.categories:
            action = config.categories[category]
            if action == "deny":
                item.rejected = True
                item.reject_reason = f"Category '{category}' is denied by input filter"
                return item
            elif action == "encrypt":
                item.metadata["requires_encryption"] = True
            elif action == "require_consent":
                if not item.metadata.get("consent_given", False):
                    item.rejected = True
                    item.reject_reason = (
                        f"Category '{category}' requires consent "
                        f"(set metadata.consent_given=true)"
                    )
                    return item

        return item
    return category_filter


def create_rate_limit_filter(config: InputFilterConfig):
    """Create a rate limiting stage.

    Rejects items when write rate exceeds config.rate_limit_per_min.
    """
    def rate_limit_filter(item: IngestItem) -> IngestItem:
        agent_id = item.metadata.get("agent_id", "default")
        if not _rate_limiter.check(agent_id, config.rate_limit_per_min):
            item.rejected = True
            item.reject_reason = (
                f"Rate limit exceeded: {config.rate_limit_per_min}/min "
                f"for agent '{agent_id}'"
            )
        return item
    return rate_limit_filter


def create_relevance_gate(config: InputFilterConfig):
    """Create a relevance score gate.

    Rejects items with relevance score below config.min_relevance_score.
    Relevance must be set in item.metadata['relevance_score'] by
    an upstream enrichment stage.
    """
    def relevance_gate(item: IngestItem) -> IngestItem:
        score = item.metadata.get("relevance_score")
        if score is not None and score < config.min_relevance_score:
            item.rejected = True
            item.reject_reason = (
                f"Relevance score {score:.3f} "
                f"< minimum {config.min_relevance_score}"
            )
        return item
    return relevance_gate


# ---------------------------------------------------------------------------
# PII detection utility
# ---------------------------------------------------------------------------

def detect_pii(text: str) -> PIIDetectionResult:
    """Scan text for PII patterns.

    Returns detection result with types found and match count.
    """
    result = PIIDetectionResult()

    for pii_type, pattern in PII_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            result.has_pii = True
            result.detected_types.append(pii_type)
            result.match_count += len(matches)

    return result


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def setup_input_filter(pipeline, config: FocusEngineConfig) -> None:
    """Configure an IngestPipeline with Focus Engine input filter stages.

    Removes default length_check and replaces with Focus Engine stages.
    Stages are applied in order:
    1. length_filter — reject too short
    2. max_tokens_filter — reject too large
    3. rate_limit_filter — enforce rate limit
    4. category_filter — enforce category rules
    5. pii_detector — detect and tag PII
    6. relevance_gate — enforce minimum relevance

    Args:
        pipeline: IngestPipeline instance
        config: FocusEngineConfig with input_filter settings
    """
    ifc = config.input_filter

    # Remove default length_check
    pipeline.remove_stage("length_check")

    # Add Focus Engine stages in order
    pipeline.add_stage("fe_length_filter", create_length_filter(ifc))
    pipeline.add_stage("fe_max_tokens_filter", create_max_tokens_filter(ifc))
    pipeline.add_stage("fe_rate_limit", create_rate_limit_filter(ifc))
    pipeline.add_stage("fe_category_filter", create_category_filter(ifc))
    pipeline.add_stage("fe_pii_detector", create_pii_detector(ifc))
    pipeline.add_stage("fe_relevance_gate", create_relevance_gate(ifc))
