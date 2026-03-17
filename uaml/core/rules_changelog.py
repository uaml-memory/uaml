# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Rules Change Log — audit trail for Focus Engine configuration changes.

Records every change to Focus Engine rules with:
- Who changed it (user)
- When (timestamp)
- What changed (parameter path, old → new value)
- Why (user-provided reason)
- Expected impact (user-provided hypothesis)
- Actual impact (measured after evaluation_days)

Designed for certifiability:
- Immutable log (append-only)
- Every entry is timestamped and attributed
- Supports rollback to any previous state
- Export to JSON/HTML for compliance reporting

© 2026 GLG, a.s. — UAML Focus Engine
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RuleChange:
    """A single rule change record."""
    change_id: str = ""
    timestamp: str = ""
    user: str = ""
    rule_path: str = ""
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    expected_impact: dict = field(default_factory=dict)
    actual_impact: Optional[dict] = None
    evaluation_status: str = "pending"  # pending, evaluated, skipped

    def __post_init__(self):
        if not self.change_id:
            self.change_id = f"RC-{uuid.uuid4().hex[:12]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ImpactMeasurement:
    """Measured impact of a rule change after evaluation period."""
    measurement_period_start: str
    measurement_period_end: str
    avg_tokens_before: float = 0.0
    avg_tokens_after: float = 0.0
    quality_score_before: float = 0.0
    quality_score_after: float = 0.0
    cost_change: str = ""
    verdict: str = ""
    recommendation: str = ""


