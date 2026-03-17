# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Real-Time Audit Stream Processor.

Watches system logs in real-time (journalctl --follow, dpkg.log, auth.log)
and processes events into incidents with lifecycle management.

Incident types:
  - Spike (short): single event or quick burst → immediate close
  - Sustained (long): ongoing activity (apt install, deployment) →
    START → segments every ~60s → CLOSE

Usage:
    # As a service (real-time streaming):
    processor = StreamProcessor("/path/to/audit_log.db", agent_id="Metod")
    processor.run()  # blocks, follows logs

    # Programmatic:
    processor = StreamProcessor(db_path, agent_id="Metod")
    processor.process_event(source="systemd", raw_line="...", timestamp="...")
"""

from __future__ import annotations

import json
import logging
import os
import re
import select
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger("uaml.audit.stream")


# ─── Schema Migration ────────────────────────────────

STREAM_SCHEMA = """
-- Incident lifecycle table (extends existing incidents)
CREATE TABLE IF NOT EXISTS incident_lifecycle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL REFERENCES incidents(id),
    lifecycle_type TEXT NOT NULL DEFAULT 'spike',  -- 'spike' or 'sustained'
    status TEXT NOT NULL DEFAULT 'open',            -- 'open', 'in_progress', 'closed'
    started_at TEXT NOT NULL,
    last_segment_at TEXT,
    closed_at TEXT,
    segment_count INTEGER DEFAULT 0,
    duration_seconds REAL,
    outcome TEXT,                                   -- 'success', 'failure', 'timeout', 'unknown'
    pattern_name TEXT,                              -- which detection pattern matched
    neo4j_synced INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_incident ON incident_lifecycle(incident_id);
CREATE INDEX IF NOT EXISTS idx_lifecycle_status ON incident_lifecycle(status);
CREATE INDEX IF NOT EXISTS idx_lifecycle_pattern ON incident_lifecycle(pattern_name);

-- Incident segments (for sustained incidents)
CREATE TABLE IF NOT EXISTS incident_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lifecycle_id INTEGER NOT NULL REFERENCES incident_lifecycle(id),
    segment_num INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    summary TEXT,
    event_ids TEXT,            -- JSON array of audit_event IDs in this segment
    progress TEXT,             -- optional progress info (e.g., "Installing package 3/10")
    neo4j_synced INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_segment_lifecycle ON incident_segments(lifecycle_id);
