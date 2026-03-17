# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""SearchIngestor — ingest web search results into UAML knowledge.

Supports Brave Search API results and generic search result formats.
Stores each result as a knowledge entry with source provenance.

Usage:
    from uaml.ingest.search import SearchIngestor

    ingestor = SearchIngestor(store)
    stats = ingestor.ingest_results(results, query="AI memory systems")

    # Or with Brave API directly (requires BRAVE_API_KEY env var)
    stats = ingestor.search_and_ingest("AI memory systems", count=5)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from uaml.ingest.base import BaseIngestor, IngestStats


class SearchIngestor(BaseIngestor):
    """Ingest web search results as knowledge entries."""

    source_type = "research"
    source_origin = "external"
    data_layer = "knowledge"

    def __init__(self, store, *, api_key: Optional[str] = None, **kwargs):
        super().__init__(store, **kwargs)
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")

    def ingest(self, source: str | Path, **kwargs) -> IngestStats:
        """Ingest from a JSON file containing search results."""
        stats = IngestStats(source=str(source), source_type="search")
        path = Path(source)

        if not path.exists():
            stats.errors += 1
            return stats

        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            stats.errors += 1
            return stats

        results = data.get("results", data.get("web", {}).get("results", []))
        query = data.get("query", "")

        for result in results:
            self._ingest_single_result(result, stats, query)

        return stats

    def ingest_results(
        self,
        results: list[dict],
        *,
        query: str = "",
    ) -> IngestStats:
        """Ingest a list of search result dicts directly.

        Each result should have: title, url, description/snippet.
        """
        stats = IngestStats(source=f"search:{query}", source_type="search")

        for result in results:
            self._ingest_single_result(result, stats, query)

        return stats

    def search_and_ingest(
        self,
        query: str,
        *,
        count: int = 5,
    ) -> IngestStats:
        """Search via Brave API and ingest results.

        Requires BRAVE_API_KEY environment variable or api_key in constructor.
        """
        stats = IngestStats(source=f"brave:{query}", source_type="search")

        if not self.api_key:
            stats.errors += 1
            stats.details["error"] = "No Brave API key (set BRAVE_API_KEY env var)"
            return stats

        try:
            results = self._brave_search(query, count=count)
            for result in results:
                self._ingest_single_result(result, stats, query)
        except Exception as e:
            stats.errors += 1
            stats.details["error"] = str(e)

        return stats

    def _ingest_single_result(
        self, result: dict, stats: IngestStats, query: str
    ) -> None:
        """Ingest a single search result."""
        title = result.get("title", "")
        url = result.get("url", "")
        description = result.get("description", result.get("snippet", ""))

        if not description or len(description.strip()) < self.min_content_length:
            stats.entries_skipped += 1
            return

        content = f"{title}\n{description}"
        if url:
            content += f"\nSource: {url}"

        self._learn_entry(
            content,
            stats,
            summary=title[:100],
            source_ref=url,
            tags=f"search,query:{query[:50]}",
        )

    def _brave_search(self, query: str, count: int = 5) -> list[dict]:
        """Execute Brave Search API query."""
        from urllib.parse import quote_plus

        url = f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={count}"
        req = Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("Accept-Encoding", "gzip")
        req.add_header("X-Subscription-Token", self.api_key)

        try:
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("web", {}).get("results", [])
        except URLError as e:
            raise RuntimeError(f"Brave search failed: {e}")

    def can_handle(self, source: str | Path) -> bool:
        """Check if source looks like a search results file."""
        path = Path(source)
        if not path.exists():
            return False
        if path.suffix == ".json":
            try:
                with open(path) as f:
                    data = json.load(f)
                return "results" in data or "web" in data
            except (json.JSONDecodeError, IOError):
                return False
        return False