# ---------------------------------------------------------------------------
# Change Log Store
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rules_changelog (
    change_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user TEXT NOT NULL,
    rule_path TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    reason TEXT DEFAULT '',
    expected_impact TEXT DEFAULT '{}',
    actual_impact TEXT,
    evaluation_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_changelog_timestamp ON rules_changelog(timestamp);
CREATE INDEX IF NOT EXISTS idx_changelog_rule_path ON rules_changelog(rule_path);
CREATE INDEX IF NOT EXISTS idx_changelog_user ON rules_changelog(user);
CREATE INDEX IF NOT EXISTS idx_changelog_status ON rules_changelog(evaluation_status);
"""


class RulesChangeLog:
    """Persistent audit trail for Focus Engine rule changes.

    Backed by SQLite — append-only log with query capabilities.
    """

    def __init__(self, db_path: str | Path = "rules_changelog.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database and schema if needed."""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def log_change(self, change: RuleChange) -> str:
        """Record a rule change.

        Args:
            change: RuleChange with details

        Returns:
            change_id of the recorded change
        """
        if not self._conn:
            self._ensure_db()

        self._conn.execute(
            """INSERT INTO rules_changelog
               (change_id, timestamp, user, rule_path, old_value, new_value,
                reason, expected_impact, actual_impact, evaluation_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                change.change_id,
                change.timestamp,
                change.user,
                change.rule_path,
                json.dumps(change.old_value),
                json.dumps(change.new_value),
                change.reason,
                json.dumps(change.expected_impact),
                json.dumps(change.actual_impact) if change.actual_impact else None,
                change.evaluation_status,
            ),
        )
        self._conn.commit()
        return change.change_id

    def record_actual_impact(
        self,
        change_id: str,
        impact: ImpactMeasurement,
    ) -> None:
        """Record the actual measured impact of a rule change.

        Called after the evaluation period (typically 7 days).
        """
        if not self._conn:
            self._ensure_db()

        self._conn.execute(
            """UPDATE rules_changelog
               SET actual_impact = ?, evaluation_status = 'evaluated'
               WHERE change_id = ?""",
            (json.dumps(asdict(impact)), change_id),
        )
        self._conn.commit()

    def get_change(self, change_id: str) -> Optional[RuleChange]:
        """Get a single change record by ID."""
        if not self._conn:
            self._ensure_db()

        row = self._conn.execute(
            "SELECT * FROM rules_changelog WHERE change_id = ?",
            (change_id,),
        ).fetchone()

        if not row:
            return None
        return self._row_to_change(row)

    def get_history(
        self,
        *,
        rule_path: Optional[str] = None,
        user: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RuleChange]:
        """Get change history with optional filters.

        Args:
            rule_path: Filter by parameter path (e.g. "output_filter.token_budget")
            user: Filter by user
            limit: Max records to return
            offset: Pagination offset

        Returns:
            List of RuleChange records, newest first
        """
        if not self._conn:
            self._ensure_db()

        query = "SELECT * FROM rules_changelog WHERE 1=1"
        params: list[Any] = []

        if rule_path:
            query += " AND rule_path = ?"
            params.append(rule_path)
        if user:
            query += " AND user = ?"
            params.append(user)

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_change(row) for row in rows]

    def get_pending_evaluations(self, older_than_days: int = 7) -> list[RuleChange]:
        """Get changes that need impact evaluation.

        Returns changes with status='pending' older than the specified days.
        """
        if not self._conn:
            self._ensure_db()

        rows = self._conn.execute(
            """SELECT * FROM rules_changelog
               WHERE evaluation_status = 'pending'
               AND julianday('now') - julianday(timestamp) >= ?
               ORDER BY timestamp ASC""",
            (older_than_days,),
        ).fetchall()

        return [self._row_to_change(row) for row in rows]

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics for the change log."""
        if not self._conn:
            self._ensure_db()

        total = self._conn.execute(
            "SELECT COUNT(*) FROM rules_changelog"
        ).fetchone()[0]

        pending = self._conn.execute(
            "SELECT COUNT(*) FROM rules_changelog WHERE evaluation_status = 'pending'"
        ).fetchone()[0]

        evaluated = self._conn.execute(
            "SELECT COUNT(*) FROM rules_changelog WHERE evaluation_status = 'evaluated'"
        ).fetchone()[0]

        top_rules = self._conn.execute(
            """SELECT rule_path, COUNT(*) as cnt
               FROM rules_changelog
               GROUP BY rule_path
               ORDER BY cnt DESC
               LIMIT 5"""
        ).fetchall()

        return {
            "total_changes": total,
            "pending_evaluation": pending,
            "evaluated": evaluated,
            "most_changed_rules": [
                {"rule": row["rule_path"], "count": row["cnt"]}
                for row in top_rules
            ],
        }

    def export_json(self, limit: int = 1000) -> str:
        """Export change log as JSON for compliance reporting."""
        changes = self.get_history(limit=limit)
        return json.dumps(
            [self._change_to_dict(c) for c in changes],
            indent=2,
            ensure_ascii=False,
        )

    def _row_to_change(self, row: sqlite3.Row) -> RuleChange:
        """Convert a database row to RuleChange."""
        return RuleChange(
            change_id=row["change_id"],
            timestamp=row["timestamp"],
            user=row["user"],
            rule_path=row["rule_path"],
            old_value=json.loads(row["old_value"]) if row["old_value"] else None,
            new_value=json.loads(row["new_value"]) if row["new_value"] else None,
            reason=row["reason"] or "",
            expected_impact=json.loads(row["expected_impact"]) if row["expected_impact"] else {},
            actual_impact=json.loads(row["actual_impact"]) if row["actual_impact"] else None,
            evaluation_status=row["evaluation_status"] or "pending",
        )

    @staticmethod
    def _change_to_dict(change: RuleChange) -> dict:
        """Convert RuleChange to serializable dict."""
        return {
            "change_id": change.change_id,
            "timestamp": change.timestamp,
            "user": change.user,
            "rule_path": change.rule_path,
            "old_value": change.old_value,
            "new_value": change.new_value,
            "reason": change.reason,
            "expected_impact": change.expected_impact,
            "actual_impact": change.actual_impact,
            "evaluation_status": change.evaluation_status,
        }
