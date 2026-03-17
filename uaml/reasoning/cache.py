# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Search Cache — LRU cache for frequent queries.

Reduces latency for repeated searches with TTL-based expiration.

Usage:
    from uaml.reasoning.cache import SearchCache

    cache = SearchCache(max_size=100, ttl_seconds=300)
    cache.put("python GIL", [result1, result2])
    results = cache.get("python GIL")
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CacheEntry:
    """A cached search result."""
    key: str
    value: Any
    created_at: float
    hits: int = 0


class SearchCache:
    """LRU cache with TTL for search results."""

    def __init__(self, *, max_size: int = 256, ttl_seconds: float = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._total_hits = 0
        self._total_misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get cached value. Returns None on miss or expiry."""
        entry = self._cache.get(key)
        if entry is None:
            self._total_misses += 1
            return None

        # Check TTL
        if time.time() - entry.created_at > self.ttl_seconds:
            del self._cache[key]
            self._total_misses += 1
            return None

        # Move to end (most recent)
        self._cache.move_to_end(key)
        entry.hits += 1
        self._total_hits += 1
        return entry.value

    def put(self, key: str, value: Any) -> None:
        """Cache a value."""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key].value = value
            self._cache[key].created_at = time.time()
            return

        if len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)  # Remove oldest

        self._cache[key] = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
        )

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if found."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        expired = [
            k for k, v in self._cache.items()
            if now - v.created_at > self.ttl_seconds
        ]
        for k in expired:
            del self._cache[k]
        return len(expired)

    def stats(self) -> dict:
        """Cache statistics."""
        total = self._total_hits + self._total_misses
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds,
            "total_hits": self._total_hits,
            "total_misses": self._total_misses,
            "hit_rate": round(self._total_hits / total, 4) if total > 0 else 0,
        }

    def hot_keys(self, *, limit: int = 10) -> list[dict]:
        """Get most frequently accessed keys."""
        entries = sorted(self._cache.values(), key=lambda e: e.hits, reverse=True)
        return [
            {"key": e.key, "hits": e.hits}
            for e in entries[:limit]
        ]
