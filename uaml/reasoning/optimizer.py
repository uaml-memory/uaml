# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Query Optimizer — improve search queries for better results.

Expands queries with synonyms, normalizes terms, suggests alternatives,
and provides query analysis.

Usage:
    from uaml.reasoning.optimizer import QueryOptimizer

    opt = QueryOptimizer()
    result = opt.optimize("py threading")
    print(result.expanded_query)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OptimizedQuery:
    """Result of query optimization."""
    original: str
    expanded: str
    normalized: str
    suggestions: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)

    @property
    def expanded_query(self) -> str:
        return self.expanded


class QueryOptimizer:
    """Optimize search queries for better results."""

    # Common abbreviation expansions
    EXPANSIONS = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "db": "database",
        "sql": "SQL",
        "api": "API",
        "auth": "authentication",
        "config": "configuration",
        "env": "environment",
        "infra": "infrastructure",
        "k8s": "kubernetes",
        "msg": "message",
        "req": "request",
        "res": "response",
        "sec": "security",
        "perf": "performance",
        "mem": "memory",
        "async": "asynchronous",
    }

    # Synonym groups for query expansion
    SYNONYMS = {
        "error": ["exception", "failure", "bug"],
        "fast": ["quick", "performance", "speed"],
        "delete": ["remove", "drop", "purge"],
        "create": ["add", "insert", "new"],
        "update": ["modify", "change", "edit"],
        "find": ["search", "query", "lookup"],
    }

    def __init__(self, *, custom_expansions: Optional[dict] = None):
        self._expansions = dict(self.EXPANSIONS)
        if custom_expansions:
            self._expansions.update(custom_expansions)

    def optimize(self, query: str) -> OptimizedQuery:
        """Optimize a search query."""
        if not query or not query.strip():
            return OptimizedQuery(original=query, expanded="", normalized="")

        transformations = []

        # Normalize
        normalized = self._normalize(query)
        if normalized != query:
            transformations.append(f"normalized: '{query}' → '{normalized}'")

        # Expand abbreviations
        expanded = self._expand_abbreviations(normalized)
        if expanded != normalized:
            transformations.append(f"expanded: '{normalized}' → '{expanded}'")

        # Generate suggestions
        suggestions = self._suggest_alternatives(expanded)

        return OptimizedQuery(
            original=query,
            expanded=expanded,
            normalized=normalized,
            suggestions=suggestions,
            transformations=transformations,
        )

    def _normalize(self, query: str) -> str:
        """Normalize query string."""
        # Lowercase
        q = query.lower().strip()
        # Remove extra whitespace
        q = re.sub(r"\s+", " ", q)
        # Remove special chars except quotes and operators
        q = re.sub(r"[^\w\s\"'*-]", "", q)
        return q

    def _expand_abbreviations(self, query: str) -> str:
        """Expand known abbreviations."""
        words = query.split()
        expanded = []
        for word in words:
            if word in self._expansions:
                expanded.append(self._expansions[word])
            else:
                expanded.append(word)
        return " ".join(expanded)

    def _suggest_alternatives(self, query: str) -> list[str]:
        """Suggest alternative queries using synonyms."""
        suggestions = []
        words = query.split()

        for i, word in enumerate(words):
            if word in self.SYNONYMS:
                for syn in self.SYNONYMS[word][:2]:
                    alt = words[:i] + [syn] + words[i+1:]
                    suggestions.append(" ".join(alt))

        return suggestions[:5]

    def add_expansion(self, abbreviation: str, full: str) -> None:
        """Add a custom abbreviation expansion."""
        self._expansions[abbreviation] = full

    def analyze(self, query: str) -> dict:
        """Analyze query characteristics."""
        words = query.strip().split()
        return {
            "word_count": len(words),
            "char_count": len(query),
            "has_quotes": '"' in query or "'" in query,
            "has_operators": any(op in query.upper() for op in ["AND", "OR", "NOT"]),
            "has_wildcards": "*" in query,
            "abbreviations": [w for w in words if w.lower() in self._expansions],
        }
