# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Export Formats — export knowledge in multiple formats.

Supports JSON, CSV, Markdown, and JSONL export with filtering.

Usage:
    from uaml.io.formats import ExportFormatter

    formatter = ExportFormatter(store)
    json_data = formatter.to_json(topic="python")
    csv_data = formatter.to_csv()
    md_data = formatter.to_markdown()
"""

from __future__ import annotations

import csv
import json
import io
from typing import Optional

from uaml.core.store import MemoryStore


class ExportFormatter:
    """Export knowledge entries in various formats."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def _query_entries(
        self,
        *,
        topic: Optional[str] = None,
        data_layer: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 10000,
    ) -> list[dict]:
        """Query entries with filters."""
        where = ["confidence >= ?"]
        params: list = [min_confidence]

        if topic:
            where.append("topic LIKE ?")
            params.append(f"%{topic}%")
        if data_layer:
            where.append("data_layer = ?")
            params.append(data_layer)

        rows = self.store._conn.execute(
            f"""
            SELECT id, topic, summary, content, confidence, data_layer,
                   tags, source_ref, source_type, source_origin,
                   created_at, updated_at, valid_from, valid_until
            FROM knowledge
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

        return [dict(r) for r in rows]

    def to_json(self, *, pretty: bool = True, **filters) -> str:
        """Export as JSON."""
        entries = self._query_entries(**filters)
        return json.dumps(
            {"entries": entries, "count": len(entries)},
            indent=2 if pretty else None,
            default=str,
        )

    def to_jsonl(self, **filters) -> str:
        """Export as JSON Lines (one entry per line)."""
        entries = self._query_entries(**filters)
        lines = [json.dumps(e, default=str) for e in entries]
        return "\n".join(lines)

    def to_csv(self, **filters) -> str:
        """Export as CSV."""
        entries = self._query_entries(**filters)
        if not entries:
            return ""

        output = io.StringIO()
        fieldnames = list(entries[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)

        return output.getvalue()

    def to_markdown(self, *, include_content: bool = True, **filters) -> str:
        """Export as Markdown document."""
        entries = self._query_entries(**filters)
        lines = [
            "# UAML Knowledge Export",
            "",
            f"**Entries:** {len(entries)}",
            "",
            "---",
            "",
        ]

        for entry in entries:
            topic = entry.get("topic") or "Untitled"
            summary = entry.get("summary") or ""
            content = entry.get("content") or ""
            confidence = entry.get("confidence", 0)
            tags = entry.get("tags") or ""
            created = entry.get("created_at") or ""

            lines.append(f"## {topic}")
            if summary:
                lines.append(f"*{summary}*")
            lines.append("")
            lines.append(f"- **Confidence:** {confidence}")
            if tags:
                lines.append(f"- **Tags:** {tags}")
            lines.append(f"- **Created:** {created}")
            lines.append(f"- **Layer:** {entry.get('data_layer', '')}")
            lines.append("")

            if include_content and content:
                lines.append(content[:1000])
                if len(content) > 1000:
                    lines.append(f"\n*... ({len(content)} chars total)*")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def to_dict_list(self, **filters) -> list[dict]:
        """Export as list of dicts (for programmatic use)."""
        return self._query_entries(**filters)

    def summary_report(self, **filters) -> str:
        """Generate a summary report of knowledge base contents."""
        entries = self._query_entries(**filters)
        if not entries:
            return "No entries found."

        # Stats
        topics = {}
        layers = {}
        total_conf = 0

        for e in entries:
            t = e.get("topic") or "untagged"
            topics[t] = topics.get(t, 0) + 1
            l = e.get("data_layer") or "unknown"
            layers[l] = layers.get(l, 0) + 1
            total_conf += e.get("confidence", 0)

        avg_conf = total_conf / len(entries) if entries else 0

        lines = [
            "# Knowledge Base Summary",
            "",
            f"**Total entries:** {len(entries)}",
            f"**Average confidence:** {avg_conf:.2f}",
            "",
            "## By Topic",
            "",
        ]
        for topic, count in sorted(topics.items(), key=lambda x: -x[1])[:20]:
            lines.append(f"- {topic}: {count}")

        lines.extend(["", "## By Layer", ""])
        for layer, count in sorted(layers.items(), key=lambda x: -x[1]):
            lines.append(f"- {layer}: {count}")

        return "\n".join(lines)
