# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""WebIngestor — ingest web pages into UAML knowledge.

Fetches a URL, extracts readable content (strips HTML),
and stores as knowledge with proper provenance.

Requires no external dependencies — uses stdlib urllib + basic HTML stripping.
For production use, pair with a proper HTML-to-markdown converter.
"""

from __future__ import annotations

import html
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from uaml.ingest.base import BaseIngestor, IngestStats


class WebIngestor(BaseIngestor):
    """Ingest web pages into UAML knowledge store.

    Fetches URL content, strips HTML tags, and stores as knowledge.
    Can also process pre-downloaded HTML/text files.

    Features:
    - URL fetching with timeout
    - Basic HTML tag stripping
    - Title extraction
    - Chunking for long pages
    """

    source_type = "web_page"
    source_origin = "external"  # Web pages are external sources
    data_layer = "knowledge"  # Web content → knowledge layer

    def __init__(self, store, *, max_content_length: int = 50_000, chunk_size: int = 4000, **kwargs):
        super().__init__(store, **kwargs)
        self.max_content_length = max_content_length
        self.chunk_size = chunk_size

    def ingest(
        self,
        source: str | Path,
        *,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        chunk: bool = True,
        timeout: int = 15,
    ) -> IngestStats:
        """Ingest from a URL or local HTML file.

        Args:
            source: URL (http/https) or path to local HTML file
            title: Override page title
            topic: Override topic
            chunk: Split long content into chunks
            timeout: HTTP request timeout in seconds
        """
        source_str = str(source)
        stats = IngestStats(source=source_str, source_type="web_page")

        if source_str.startswith(("http://", "https://")):
            text, extracted_title = self._fetch_url(source_str, timeout, stats)
        else:
            text, extracted_title = self._read_file(Path(source_str), stats)

        if not text:
            return stats

        page_title = title or extracted_title or source_str
        page_topic = topic or self.default_topic

        # Truncate if too long
        if len(text) > self.max_content_length:
            text = text[: self.max_content_length]

        if chunk and len(text) > self.chunk_size:
            self._ingest_chunked(text, page_title, page_topic, source_str, stats)
        else:
            self._learn_entry(
                text,
                stats,
                topic=page_topic,
                summary=page_title,
                source_ref=source_str,
            )

        stats.details["title"] = page_title
        return stats

    def _fetch_url(self, url: str, timeout: int, stats: IngestStats) -> tuple[str, str]:
        """Fetch URL and extract text content."""
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "UAML-Ingestor/0.2"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                raw = resp.read().decode(charset, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            stats.errors += 1
            stats.details["fetch_error"] = str(e)
            return "", ""

        title = self._extract_title(raw)
        text = self._html_to_text(raw)
        return text, title

    def _read_file(self, path: Path, stats: IngestStats) -> tuple[str, str]:
        """Read a local HTML or text file."""
        if not path.exists():
            stats.errors += 1
            stats.details["error"] = f"File not found: {path}"
            return "", ""

        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            stats.errors += 1
            return "", ""

        if path.suffix in (".html", ".htm"):
            title = self._extract_title(raw)
            text = self._html_to_text(raw)
        else:
            title = path.name
            text = raw

        return text, title

    def _html_to_text(self, raw_html: str) -> str:
        """Basic HTML to text conversion (no external deps)."""
        # Remove script and style blocks
        text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode entities
        text = html.unescape(text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_title(self, raw_html: str) -> str:
        """Extract <title> from HTML."""
        match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        if match:
            return html.unescape(match.group(1)).strip()
        return ""

    def _ingest_chunked(
        self, text: str, title: str, topic: str, source_ref: str, stats: IngestStats
    ) -> None:
        """Split text into chunks and ingest each."""
        # Split on paragraph boundaries when possible
        paragraphs = re.split(r"\n\n+|\. (?=[A-Z])", text)
        current_chunk = ""
        chunk_num = 0

        for para in paragraphs:
            if len(current_chunk) + len(para) > self.chunk_size and current_chunk:
                chunk_num += 1
                self._learn_entry(
                    current_chunk.strip(),
                    stats,
                    topic=topic,
                    summary=f"{title} (chunk {chunk_num})",
                    source_ref=f"{source_ref}#chunk-{chunk_num}",
                )
                current_chunk = para
            else:
                current_chunk += " " + para

        # Last chunk
        if current_chunk.strip():
            chunk_num += 1
            self._learn_entry(
                current_chunk.strip(),
                stats,
                topic=topic,
                summary=f"{title} (chunk {chunk_num})" if chunk_num > 1 else title,
                source_ref=f"{source_ref}#chunk-{chunk_num}" if chunk_num > 1 else source_ref,
            )

    def can_handle(self, source: str | Path) -> bool:
        source_str = str(source)
        if source_str.startswith(("http://", "https://")):
            return True
        path = Path(source_str)
        return path.suffix in (".html", ".htm", ".txt") and path.exists()
