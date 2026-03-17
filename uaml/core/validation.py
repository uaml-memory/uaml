# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Validation — verify entry quality and consistency.

Validates content quality, metadata completeness, schema compliance,
and cross-reference integrity.

Usage:
    from uaml.core.validation import KnowledgeValidator

    validator = KnowledgeValidator(store)
    issues = validator.validate_entry(entry_id=1)
    report = validator.full_validation()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class ValidationIssue:
    """A validation issue found in an entry."""
    entry_id: int
    severity: str  # error, warning, info
    category: str  # content, metadata, reference, schema
    message: str


class KnowledgeValidator:
    """Validate knowledge entries for quality and consistency."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._min_content_length = 10
        self._max_content_length = 50000

    def validate_entry(self, entry_id: int) -> list[ValidationIssue]:
        """Validate a single entry."""
        issues = []

        row = self.store._conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()

        if not row:
            return [ValidationIssue(entry_id, "error", "schema", "Entry not found")]

        entry = dict(row)

        # Content checks
        content = entry.get("content", "")
        if not content:
            issues.append(ValidationIssue(entry_id, "error", "content", "Empty content"))
        elif len(content) < self._min_content_length:
            issues.append(ValidationIssue(entry_id, "warning", "content",
                f"Content too short ({len(content)} chars, min {self._min_content_length})"))
        elif len(content) > self._max_content_length:
            issues.append(ValidationIssue(entry_id, "warning", "content",
                f"Content too long ({len(content)} chars, max {self._max_content_length})"))

        # Metadata checks
        if not entry.get("topic"):
            issues.append(ValidationIssue(entry_id, "warning", "metadata", "Missing topic"))

        confidence = entry.get("confidence", 0)
        if confidence < 0 or confidence > 1:
            issues.append(ValidationIssue(entry_id, "error", "metadata",
                f"Invalid confidence: {confidence} (must be 0-1)"))

        if not entry.get("agent_id"):
            issues.append(ValidationIssue(entry_id, "warning", "metadata", "Missing agent_id"))

        # Data layer check
        valid_layers = {"identity", "knowledge", "team", "operational", "project", "archive"}
        layer = entry.get("data_layer", "")
        if layer and layer not in valid_layers:
            issues.append(ValidationIssue(entry_id, "warning", "schema",
                f"Unknown data_layer: {layer}"))

        # Temporal validity
        valid_from = entry.get("valid_from")
        valid_until = entry.get("valid_until")
        if valid_from and valid_until and valid_from > valid_until:
            issues.append(ValidationIssue(entry_id, "error", "metadata",
                "valid_from is after valid_until"))

        # Source checks
        if not entry.get("source_type") and not entry.get("source_ref"):
            issues.append(ValidationIssue(entry_id, "info", "metadata",
                "No source information"))

        return issues

    def full_validation(self, *, limit: int = 10000) -> dict:
        """Validate all entries and return summary."""
        rows = self.store._conn.execute(
            "SELECT id FROM knowledge LIMIT ?", (limit,)
        ).fetchall()

        all_issues = []
        clean = 0
        for row in rows:
            issues = self.validate_entry(row["id"])
            if issues:
                all_issues.extend(issues)
            else:
                clean += 1

        errors = [i for i in all_issues if i.severity == "error"]
        warnings = [i for i in all_issues if i.severity == "warning"]
        infos = [i for i in all_issues if i.severity == "info"]

        return {
            "total_entries": len(rows),
            "clean_entries": clean,
            "total_issues": len(all_issues),
            "errors": len(errors),
            "warnings": len(warnings),
            "info": len(infos),
            "pass_rate": round(clean / len(rows), 4) if rows else 1.0,
            "top_issues": self._top_issues(all_issues),
        }

    def _top_issues(self, issues: list[ValidationIssue]) -> list[dict]:
        """Get most common issue types."""
        from collections import Counter
        counts = Counter(i.message for i in issues)
        return [
            {"message": msg, "count": cnt}
            for msg, cnt in counts.most_common(10)
        ]

    def validate_batch(self, entry_ids: list[int]) -> dict[int, list[ValidationIssue]]:
        """Validate multiple entries."""
        return {eid: self.validate_entry(eid) for eid in entry_ids}
