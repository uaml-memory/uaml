# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Structured Logs — queryable log storage in SQLite.

Provides structured logging with severity levels, categories,
and full-text search. Separate from audit_log (which tracks
data operations); this is for operational/application logging.

Usage:
    from uaml.audit.logs import LogStore

    logs = LogStore(store)
    logs.log("info", "system", "Service started")
    logs.log("error", "sync", "Neo4j connection failed", details={"url": "bolt://..."})

    recent = logs.query(severity="error", limit=10)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


class LogStore:
    """Structured log storage backed by SQLite."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.store.conn.execute("""
            CREATE TABLE IF NOT EXISTS app_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                category TEXT NOT NULL DEFAULT 'general',
                message TEXT NOT NULL,
                details TEXT DEFAULT '',
                agent_id TEXT DEFAULT '',
                source TEXT DEFAULT ''
            )
        """)
        self.store.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_ts ON app_logs(ts)
        """)
        self.store.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_severity ON app_logs(severity)
        """)
        self.store.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_category ON app_logs(category)
        """)
        self.store.conn.commit()

    def log(
        self,
        severity: str,
        category: str,
        message: str,
        *,
        details: Optional[dict] = None,
        agent_id: Optional[str] = None,
        source: str = "",
    ) -> int:
        """Write a structured log entry.

        Args:
            severity: debug | info | warning | error | critical
            category: Category (system, sync, security, ingest, etc.)
            message: Log message
            details: Optional dict with extra context
            agent_id: Agent that generated the log
            source: Source module/function

        Returns:
            Log entry ID
        """
        now = datetime.now(timezone.utc).isoformat()
        details_str = json.dumps(details, ensure_ascii=False) if details else ""

        cursor = self.store.conn.execute(
            """INSERT INTO app_logs (ts, severity, category, message, details, agent_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, severity, category, message, details_str,
             agent_id or self.store.agent_id, source),
        )
        self.store.conn.commit()
        return cursor.lastrowid

    def query(
        self,
        *,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        since: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query log entries with filters."""
        where = []
        params: list = []

        if severity:
            where.append("severity = ?")
            params.append(severity)
        if category:
            where.append("category = ?")
            params.append(category)
        if since:
            where.append("ts >= ?")
            params.append(since)
        if search:
            where.append("message LIKE ?")
            params.append(f"%{search}%")

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)

        rows = self.store.conn.execute(
            f"SELECT * FROM app_logs {clause} ORDER BY ts DESC LIMIT ?",
            params,
        ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            if d.get("details"):
                try:
                    d["details"] = json.loads(d["details"])
                except json.JSONDecodeError:
                    pass
            results.append(d)

        return results

    def stats(self) -> dict:
        """Get log statistics."""
        total = self.store.conn.execute("SELECT COUNT(*) FROM app_logs").fetchone()[0]

        by_severity = {}
        for row in self.store.conn.execute(
            "SELECT severity, COUNT(*) as cnt FROM app_logs GROUP BY severity"
        ).fetchall():
            by_severity[row["severity"]] = row["cnt"]

        by_category = {}
        for row in self.store.conn.execute(
            "SELECT category, COUNT(*) as cnt FROM app_logs GROUP BY category ORDER BY cnt DESC LIMIT 10"
        ).fetchall():
            by_category[row["category"]] = row["cnt"]

        return {
            "total": total,
            "by_severity": by_severity,
            "by_category": by_category,
        }

    def purge(self, *, older_than_days: int = 30) -> int:
        """Purge old log entries."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()

        cursor = self.store.conn.execute(
            "DELETE FROM app_logs WHERE ts < ?", (cutoff,)
        )
        self.store.conn.commit()
        return cursor.rowcount

    def detect_incidents(self, *, window_minutes: int = 60, error_threshold: int = 3) -> list[dict]:
        """Detect potential incidents from log patterns.

        Looks for error clusters that may indicate systemic issues.
        Returns incident candidates for review/escalation.

        Args:
            window_minutes: Time window to analyze
            error_threshold: Minimum errors to trigger incident detection
        """
        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()

        # Find error clusters by category
        clusters = self.store.conn.execute(
            """SELECT category, COUNT(*) as cnt,
                      MIN(ts) as first_seen, MAX(ts) as last_seen,
                      GROUP_CONCAT(message, ' | ') as messages
            FROM app_logs
            WHERE severity IN ('error', 'critical') AND ts >= ?
            GROUP BY category
            HAVING cnt >= ?
            ORDER BY cnt DESC""",
            (since, error_threshold),
        ).fetchall()

        incidents = []
        for row in clusters:
            d = dict(row)
            # Truncate messages
            msgs = d.get("messages", "")
            if len(msgs) > 500:
                msgs = msgs[:500] + "..."
            incidents.append({
                "category": d["category"],
                "error_count": d["cnt"],
                "first_seen": d["first_seen"],
                "last_seen": d["last_seen"],
                "sample_messages": msgs,
                "suggested_severity": "critical" if d["cnt"] >= error_threshold * 3 else "error",
                "suggested_title": f"Error cluster in {d['category']} ({d['cnt']} errors in {window_minutes}min)",
            })

        return incidents

    def escalate_to_incident(self, category: str, *, window_minutes: int = 60) -> Optional[int]:
        """Escalate a log error cluster to the incident pipeline.

        Returns incident ID if created, None if no pipeline available.
        """
        try:
            from uaml.reasoning.incidents import IncidentPipeline
            pipeline = IncidentPipeline(self.store)
        except ImportError:
            return None

        from datetime import timedelta
        since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()

        errors = self.store.conn.execute(
            """SELECT COUNT(*) as cnt, GROUP_CONCAT(message, ' | ') as msgs
            FROM app_logs
            WHERE category = ? AND severity IN ('error', 'critical') AND ts >= ?""",
            (category, since),
        ).fetchone()

        if not errors or errors["cnt"] == 0:
            return None

        msgs = errors["msgs"] or ""
        if len(msgs) > 300:
            msgs = msgs[:300] + "..."

        incident = pipeline.log_incident(
            title=f"Log error cluster: {category}",
            description=f"{errors['cnt']} errors in {window_minutes}min: {msgs}",
            severity="error" if errors["cnt"] < 10 else "critical",
            category=category,
        )

        return incident.id