"""


# ─── Detection Patterns ──────────────────────────────

class IncidentType(Enum):
    SPIKE = "spike"
    SUSTAINED = "sustained"


@dataclass
class DetectionPattern:
    """Pattern for detecting and classifying log events."""
    name: str
    source: str                    # ssh, systemd, dpkg, ufw, openclaw
    start_pattern: re.Pattern      # regex to detect start
    end_pattern: Optional[re.Pattern] = None  # regex to detect end (None = spike)
    incident_type: IncidentType = IncidentType.SPIKE
    severity: str = "info"
    category: str = "service"
    segment_interval: int = 60     # seconds between segments for sustained
    max_duration: int = 3600       # auto-close after this many seconds
    extract_metadata: Optional[callable] = None  # function to extract metadata from match


# Pre-configured detection patterns
DETECTION_PATTERNS = [
    # ─── Spike patterns (immediate close) ───
    DetectionPattern(
        name="ssh_login_failed",
        source="ssh",
        start_pattern=re.compile(r"Failed password|Invalid user", re.I),
        severity="warning",
        category="auth",
    ),
    DetectionPattern(
        name="ssh_login_success",
        source="ssh",
        start_pattern=re.compile(r"Accepted (?:password|publickey)", re.I),
        severity="info",
        category="auth",
    ),
    DetectionPattern(
        name="ufw_block",
        source="ufw",
        start_pattern=re.compile(r"\[UFW BLOCK\]", re.I),
        severity="warning",
        category="network",
    ),
    DetectionPattern(
        name="service_failed",
        source="systemd",
        start_pattern=re.compile(r"Failed to start|entered failed state|Main process exited, code=exited, status=1", re.I),
        severity="critical",
        category="service",
    ),
    DetectionPattern(
        name="oom_kill",
        source="kernel",
        start_pattern=re.compile(r"Out of memory|oom-kill|oom_reaper", re.I),
        severity="critical",
        category="system",
    ),

    # ─── Sustained patterns (start → segments → end) ───
    DetectionPattern(
        name="apt_install",
        source="dpkg",
        start_pattern=re.compile(r"install\s+\S+|upgrade\s+\S+", re.I),
        end_pattern=re.compile(r"trigproc\s+|status installed|configure\s+\S+\s+\S+\s+\S+", re.I),
        incident_type=IncidentType.SUSTAINED,
        severity="info",
        category="modification",
        segment_interval=60,
        max_duration=1800,
    ),
    DetectionPattern(
        name="service_restart",
        source="systemd",
        start_pattern=re.compile(r"Stopping\s+|Deactivating\s+", re.I),
        end_pattern=re.compile(r"Started\s+|Finished\s+|Reached target", re.I),
        incident_type=IncidentType.SUSTAINED,
        severity="info",
        category="service",
        segment_interval=30,
        max_duration=300,
    ),
    DetectionPattern(
        name="neo4j_sync",
        source="openclaw",
        start_pattern=re.compile(r"Neo4j Sync —|sync.*started", re.I),
        end_pattern=re.compile(r"Sync complete|sync.*finished|sync.*error", re.I),
        incident_type=IncidentType.SUSTAINED,
        severity="info",
        category="service",
        segment_interval=60,
        max_duration=600,
    ),
    DetectionPattern(
        name="backup_run",
        source="openclaw",
        start_pattern=re.compile(r"backup.*started|Creating backup", re.I),
        end_pattern=re.compile(r"backup.*complete|backup.*finished|backup.*failed", re.I),
        incident_type=IncidentType.SUSTAINED,
        severity="info",
        category="service",
        segment_interval=60,
        max_duration=1800,
    ),
]


@dataclass
class OpenIncident:
    """Tracks an open sustained incident in memory."""
    lifecycle_id: int
    incident_id: int
    pattern: DetectionPattern
    started_at: datetime
    last_segment_at: datetime
    segment_count: int = 0
    event_ids: list = field(default_factory=list)
    raw_lines: list = field(default_factory=list)


@dataclass
class AlertConfig:
    """Configuration for real-time alerting."""
    enabled: bool = True
    # Severity levels that trigger immediate alert
    immediate_severities: list = field(default_factory=lambda: ["critical", "alert"])
    # Warning threshold: N events in M seconds → alert
    warning_threshold: int = 3
    warning_window_seconds: int = 60
    # Callback for sending alerts (receives AlertEvent)
    callback: Optional[callable] = None
    # Discord webhook URL (alternative to callback)
    discord_webhook: Optional[str] = None
    # File to write alerts to (for OpenClaw heartbeat pickup)
    alert_file: Optional[str] = None


@dataclass
class AlertEvent:
    """An alert to be sent to the active thread/channel."""
    severity: str
    title: str
    summary: str
    incident_id: int
    pattern_name: str
    source: str
    timestamp: str
    recommended_action: str = ""
    raw_lines: list = field(default_factory=list)


class StreamProcessor:
    """Real-time log stream processor with incident lifecycle management."""

    def __init__(
        self,
        db_path: str,
        agent_id: str = "unknown",
        hostname: str = "",
        neo4j_uri: str = None,
        neo4j_user: str = None,
        neo4j_password: str = None,
        alert_config: AlertConfig = None,
    ):
        self.db_path = Path(db_path)
        self.agent_id = agent_id
        self.hostname = hostname or os.uname().nodename
        self.neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
        self.neo4j_user = neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
        self.neo4j_password = neo4j_password or os.environ.get("NEO4J_PASSWORD", "")
        self._conn: Optional[sqlite3.Connection] = None
        self._open_incidents: dict[str, OpenIncident] = {}  # pattern_name → OpenIncident
        self._neo4j_driver = None
        self._stop_event = threading.Event()
        self._patterns = list(DETECTION_PATTERNS)
        self._alert_config = alert_config or AlertConfig()
        self._warning_counter: dict[str, list[float]] = {}  # pattern → [timestamps]

    def init_db(self):
        """Initialize database with stream schema."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")

        # Apply base schema if needed
        schema_path = Path(__file__).parent / "schema.sql"
        if schema_path.exists():
            self._conn.executescript(schema_path.read_text())

        # Apply stream-specific schema
        self._conn.executescript(STREAM_SCHEMA)
        self._conn.commit()

        # Recover open incidents from DB (e.g., after restart)
        self._recover_open_incidents()

    def close(self):
        """Close database and Neo4j connections."""
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._neo4j_driver:
            self._neo4j_driver.close()
            self._neo4j_driver = None

    def _recover_open_incidents(self):
        """Recover open incidents from DB after restart."""
        rows = self._conn.execute(
            """SELECT il.*, i.title FROM incident_lifecycle il
               JOIN incidents i ON il.incident_id = i.id
               WHERE il.status IN ('open', 'in_progress')"""
        ).fetchall()

        for row in rows:
            pattern = next((p for p in self._patterns if p.name == row["pattern_name"]), None)
            if not pattern:
                # Auto-close orphaned incidents
                self._close_lifecycle(row["id"], outcome="timeout")
                continue

            started = datetime.fromisoformat(row["started_at"])
            last_seg = datetime.fromisoformat(row["last_segment_at"] or row["started_at"])

            # Always recover open incidents — timeout will be checked on next
            # event via _maybe_create_segment using the event's own timestamp.
            # This avoids false timeouts when replaying historical events.
            self._open_incidents[pattern.name] = OpenIncident(
                lifecycle_id=row["id"],
                incident_id=row["incident_id"],
                pattern=pattern,
                started_at=started,
                last_segment_at=last_seg,
                segment_count=row["segment_count"],
            )
            logger.info(f"Recovered open incident: {pattern.name}")

    # ─── Event Processing ─────────────────────────────────

    def process_event(self, source: str, raw_line: str, timestamp: str = None) -> Optional[int]:
        """Process a single log event. Returns event_id if stored."""
        if not self._conn:
            self.init_db()

        if not raw_line or not raw_line.strip():
            return None

        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")

        # Store raw event
        event_id = self._store_event(source, raw_line, ts)

        # Match against patterns
        for pattern in self._patterns:
            if pattern.source != source:
                continue

            # Check if this closes a sustained incident
            if pattern.name in self._open_incidents:
                open_inc = self._open_incidents[pattern.name]
                open_inc.event_ids.append(event_id)
                open_inc.raw_lines.append(raw_line[:500])

                if pattern.end_pattern and pattern.end_pattern.search(raw_line):
                    self._close_incident(pattern.name, outcome="success")
                    continue
                else:
                    # Check if we need a segment update
                    self._maybe_create_segment(pattern.name, event_ts=ts)
                    continue

            # Check start pattern
            if pattern.start_pattern.search(raw_line):
                if pattern.incident_type == IncidentType.SPIKE:
                    self._create_spike_incident(pattern, raw_line, ts, event_id)
                else:
                    self._open_sustained_incident(pattern, raw_line, ts, event_id)

        return event_id

    def _store_event(self, source: str, raw_line: str, timestamp: str) -> int:
        """Store a raw audit event."""
        import hashlib
        content_hash = hashlib.sha256(f"{timestamp}|{source}|{raw_line[:200]}".encode()).hexdigest()

        # Extract basic metadata
        severity = "info"
        event_type = f"{source}_event"
        summary = raw_line[:200]

        # Smart severity detection
        lower = raw_line.lower()
        if any(kw in lower for kw in ["error", "failed", "critical", "panic", "fatal"]):
            severity = "critical"
        elif any(kw in lower for kw in ["warning", "warn", "block"]):
            severity = "warning"

        cur = self._conn.execute(
            """INSERT INTO audit_events
               (timestamp, source, severity, category, agent_id, hostname,
                event_type, summary, raw_line, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, source, severity, "stream", self.agent_id, self.hostname,
             event_type, summary, raw_line[:2000], content_hash),
        )
        self._conn.commit()
        return cur.lastrowid

    # ─── Spike Incidents ──────────────────────────────────

    def _create_spike_incident(self, pattern: DetectionPattern, raw_line: str, timestamp: str, event_id: int):
        """Create a spike incident (immediately closed)."""
        # Create incident
        incident_id = self._create_incident(
            incident_type=pattern.name,
            severity=pattern.severity,
            title=f"[{pattern.name}] {raw_line[:150]}",
            log_refs=[event_id],
        )

        # Create lifecycle (already closed)
        self._conn.execute(
            """INSERT INTO incident_lifecycle
               (incident_id, lifecycle_type, status, started_at, closed_at,
                segment_count, duration_seconds, outcome, pattern_name)
               VALUES (?, 'spike', 'closed', ?, ?, 0, 0, 'complete', ?)""",
            (incident_id, timestamp, timestamp, pattern.name),
        )

        # Mark incident resolved
        self._conn.execute(
            "UPDATE incidents SET resolved = 1, resolved_at = ? WHERE id = ?",
            (timestamp, incident_id),
        )
        self._conn.commit()

        # Sync to Neo4j
        self._sync_incident_to_neo4j(incident_id, pattern.name, "spike", timestamp, timestamp)

        # Real-time alert
        self._trigger_alert(pattern, incident_id, raw_line, timestamp)

        logger.debug(f"Spike incident: {pattern.name} — {raw_line[:80]}")

    # ─── Sustained Incidents ──────────────────────────────

    def _open_sustained_incident(self, pattern: DetectionPattern, raw_line: str, timestamp: str, event_id: int):
        """Open a new sustained incident."""
        incident_id = self._create_incident(
            incident_type=pattern.name,
            severity=pattern.severity,
            title=f"[{pattern.name}] STARTED: {raw_line[:120]}",
            log_refs=[event_id],
        )

        lifecycle_id = self._conn.execute(
            """INSERT INTO incident_lifecycle
               (incident_id, lifecycle_type, status, started_at, last_segment_at,
                segment_count, pattern_name)
               VALUES (?, 'sustained', 'open', ?, ?, 0, ?)""",
            (incident_id, timestamp, timestamp, pattern.name),
        ).lastrowid
        self._conn.commit()

        self._open_incidents[pattern.name] = OpenIncident(
            lifecycle_id=lifecycle_id,
            incident_id=incident_id,
            pattern=pattern,
            started_at=datetime.fromisoformat(timestamp) if "T" in timestamp else datetime.now(timezone.utc).replace(tzinfo=None),
            last_segment_at=datetime.fromisoformat(timestamp) if "T" in timestamp else datetime.now(timezone.utc).replace(tzinfo=None),
            event_ids=[event_id],
            raw_lines=[raw_line[:500]],
        )

        # Sync start to Neo4j
        self._sync_incident_to_neo4j(incident_id, pattern.name, "sustained_start", timestamp)

        # Alert for sustained start (if critical)
        self._trigger_alert(pattern, incident_id, raw_line, timestamp)

        logger.info(f"Sustained incident OPENED: {pattern.name}")

    def _maybe_create_segment(self, pattern_name: str, event_ts: str = None):
        """Create a segment update if enough time has passed."""
        if pattern_name not in self._open_incidents:
            return

        inc = self._open_incidents[pattern_name]
        # Use event timestamp when available (critical for correct elapsed calculation
        # when processing historical events or in tests)
        if event_ts and "T" in event_ts:
            now = datetime.fromisoformat(event_ts)
        else:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
        elapsed = (now - inc.last_segment_at).total_seconds()

        # Check max duration (auto-close)
        total_elapsed = (now - inc.started_at).total_seconds()
        if total_elapsed > inc.pattern.max_duration:
            self._close_incident(pattern_name, outcome="timeout")
            return

        # Create segment if interval passed
        if elapsed >= inc.pattern.segment_interval:
            inc.segment_count += 1
            ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")

            self._conn.execute(
                """INSERT INTO incident_segments
                   (lifecycle_id, segment_num, timestamp, summary, event_ids)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    inc.lifecycle_id, inc.segment_count, ts,
                    f"Segment #{inc.segment_count}: {len(inc.event_ids)} events, {total_elapsed:.0f}s elapsed",
                    json.dumps(inc.event_ids[-50:]),
                ),
            )

            # Update lifecycle
            self._conn.execute(
                """UPDATE incident_lifecycle
                   SET status = 'in_progress', last_segment_at = ?, segment_count = ?
                   WHERE id = ?""",
                (ts, inc.segment_count, inc.lifecycle_id),
            )
            self._conn.commit()

            inc.last_segment_at = now
            inc.event_ids = []  # Reset for next segment

            # Sync segment to Neo4j
            self._sync_segment_to_neo4j(inc.incident_id, inc.segment_count, ts)

            logger.info(f"Segment #{inc.segment_count} for {pattern_name} ({total_elapsed:.0f}s)")

    def _close_incident(self, pattern_name: str, outcome: str = "success"):
        """Close a sustained incident."""
        if pattern_name not in self._open_incidents:
            return

        inc = self._open_incidents.pop(pattern_name)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")
        duration = (now - inc.started_at).total_seconds()

        # Final segment with remaining events
        if inc.event_ids:
            inc.segment_count += 1
            self._conn.execute(
                """INSERT INTO incident_segments
                   (lifecycle_id, segment_num, timestamp, summary, event_ids)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    inc.lifecycle_id, inc.segment_count, ts,
                    f"FINAL segment: {outcome}, {duration:.0f}s total",
                    json.dumps(inc.event_ids[-50:]),
                ),
            )

        self._close_lifecycle(inc.lifecycle_id, outcome, ts, duration, inc.segment_count)

        # Resolve the parent incident
        self._conn.execute(
            "UPDATE incidents SET resolved = 1, resolved_at = ? WHERE id = ?",
            (ts, inc.incident_id),
        )
        self._conn.commit()

        # Sync closure to Neo4j
        self._sync_incident_to_neo4j(inc.incident_id, pattern_name, "sustained_close", ts, ts, duration)

        logger.info(f"Sustained incident CLOSED: {pattern_name} ({duration:.1f}s, {inc.segment_count} segments, {outcome})")

    def _close_lifecycle(self, lifecycle_id: int, outcome: str = "unknown", ts: str = None, duration: float = None, segments: int = None):
        """Close a lifecycle record."""
        ts = ts or datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")
        updates = ["status = 'closed'", f"closed_at = '{ts}'", f"outcome = '{outcome}'"]
        if duration is not None:
            updates.append(f"duration_seconds = {duration}")
        if segments is not None:
            updates.append(f"segment_count = {segments}")

        self._conn.execute(
            f"UPDATE incident_lifecycle SET {', '.join(updates)} WHERE id = ?",
            (lifecycle_id,),
        )
        self._conn.commit()

    def _create_incident(self, incident_type: str, severity: str, title: str, log_refs: list = None) -> int:
        """Create a new incident record."""
        cur = self._conn.execute(
            """INSERT INTO incidents (type, severity, title, log_refs)
               VALUES (?, ?, ?, ?)""",
            (incident_type, severity, title, json.dumps(log_refs or [])),
        )
        self._conn.commit()
        return cur.lastrowid

    # ─── Real-Time Alerting ─────────────────────────────────

    # Recommended actions per pattern
    RECOMMENDED_ACTIONS = {
        "ssh_login_failed": "Check source IP, consider temporary ban: `ufw deny from <IP>`",
        "ssh_login_success": "Verify this login was expected. Check `last` and `who` output.",
        "ufw_block": "Port scan or probing detected. Monitor for escalation.",
        "service_failed": "Check service logs: `journalctl -u <service> --since '5 min ago'`",
        "oom_kill": "CRITICAL: Memory exhaustion! Check `free -h`, identify and kill runaway process.",
        "apt_install": "Package installation in progress. Verify it's authorized.",
        "service_restart": "Service restarting. Check if planned maintenance.",
    }

    def _trigger_alert(self, pattern: DetectionPattern, incident_id: int, raw_line: str, timestamp: str):
        """Evaluate whether to send a real-time alert."""
        if not self._alert_config.enabled:
            return

        now = time.time()
        severity = pattern.severity

        # Immediate alert for critical/alert severity
        if severity in self._alert_config.immediate_severities:
            self._send_alert(AlertEvent(
                severity=severity,
                title=f"🚨 {severity.upper()}: {pattern.name}",
                summary=raw_line[:300],
                incident_id=incident_id,
                pattern_name=pattern.name,
                source=pattern.source,
                timestamp=timestamp,
                recommended_action=self.RECOMMENDED_ACTIONS.get(pattern.name, "Investigate immediately."),
                raw_lines=[raw_line[:500]],
            ))
            return

        # Warning threshold: track and alert on burst
        if severity == "warning":
            if pattern.name not in self._warning_counter:
                self._warning_counter[pattern.name] = []

            # Clean old entries outside window
            cutoff = now - self._alert_config.warning_window_seconds
            self._warning_counter[pattern.name] = [
                t for t in self._warning_counter[pattern.name] if t > cutoff
            ]
            self._warning_counter[pattern.name].append(now)

            if len(self._warning_counter[pattern.name]) >= self._alert_config.warning_threshold:
                count = len(self._warning_counter[pattern.name])
                self._send_alert(AlertEvent(
                    severity="warning",
                    title=f"⚠️ WARNING BURST: {pattern.name} ({count}× in {self._alert_config.warning_window_seconds}s)",
                    summary=f"{count} events detected. Latest: {raw_line[:200]}",
                    incident_id=incident_id,
                    pattern_name=pattern.name,
                    source=pattern.source,
                    timestamp=timestamp,
                    recommended_action=self.RECOMMENDED_ACTIONS.get(pattern.name, "Monitor situation."),
                ))
                # Reset counter after alert
                self._warning_counter[pattern.name] = []

    def _send_alert(self, alert: AlertEvent):
        """Dispatch alert through configured channels."""
        logger.warning(f"ALERT [{alert.severity}] {alert.title}: {alert.summary[:100]}")

        # 1. Custom callback (e.g., inject into OpenClaw session)
        if self._alert_config.callback:
            try:
                self._alert_config.callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        # 2. Write to alert file (for OpenClaw heartbeat/cron pickup)
        if self._alert_config.alert_file:
            try:
                alert_data = {
                    "timestamp": alert.timestamp,
                    "severity": alert.severity,
                    "title": alert.title,
                    "summary": alert.summary,
                    "pattern": alert.pattern_name,
                    "incident_id": alert.incident_id,
                    "action": alert.recommended_action,
                }
                with open(self._alert_config.alert_file, "a") as f:
                    f.write(json.dumps(alert_data, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"Alert file write failed: {e}")

        # 3. Discord webhook (direct push)
        if self._alert_config.discord_webhook:
            try:
                import urllib.request
                payload = json.dumps({
                    "content": f"**{alert.title}**\n{alert.summary[:500]}\n\n📋 Action: {alert.recommended_action}",
                }).encode()
                req = urllib.request.Request(
                    self._alert_config.discord_webhook,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                logger.error(f"Discord webhook failed: {e}")

        # 4. Store alert in DB for audit trail
        try:
            self._conn.execute(
                """INSERT INTO audit_events
                   (timestamp, source, severity, category, agent_id, hostname,
                    event_type, summary, details, content_hash)
                   VALUES (?, 'alert_system', ?, 'alert', ?, ?, 'alert_sent', ?, ?, ?)""",
                (
                    alert.timestamp, alert.severity, self.agent_id, self.hostname,
                    alert.title,
                    json.dumps({"pattern": alert.pattern_name, "action": alert.recommended_action}),
                    f"alert_{alert.incident_id}_{alert.pattern_name}",
                ),
            )
            self._conn.commit()
        except Exception:
            pass

    # ─── Neo4j Sync ───────────────────────────────────────

    def _get_neo4j_driver(self):
        """Lazy-init Neo4j driver."""
        if self._neo4j_driver:
            return self._neo4j_driver
        try:
            from neo4j import GraphDatabase
            self._neo4j_driver = GraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password),
            )
            return self._neo4j_driver
        except Exception as e:
            logger.warning(f"Neo4j unavailable: {e}")
            return None

    def _sync_incident_to_neo4j(
        self, incident_id: int, pattern_name: str, event_type: str,
        started_at: str, closed_at: str = None, duration: float = None,
    ):
        """Sync an incident to Neo4j as an Incident node."""
        driver = self._get_neo4j_driver()
        if not driver:
            return

        try:
            with driver.session() as session:
                session.run(
                    """MERGE (i:Incident {sqlite_id: $id, hostname: $hostname})
                       ON CREATE SET
                           i.pattern = $pattern,
                           i.event_type = $event_type,
                           i.started_at = datetime($started_at),
                           i.hostname = $hostname,
                           i.agent_id = $agent_id
                       ON MATCH SET
                           i.event_type = $event_type,
                           i.updated_at = datetime()
                       SET i.closed_at = CASE WHEN $closed_at IS NOT NULL THEN datetime($closed_at) ELSE i.closed_at END,
                           i.duration_seconds = CASE WHEN $duration IS NOT NULL THEN $duration ELSE i.duration_seconds END
                    """,
                    id=incident_id, pattern=pattern_name, event_type=event_type,
                    started_at=started_at[:19],  # trim microseconds for Neo4j
                    closed_at=closed_at[:19] if closed_at else None,
                    duration=duration, hostname=self.hostname, agent_id=self.agent_id,
                )

                # Link to host machine node
                session.run(
                    """MERGE (h:Host {hostname: $hostname})
                       WITH h
                       MATCH (i:Incident {sqlite_id: $id, hostname: $hostname})
                       MERGE (h)-[:HAS_INCIDENT]->(i)
                    """,
                    hostname=self.hostname, id=incident_id,
                )

            # Mark as synced
            self._conn.execute(
                "UPDATE incidents SET neo4j_synced = 1 WHERE id = ?",
                (incident_id,),
            )
            self._conn.commit()

        except Exception as e:
            logger.warning(f"Neo4j sync failed for incident {incident_id}: {e}")

    def _sync_segment_to_neo4j(self, incident_id: int, segment_num: int, timestamp: str):
        """Sync a segment to Neo4j."""
        driver = self._get_neo4j_driver()
        if not driver:
            return

        try:
            with driver.session() as session:
                session.run(
                    """MATCH (i:Incident {sqlite_id: $inc_id, hostname: $hostname})
                       MERGE (s:IncidentSegment {incident_id: $inc_id, segment_num: $seg_num, hostname: $hostname})
                       ON CREATE SET s.timestamp = datetime($ts)
                       MERGE (i)-[:HAS_SEGMENT]->(s)
                    """,
                    inc_id=incident_id, seg_num=segment_num,
                    ts=timestamp[:19], hostname=self.hostname,
                )
        except Exception as e:
            logger.warning(f"Neo4j segment sync failed: {e}")

    # ─── Log Source Watchers ──────────────────────────────

    def _watch_journal(self):
        """Follow journalctl in real-time."""
        try:
            proc = subprocess.Popen(
                ["journalctl", "--follow", "--no-pager", "-o", "short-iso",
                 "--since", "now"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            logger.info("Journal watcher started")

            while not self._stop_event.is_set():
                if proc.poll() is not None:
                    logger.warning("journalctl process exited, restarting...")
                    time.sleep(5)
                    return self._watch_journal()

                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                line = line.strip()
                if not line:
                    continue

                # Determine source from content
                source = "systemd"
                if "sshd" in line:
                    source = "ssh"
                elif "[UFW" in line:
                    source = "ufw"
                elif "kernel" in line and ("oom" in line.lower() or "error" in line.lower()):
                    source = "kernel"

                # Extract timestamp
                ts_match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                ts = ts_match.group(1) if ts_match else None

                try:
                    self.process_event(source=source, raw_line=line, timestamp=ts)
                except Exception as e:
                    logger.error(f"Error processing journal line: {e}")

        except FileNotFoundError:
            logger.warning("journalctl not found, journal watching disabled")
        except Exception as e:
            logger.error(f"Journal watcher error: {e}")

    def _watch_dpkg(self):
        """Watch dpkg.log for package events using tail -F."""
        dpkg_log = Path("/var/log/dpkg.log")
        if not dpkg_log.exists():
            logger.info("dpkg.log not found, dpkg watching disabled")
            return

        try:
            proc = subprocess.Popen(
                ["tail", "-F", "-n", "0", str(dpkg_log)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
            logger.info("dpkg watcher started")

            while not self._stop_event.is_set():
                if proc.poll() is not None:
                    time.sleep(5)
                    return self._watch_dpkg()

                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue

                line = line.strip()
                if not line:
                    continue

                # Extract timestamp from dpkg log format: "2026-03-09 08:50:00 ..."
                ts_match = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", line)
                ts = f"{ts_match.group(1)}T{ts_match.group(2)}" if ts_match else None

                try:
                    self.process_event(source="dpkg", raw_line=line, timestamp=ts)
                except Exception as e:
                    logger.error(f"Error processing dpkg line: {e}")

        except Exception as e:
            logger.error(f"dpkg watcher error: {e}")

    def _check_timeouts(self):
        """Periodically check for timed-out sustained incidents."""
        while not self._stop_event.is_set():
            time.sleep(30)  # Check every 30 seconds

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for pattern_name in list(self._open_incidents.keys()):
                inc = self._open_incidents[pattern_name]
                elapsed = (now - inc.started_at).total_seconds()
                if elapsed > inc.pattern.max_duration:
                    logger.info(f"Auto-closing timed-out incident: {pattern_name} ({elapsed:.0f}s)")
                    self._close_incident(pattern_name, outcome="timeout")

    # ─── Main Run Loop ────────────────────────────────────

    def run(self):
        """Start real-time log processing. Blocks until stop() is called."""
        self.init_db()
        logger.info(f"Stream processor started (agent={self.agent_id}, host={self.hostname})")
        logger.info(f"Patterns loaded: {len(self._patterns)} ({sum(1 for p in self._patterns if p.incident_type == IncidentType.SUSTAINED)} sustained)")

        threads = [
            threading.Thread(target=self._watch_journal, daemon=True, name="journal-watcher"),
            threading.Thread(target=self._watch_dpkg, daemon=True, name="dpkg-watcher"),
            threading.Thread(target=self._check_timeouts, daemon=True, name="timeout-checker"),
        ]

        for t in threads:
            t.start()

        try:
            self._stop_event.wait()
        except KeyboardInterrupt:
            logger.info("Shutting down stream processor...")
            self.stop()

    def stop(self):
        """Stop the stream processor."""
        self._stop_event.set()

        # Close all open incidents
        for pattern_name in list(self._open_incidents.keys()):
            self._close_incident(pattern_name, outcome="shutdown")

        self.close()
        logger.info("Stream processor stopped")

    # ─── Statistics ───────────────────────────────────────

    def stats(self) -> dict:
        """Return processing statistics."""
        if not self._conn:
            self.init_db()

        total_events = self._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        total_incidents = self._conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        open_incidents = len(self._open_incidents)

        lifecycle_stats = self._conn.execute(
            """SELECT lifecycle_type, status, COUNT(*) as cnt
               FROM incident_lifecycle
               GROUP BY lifecycle_type, status"""
        ).fetchall()

        return {
            "total_events": total_events,
            "total_incidents": total_incidents,
            "open_incidents": open_incidents,
            "open_patterns": list(self._open_incidents.keys()),
            "lifecycle": [dict(r) for r in lifecycle_stats],
        }


# ─── CLI Entry Point ─────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="UAML Audit Stream Processor")
    parser.add_argument("--db", default=os.path.expanduser("~/.openclaw/workspace/data/audit_log.db"),
                        help="Path to audit database")
    parser.add_argument("--agent-id", default="Metod", help="Agent identifier")
    parser.add_argument("--stats", action="store_true", help="Show statistics and exit")
    parser.add_argument("--alert-file", default=os.path.expanduser("~/.openclaw/workspace/data/security_alerts.jsonl"),
                        help="Path to write alerts (JSONL)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Configure alerting
    discord_webhook = os.environ.get("DISCORD_WEBHOOK")
    alert_cfg = AlertConfig(
        enabled=True,
        alert_file=args.alert_file,
        discord_webhook=discord_webhook,
    )

    processor = StreamProcessor(
        db_path=args.db,
        agent_id=args.agent_id,
        neo4j_uri=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD", "uaml2026secure"),
        alert_config=alert_cfg,
    )

    if args.stats:
        processor.init_db()
        stats = processor.stats()
        print(json.dumps(stats, indent=2))
    else:
        print(f"🔄 Starting real-time audit stream processor...")
        print(f"   Agent: {args.agent_id}")
        print(f"   DB: {args.db}")
        print(f"   Patterns: {len(DETECTION_PATTERNS)}")
        processor.run()


if __name__ == "__main__":
    main()
