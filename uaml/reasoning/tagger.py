# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Auto-Tagger — automatic topic and tag suggestion for entries.

Uses keyword extraction, topic patterns, and content analysis
to suggest relevant tags for knowledge entries.

Usage:
    from uaml.reasoning.tagger import AutoTagger

    tagger = AutoTagger()
    tags = tagger.suggest("Python 3.12 introduces new typing features")
    # ["python", "typing", "programming", "update"]
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional


# Topic keyword maps
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "security": ["encrypt", "auth", "password", "firewall", "vulnerability", "ssl", "tls", "pqc", "kem", "certificate", "token", "oauth"],
    "database": ["sql", "sqlite", "postgres", "mysql", "query", "index", "schema", "migration", "table", "column"],
    "python": ["python", "pip", "pytest", "django", "flask", "fastapi", "pydantic", "typing", "dataclass", "asyncio"],
    "infrastructure": ["docker", "kubernetes", "nginx", "ssh", "server", "deploy", "ci", "cd", "pipeline", "ansible"],
    "compliance": ["gdpr", "audit", "consent", "dpia", "breach", "iso", "certification", "regulation", "privacy"],
    "ai": ["model", "llm", "embedding", "inference", "training", "neural", "transformer", "gpt", "claude", "ollama"],
    "networking": ["ip", "port", "tcp", "udp", "http", "https", "dns", "firewall", "proxy", "vpn", "nat"],
    "memory": ["uaml", "memory", "recall", "knowledge", "learning", "store", "entry", "retention"],
    "crypto": ["encrypt", "decrypt", "hash", "sign", "key", "escrow", "pqc", "ml-kem", "aes", "sha"],
    "testing": ["test", "pytest", "unittest", "mock", "fixture", "assert", "coverage", "tdd"],
}

# Stopwords to exclude
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "don", "now", "and", "but", "or", "if", "this", "that", "these",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he",
    "him", "his", "she", "her", "they", "them", "their", "what", "which",
}


@dataclass
class TagSuggestion:
    """A suggested tag with confidence."""
    tag: str
    confidence: float
    source: str  # keyword, topic, frequency


class AutoTagger:
    """Suggest tags for knowledge content."""

    def __init__(self, *, custom_topics: Optional[dict[str, list[str]]] = None):
        self.topics = {**TOPIC_KEYWORDS}
        if custom_topics:
            self.topics.update(custom_topics)

    def suggest(self, content: str, *, max_tags: int = 8) -> list[TagSuggestion]:
        """Suggest tags for content.

        Combines topic matching, keyword extraction, and frequency analysis.
        """
        suggestions: list[TagSuggestion] = []
        seen: set[str] = set()

        # 1. Topic matching
        content_lower = content.lower()
        for topic, keywords in self.topics.items():
            matches = sum(1 for kw in keywords if kw in content_lower)
            if matches >= 2:
                if topic not in seen:
                    seen.add(topic)
                    suggestions.append(TagSuggestion(
                        tag=topic,
                        confidence=min(1.0, 0.5 + matches * 0.1),
                        source="topic",
                    ))

        # 2. Keyword extraction (top frequent meaningful words)
        words = re.findall(r'[a-zA-Z]{3,}', content_lower)
        words = [w for w in words if w not in STOPWORDS and len(w) > 3]
        freq = Counter(words)

        for word, count in freq.most_common(10):
            if word not in seen and count >= 1:
                seen.add(word)
                suggestions.append(TagSuggestion(
                    tag=word,
                    confidence=min(0.8, 0.3 + count * 0.1),
                    source="frequency",
                ))

        # 3. Technical patterns
        if re.search(r'v\d+\.\d+', content):
            if "version" not in seen:
                seen.add("version")
                suggestions.append(TagSuggestion(tag="version", confidence=0.7, source="keyword"))

        if re.search(r'https?://', content):
            if "reference" not in seen:
                seen.add("reference")
                suggestions.append(TagSuggestion(tag="reference", confidence=0.6, source="keyword"))

        if re.search(r'(?:bug|fix|error|issue|patch)', content_lower):
            if "bugfix" not in seen:
                seen.add("bugfix")
                suggestions.append(TagSuggestion(tag="bugfix", confidence=0.7, source="keyword"))

        # Sort by confidence, limit
        suggestions.sort(key=lambda s: s.confidence, reverse=True)
        return suggestions[:max_tags]

    def suggest_tags_str(self, content: str, *, max_tags: int = 5) -> str:
        """Convenience: return comma-separated tag string."""
        suggestions = self.suggest(content, max_tags=max_tags)
        return ",".join(s.tag for s in suggestions)

    def auto_tag_entry(self, content: str, existing_tags: str = "") -> str:
        """Merge suggested tags with existing, dedup."""
        existing = set(t.strip() for t in existing_tags.split(",") if t.strip())
        suggested = self.suggest(content, max_tags=5)
        new_tags = [s.tag for s in suggested if s.tag not in existing]
        all_tags = sorted(existing | set(new_tags))
        return ",".join(all_tags)
