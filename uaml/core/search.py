# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Convenience search functions for UAML.

These wrap MemoryStore.search() for common use cases.
"""

from __future__ import annotations

from typing import Optional

from uaml.core.store import MemoryStore


def search(
    store: MemoryStore,
    query: str,
    *,
    limit: int = 10,
    **kwargs,
) -> list[dict]:
    """Search knowledge and return dicts (simpler than SearchResult objects).

    Returns list of dicts with keys: id, content, summary, topic, score, snippet.
    """
    results = store.search(query, limit=limit, **kwargs)
    return [
        {
            "id": r.entry.id,
            "content": r.entry.content,
            "summary": r.entry.summary,
            "topic": r.entry.topic,
            "tags": r.entry.tags,
            "score": r.score,
            "snippet": r.snippet,
            "confidence": r.entry.confidence,
            "source_ref": r.entry.source_ref,
        }
        for r in results
    ]


def search_entities(
    store: MemoryStore,
    name: str,
) -> Optional[dict]:
    """Look up an entity and its connected knowledge.

    Returns dict with 'entity' and 'knowledge' keys, or None.
    """
    return store.get_entity(name)
