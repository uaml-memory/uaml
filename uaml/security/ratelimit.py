# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Rate Limiter — protect against abuse and excessive usage.

Token bucket algorithm with per-agent and per-operation limits.

Usage:
    from uaml.security.ratelimit import RateLimiter

    limiter = RateLimiter(rate=10, burst=20)
    if limiter.allow("agent-1", "search"):
        # proceed
    else:
        # rate limited
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Bucket:
    """Token bucket for rate limiting."""
    tokens: float
    last_refill: float
    total_allowed: int = 0
    total_denied: int = 0


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, *, rate: float = 10.0, burst: int = 20):
        """
        Args:
            rate: Tokens per second (sustained rate)
            burst: Maximum burst size (bucket capacity)
        """
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, Bucket] = {}

    def _get_key(self, agent_id: str, operation: str) -> str:
        return f"{agent_id}:{operation}"

    def _refill(self, bucket: Bucket) -> None:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
        bucket.last_refill = now

    def allow(self, agent_id: str, operation: str = "default", *, cost: float = 1.0) -> bool:
        """Check if operation is allowed. Consumes tokens if yes."""
        key = self._get_key(agent_id, operation)

        if key not in self._buckets:
            self._buckets[key] = Bucket(
                tokens=float(self.burst),
                last_refill=time.monotonic(),
            )

        bucket = self._buckets[key]
        self._refill(bucket)

        if bucket.tokens >= cost:
            bucket.tokens -= cost
            bucket.total_allowed += 1
            return True
        else:
            bucket.total_denied += 1
            return False

    def remaining(self, agent_id: str, operation: str = "default") -> float:
        """Get remaining tokens for an agent/operation."""
        key = self._get_key(agent_id, operation)
        bucket = self._buckets.get(key)
        if not bucket:
            return float(self.burst)
        self._refill(bucket)
        return bucket.tokens

    def reset(self, agent_id: str, operation: str = "default") -> None:
        """Reset rate limit for an agent/operation."""
        key = self._get_key(agent_id, operation)
        if key in self._buckets:
            self._buckets[key] = Bucket(
                tokens=float(self.burst),
                last_refill=time.monotonic(),
            )

    def stats(self) -> dict:
        """Rate limiter statistics."""
        total_allowed = sum(b.total_allowed for b in self._buckets.values())
        total_denied = sum(b.total_denied for b in self._buckets.values())
        return {
            "active_buckets": len(self._buckets),
            "total_allowed": total_allowed,
            "total_denied": total_denied,
            "deny_rate": round(total_denied / (total_allowed + total_denied), 4) if (total_allowed + total_denied) > 0 else 0,
            "rate": self.rate,
            "burst": self.burst,
        }
