"""Tests for UAML Rate Limiter."""

from __future__ import annotations

import pytest

from uaml.security.ratelimit import RateLimiter


class TestRateLimiter:
    def test_allow_within_burst(self):
        limiter = RateLimiter(rate=10, burst=5)
        for _ in range(5):
            assert limiter.allow("agent1", "search") is True

    def test_deny_over_burst(self):
        limiter = RateLimiter(rate=0.1, burst=2)
        assert limiter.allow("a", "op") is True
        assert limiter.allow("a", "op") is True
        assert limiter.allow("a", "op") is False

    def test_per_agent_isolation(self):
        limiter = RateLimiter(rate=0.1, burst=1)
        assert limiter.allow("agent1", "search") is True
        assert limiter.allow("agent2", "search") is True
        assert limiter.allow("agent1", "search") is False

    def test_per_operation_isolation(self):
        limiter = RateLimiter(rate=0.1, burst=1)
        assert limiter.allow("a", "search") is True
        assert limiter.allow("a", "learn") is True
        assert limiter.allow("a", "search") is False

    def test_remaining(self):
        limiter = RateLimiter(rate=10, burst=5)
        assert limiter.remaining("a") == 5.0
        limiter.allow("a")
        assert limiter.remaining("a") < 5.0

    def test_reset(self):
        limiter = RateLimiter(rate=0.1, burst=2)
        limiter.allow("a")
        limiter.allow("a")
        limiter.reset("a")
        assert limiter.allow("a") is True

    def test_stats(self):
        limiter = RateLimiter(rate=0.1, burst=1)
        limiter.allow("a")
        limiter.allow("a")  # denied
        stats = limiter.stats()
        assert stats["total_allowed"] == 1
        assert stats["total_denied"] == 1
        assert stats["deny_rate"] == 0.5

    def test_cost(self):
        limiter = RateLimiter(rate=10, burst=5)
        assert limiter.allow("a", cost=3) is True
        assert limiter.remaining("a") < 3

    def test_empty_stats(self):
        limiter = RateLimiter()
        stats = limiter.stats()
        assert stats["active_buckets"] == 0
