"""Tests for UAML Search Cache."""

from __future__ import annotations

import time
import pytest

from uaml.reasoning.cache import SearchCache


class TestSearchCache:
    def test_put_and_get(self):
        cache = SearchCache()
        cache.put("python", ["result1"])
        assert cache.get("python") == ["result1"]

    def test_miss(self):
        cache = SearchCache()
        assert cache.get("missing") is None

    def test_ttl_expiry(self):
        cache = SearchCache(ttl_seconds=0.01)
        cache.put("key", "value")
        time.sleep(0.02)
        assert cache.get("key") is None

    def test_lru_eviction(self):
        cache = SearchCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_invalidate(self):
        cache = SearchCache()
        cache.put("key", "val")
        assert cache.invalidate("key") is True
        assert cache.invalidate("key") is False

    def test_clear(self):
        cache = SearchCache()
        cache.put("a", 1)
        cache.put("b", 2)
        assert cache.clear() == 2
        assert cache.get("a") is None

    def test_stats(self):
        cache = SearchCache()
        cache.put("a", 1)
        cache.get("a")  # hit
        cache.get("b")  # miss
        stats = cache.stats()
        assert stats["total_hits"] == 1
        assert stats["total_misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_hot_keys(self):
        cache = SearchCache()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")
        cache.get("a")
        cache.get("b")
        hot = cache.hot_keys()
        assert hot[0]["key"] == "a"
        assert hot[0]["hits"] == 2

    def test_cleanup_expired(self):
        cache = SearchCache(ttl_seconds=0.01)
        cache.put("old", 1)
        time.sleep(0.02)
        cache.put("new", 2)
        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.get("new") == 2

    def test_update_existing(self):
        cache = SearchCache()
        cache.put("key", "v1")
        cache.put("key", "v2")
        assert cache.get("key") == "v2"
