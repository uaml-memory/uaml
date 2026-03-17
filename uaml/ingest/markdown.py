# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""MarkdownIngestor — ingest markdown files into UAML knowledge.

Supports two modes:
1. **Whole file** — entire file as one knowledge entry
2. **Section split** — split by headings (## or ###) into separate entries

Extracts metadata from YAML frontmatter if present.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from uaml.ingest.base import BaseIngestor, IngestStats


class MarkdownIngestor(BaseIngestor):
    """Ingest markdown files into UAML knowledge store.

    Can process individual files or entire directories.
    Supports splitting by sections for granular knowledge entries.
    """

    source_type = "document"
    source_origin = "external"  # Documents are external sources
    data_layer = "knowledge"  # Docs → knowledge layer by default

    def ingest(
        self,
        source: str | Path,
        *,
        split_sections: bool = True,
        heading_level: int = 2,
        recursive: bool = True,
    ) -> IngestStats:
        """Ingest markdown file(s).

        Args:
            source: Path to .md file or directory
            split_sections: Split by headings into separate entries
            heading_level: Heading level to split on (2 = ##, 3 = ###)
            recursive: If source is a directory, recurse into subdirs
        """
        path = Path(source)
        stats = IngestStats(source=str(path), source_type="document")

        if path.is_dir():
            pattern = "**/*.md" if recursive else "*.md"
            for md_file in sorted(path.glob(pattern)):
                self._ingest_file(md_file, stats, split_sections, heading_level)
        elif path.is_file():
            self._ingest_file(path, stats, split_sections, heading_level)
        else:
            stats.errors += 1
            stats.details["error"] = f"Not found: {path}"

        return stats

    def _ingest_file(
        self, path: Path, stats: IngestStats, split_sections: bool, heading_level: int
    ) -> None:
        """Ingest a single markdown file."""
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            stats.errors += 1
            return

        # Strip frontmatter
        text, frontmatter = self._strip_frontmatter(text)

        # Extract metadata from frontmatter
        topic = frontmatter.get("topic", "") or self.default_topic
        tags = frontmatter.get("tags", "") or self.default_tags
        project = frontmatter.get("project") or self.default_project

        source_ref = str(path)

        if split_sections:
            sections = self._split_by_heading(text, heading_level)
            if not sections:
                # No headings found — treat as whole file
                self._learn_entry(
                    text.strip(),
                    stats,
                    topic=topic,
                    summary=path.name,
                    source_ref=source_ref,
                    tags=tags,
                    project=project,
                )
            else:
                for heading, content in sections:
                    full_content = f"# {heading}\n\n{content}".strip()
                    self._learn_entry(
                        full_content,
                        stats,
                        topic=topic,
                        summary=heading,
                        source_ref=f"{source_ref}#{heading}",
                        tags=tags,
                        project=project,
                    )
        else:
            self._learn_entry(
                text.strip(),
                stats,
                topic=topic,
                summary=path.name,
                source_ref=source_ref,
                tags=tags,
                project=project,
            )

    def _split_by_heading(self, text: str, level: int) -> list[tuple[str, str]]:
        """Split markdown text by heading level.

        Returns list of (heading_text, section_content) tuples.
        """
        pattern = r"^(#{" + str(level) + r"})\s+(.+)$"
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_content: list[str] = []

        for line in text.split("\n"):
            match = re.match(pattern, line)
            if match:
                # Save previous section
                if current_heading:
                    sections.append((current_heading, "\n".join(current_content).strip()))
                current_heading = match.group(2).strip()
                current_content = []
            else:
                current_content.append(line)

        # Save last section
        if current_heading:
            sections.append((current_heading, "\n".join(current_content).strip()))

        return sections

    def _strip_frontmatter(self, text: str) -> tuple[str, dict]:
        """Remove YAML frontmatter from markdown and parse it."""
        if not text.startswith("---"):
            return text, {}

        parts = text.split("---", 2)
        if len(parts) < 3:
            return text, {}

        frontmatter_text = parts[1].strip()
        body = parts[2].strip()

        # Simple YAML parsing (key: value) — no dependency on pyyaml
        metadata: dict = {}
        for line in frontmatter_text.split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                metadata[key.strip()] = value.strip()

        return body, metadata

    def can_handle(self, source: str | Path) -> bool:
        path = Path(source)
        if path.is_dir():
            return any(path.glob("*.md"))
        return path.suffix == ".md" and path.exists()
