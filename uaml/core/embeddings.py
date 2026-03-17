# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Embeddings — abstraction layer for vector embeddings.

Supports multiple backends: local (TF-IDF), Ollama, OpenAI-compatible.
Used for semantic search improvement and similarity scoring.

Usage:
    from uaml.core.embeddings import EmbeddingEngine

    engine = EmbeddingEngine(backend="tfidf")
    vec = engine.embed("Python is great for AI")
    sim = engine.similarity("Python AI", "Machine learning with Python")
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional


class EmbeddingEngine:
    """Multi-backend embedding engine."""

    def __init__(self, backend: str = "tfidf"):
        """Initialize embedding engine.

        Args:
            backend: "tfidf" (local, no deps), "ollama", or "openai"
        """
        self.backend = backend
        self._idf_cache: dict[str, float] = {}
        self._doc_count = 0

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization."""
        return [w.lower() for w in re.findall(r'[a-zA-Z]{2,}', text)]

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text.

        For TF-IDF backend, returns a sparse-ish vector based on
        term frequencies. For external backends, would call API.
        """
        if self.backend == "tfidf":
            return self._tfidf_embed(text)
        elif self.backend == "bow":
            return self._bow_embed(text)
        else:
            raise ValueError(f"Backend '{self.backend}' not available locally. Use 'tfidf' or 'bow'.")

    def _tfidf_embed(self, text: str) -> list[float]:
        """TF-IDF based embedding (local, deterministic)."""
        tokens = self._tokenize(text)
        if not tokens:
            return []

        # Term frequency
        tf = Counter(tokens)
        total = len(tokens)

        # Build vector (sorted keys for consistency)
        vocab = sorted(tf.keys())
        vector = []
        for term in vocab:
            freq = tf[term] / total
            # Simple IDF approximation (log smoothing)
            idf = math.log(1 + 1.0 / (1 + self._idf_cache.get(term, 0.1)))
            vector.append(round(freq * idf, 6))

        return vector

    def _bow_embed(self, text: str) -> list[float]:
        """Bag-of-words embedding."""
        tokens = self._tokenize(text)
        if not tokens:
            return []
        tf = Counter(tokens)
        vocab = sorted(tf.keys())
        return [float(tf[t]) for t in vocab]

    def similarity(self, text_a: str, text_b: str) -> float:
        """Calculate cosine similarity between two texts.

        Uses word overlap for efficiency (no embedding needed).
        """
        tokens_a = set(self._tokenize(text_a))
        tokens_b = set(self._tokenize(text_b))

        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b

        # Jaccard similarity (simpler, more robust than cosine for sparse)
        return len(intersection) / len(union)

    def cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Cosine similarity between two vectors."""
        if not vec_a or not vec_b:
            return 0.0

        # Pad to same length
        max_len = max(len(vec_a), len(vec_b))
        a = vec_a + [0.0] * (max_len - len(vec_a))
        b = vec_b + [0.0] * (max_len - len(vec_b))

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def batch_similarity(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        """Rank documents by similarity to query.

        Returns list of (index, score) sorted by score descending.
        """
        results = []
        for i, doc in enumerate(documents):
            score = self.similarity(query, doc)
            results.append((i, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def find_most_similar(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict]:
        """Find most similar documents to query.

        Returns list of {index, document, score}.
        """
        ranked = self.batch_similarity(query, documents)
        results = []
        for idx, score in ranked[:top_k]:
            if score >= min_score:
                results.append({
                    "index": idx,
                    "document": documents[idx][:200],
                    "score": round(score, 4),
                })
        return results

    def update_idf(self, documents: list[str]) -> None:
        """Update IDF cache from a corpus of documents."""
        self._doc_count = len(documents)
        doc_freq: Counter = Counter()

        for doc in documents:
            tokens = set(self._tokenize(doc))
            for token in tokens:
                doc_freq[token] += 1

        for term, freq in doc_freq.items():
            self._idf_cache[term] = freq / self._doc_count if self._doc_count > 0 else 0
