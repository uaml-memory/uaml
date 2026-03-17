# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Context Builder — assemble relevant context for LLM prompts.

Pulls knowledge entries, applies relevance ranking, deduplication,
and token budgeting to build optimal context windows.

Usage:
    from uaml.reasoning.context import ContextBuilder

    builder = ContextBuilder(store)
    ctx = builder.build("What is Python's GIL?", max_tokens=2000)
    print(ctx.text)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class ContextEntry:
    """A single context entry with relevance score."""
    content: str
    topic: str
    confidence: float
    relevance: float
    source: str = ""
    entry_id: int = 0


@dataclass
class ContextWindow:
    """Assembled context window."""
    entries: list[ContextEntry] = field(default_factory=list)
    total_chars: int = 0
    token_estimate: int = 0
    query: str = ""

    @property
    def text(self) -> str:
        """Get assembled context as text."""
        parts = []
        for e in self.entries:
            header = f"[{e.topic}] (confidence: {e.confidence:.0%})"
            parts.append(f"{header}\n{e.content}")
        return "\n\n---\n\n".join(parts)

    @property
    def count(self) -> int:
        return len(self.entries)


class ContextBuilder:
    """Build context windows from knowledge store."""

    CHARS_PER_TOKEN = 4  # Rough estimate

    def __init__(self, store: MemoryStore):
        self.store = store

    def build(
        self,
        query: str,
        *,
        max_tokens: int = 4000,
        max_entries: int = 20,
        min_confidence: float = 0.0,
        topics: Optional[list[str]] = None,
        data_layers: Optional[list[str]] = None,
        deduplicate: bool = True,
    ) -> ContextWindow:
        """Build context window for a query.

        Args:
            query: Search query
            max_tokens: Token budget
            max_entries: Maximum entries to include
            min_confidence: Minimum confidence threshold
            topics: Filter by topics
            data_layers: Filter by data layers
            deduplicate: Remove near-duplicate content
        """
        # Search for relevant entries
        if not query:
            # Empty query — get recent entries
            try:
                rows = self.store._conn.execute(
                    "SELECT * FROM knowledge ORDER BY updated_at DESC LIMIT ?",
                    (max_entries * 2,)
                ).fetchall()
                results = [dict(r) for r in rows]
            except Exception:
                results = []
        else:
            try:
                results = self.store.search(query, limit=max_entries * 2)
                # Convert SearchResult objects to dicts if needed
                if results and hasattr(results[0], '__dict__') and not isinstance(results[0], dict):
                    results = [vars(r) if hasattr(r, '__dict__') else r for r in results]
                elif results and hasattr(results[0], 'keys'):
                    results = [dict(r) for r in results]
            except Exception:
                results = []

        # Apply filters — handle both SearchResult objects and dicts
        entries = []
        for r in results:
            # Normalize to dict
            if hasattr(r, 'entry'):
                # SearchResult dataclass
                e = r.entry
                content = getattr(e, 'content', '')
                topic = getattr(e, 'topic', '')
                conf = getattr(e, 'confidence', 0)
                layer = str(getattr(e, 'data_layer', ''))
                # Handle enum values
                if hasattr(layer, 'value'):
                    layer = layer.value
                src = getattr(e, 'source_ref', '')
                eid = getattr(e, 'id', 0)
                score = getattr(r, 'score', 0.5)
            elif isinstance(r, dict):
                content = r.get('content', '')
                topic = r.get('topic', '')
                conf = r.get('confidence', 0)
                layer = str(r.get('data_layer', ''))
                src = r.get('source_ref', '')
                eid = r.get('id', 0)
                score = r.get('score', 0.5)
            else:
                continue

            if conf < min_confidence:
                continue
            if topics and topic not in topics:
                continue
            if data_layers and layer not in data_layers:
                continue

            entries.append(ContextEntry(
                content=content,
                topic=topic,
                confidence=conf,
                relevance=score,
                source=src,
                entry_id=eid,
            ))

        # Deduplicate
        if deduplicate:
            entries = self._deduplicate(entries)

        # Sort by relevance
        entries.sort(key=lambda e: e.relevance, reverse=True)

        # Token budgeting
        max_chars = max_tokens * self.CHARS_PER_TOKEN
        window = ContextWindow(query=query)

        for entry in entries:
            entry_chars = len(entry.content) + len(entry.topic) + 50  # overhead
            if window.total_chars + entry_chars > max_chars:
                # Try to fit a truncated version
                remaining = max_chars - window.total_chars - 50
                if remaining > 100:
                    entry.content = entry.content[:remaining] + "..."
                    entry_chars = len(entry.content) + len(entry.topic) + 50
                else:
                    break

            window.entries.append(entry)
            window.total_chars += entry_chars

            if len(window.entries) >= max_entries:
                break

        window.token_estimate = window.total_chars // self.CHARS_PER_TOKEN
        return window

    def _deduplicate(self, entries: list[ContextEntry]) -> list[ContextEntry]:
        """Remove near-duplicate entries based on content similarity."""
        if not entries:
            return entries

        unique = [entries[0]]
        for entry in entries[1:]:
            is_dup = False
            for existing in unique:
                # Simple overlap check
                shorter = min(len(entry.content), len(existing.content))
                if shorter > 0:
                    overlap = self._content_overlap(entry.content, existing.content)
                    if overlap > 0.8:
                        is_dup = True
                        break
            if not is_dup:
                unique.append(entry)

        return unique

    def _content_overlap(self, a: str, b: str) -> float:
        """Rough content overlap ratio using word sets."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        return len(intersection) / min(len(words_a), len(words_b))
