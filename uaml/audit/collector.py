# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Audit Log Collector — ingests events from multiple sources into audit_log.db.

Sources:
  - SSH auth logs (/var/log/auth.log)
  - Firewall logs (journalctl -u nftables / iptables)
  - Systemd journal (service events)
  - File integrity checks (hash monitoring)
  - UAML API events (passed programmatically)

Usage:
    collector = AuditCollector("/path/to/audit_log.db", agent_id="Metod", hostname="vmi3100682")
    collector.init_db()
    collector.collect_ssh()
    collector.collect_systemd()
    collector.check_file_integrity()
    collector.detect_anomalies()
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


class AuditCollector:
    """Collects security events from system logs into audit_log.db."""

    def __init__(self, db_path: str, agent_id: str = "unknown", hostname: str = ""):
        self.db_path = Path(db_path)
        self.agent_id = agent_id
        self.hostname = hostname or platform.node()
        self._conn: Optional[sqlite3.Connection] = None

    def init_db(self):
        """Initialize audit database with schema."""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        schema_path = Path(__file__).parent / "schema.sql"
        if schema_path.exists():
            self._conn.executescript(schema_path.read_text())
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _hash_event(self, source: str, event_type: str, summary: str, timestamp: str) -> str:
        """Create tamper-detection hash for an event."""
        data = f"{timestamp}|{source}|{event_type}|{summary}"
        return hashlib.sha256(data.encode()).hexdigest()

    def log_event(
        self,
        source: str,
        category: str,
        event_type: str,
        summary: str,
        severity: str = "info",
        details: dict = None,
        source_file: str = None,
        source_line: int = None,
        remote_ip: str = None,
        user_id: str = None,
        raw_line: str = None,
    ) -> int:
        """Log a single audit event. Returns the event ID."""
        if not self._conn:
            self.init_db()

        ts = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S.%f")
        content_hash = self._hash_event(source, event_type, summary, ts)

        cur = self._conn.execute(
            """INSERT INTO audit_events
               (timestamp, source, severity, category, agent_id, hostname,
                event_type, summary, details, source_file, source_line,
                remote_ip, user_id, raw_line, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts, source, severity, category, self.agent_id, self.hostname,
                event_type, summary,
                json.dumps(details, ensure_ascii=False) if details else None,
                source_file, source_line, remote_ip, user_id, raw_line, content_hash,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # ─── SSH Log Collection ───────────────────────────────

    def collect_ssh(self, since_minutes: int = 30) -> int:
        """Parse /var/log/auth.log for SSH events."""
        auth_log = Path("/var/log/auth.log")
        if not auth_log.exists():
            return 0

        count = 0
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=since_minutes)

        try:
            lines = auth_log.read_text(errors="replace").splitlines()
        except PermissionError:
            return 0

        for i, line in enumerate(lines[-500:], start=max(1, len(lines) - 500)):
            if "sshd" not in line:
                continue

            if "Failed password" in line or "Invalid user" in line:
                ip_match = re.search(r"from (\d+\.\d+\.\d+\.\d+)", line)
                user_match = re.search(r"for (?:invalid user )?(\S+)", line)
                self.log_event(
                    source="ssh", category="auth", event_type="ssh_login_failed",
                    summary=f"Failed SSH login: {user_match.group(1) if user_match else '?'} from {ip_match.group(1) if ip_match else '?'}",
                    severity="warning",
                    source_file=str(auth_log), source_line=i,
                    remote_ip=ip_match.group(1) if ip_match else None,
                    user_id=user_match.group(1) if user_match else None,
                    raw_line=line,
                )
                count += 1

            elif "Accepted" in line:
                ip_match = re.search(r"from (\d+\.\d+\.\d+\.\d+)", line)
                user_match = re.search(r"for (\S+)", line)
                method = "password" if "password" in line else "publickey"
                self.log_event(
                    source="ssh", category="auth", event_type=f"ssh_login_{method}",
                    summary=f"SSH login ({method}): {user_match.group(1) if user_match else '?'} from {ip_match.group(1) if ip_match else '?'}",
                    severity="info" if method == "publickey" else "warning",
                    details={"method": method},
                    source_file=str(auth_log), source_line=i,
                    remote_ip=ip_match.group(1) if ip_match else None,
                    user_id=user_match.group(1) if user_match else None,
                    raw_line=line,
                )
                count += 1

        return count

    # ─── Systemd Journal Collection ──────────────────────

    def collect_systemd(self, since_minutes: int = 30) -> int:
        """Collect service start/stop/fail events from journalctl."""
        count = 0
        try:
            result = subprocess.run(
                ["journalctl", "--since", f"{since_minutes} min ago",
                 "--no-pager", "-o", "json", "--output-fields=MESSAGE,_SYSTEMD_UNIT,PRIORITY"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return 0

            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = entry.get("MESSAGE", "")
                if isinstance(msg, list):
                    msg = " ".join(str(m) for m in msg)
                msg = str(msg)
                unit = entry.get("_SYSTEMD_UNIT", "")
                priority = int(entry.get("PRIORITY", 6))

                # Only interesting events
                if any(kw in msg.lower() for kw in ["started", "stopped", "failed", "error", "crash"]):
                    sev = "critical" if priority <= 3 else "warning" if priority <= 4 else "info"
                    self.log_event(
                        source="systemd", category="service",
                        event_type="service_event",
                        summary=f"[{unit}] {msg[:200]}",
                        severity=sev,
                        details={"unit": unit, "priority": priority},
                    )
                    count += 1
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return count

    # ─── File Integrity Monitoring ────────────────────────

    def check_file_integrity(self) -> int:
        """Check monitored files for changes."""
        if not self._conn:
            self.init_db()

        count = 0
        rows = self._conn.execute(
            "SELECT id, file_path, last_hash, last_size FROM monitored_files WHERE alert_on_change = 1"
        ).fetchall()

        for row in rows:
            fpath = Path(row["file_path"])
            try:
                exists = fpath.exists()
            except PermissionError:
                continue
            if not exists:
                if row["last_hash"] is not None:
                    self.log_event(
                        source="file_integrity", category="integrity",
                        event_type="file_deleted",
                        summary=f"Monitored file deleted: {fpath}",
                        severity="critical",
                        source_file=str(fpath),
                    )
                    count += 1
                continue

            try:
                content = fpath.read_bytes()
                current_hash = hashlib.sha256(content).hexdigest()
                current_size = len(content)
            except PermissionError:
                continue

            now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S")

            if row["last_hash"] and current_hash != row["last_hash"]:
                self.log_event(
                    source="file_integrity", category="integrity",
                    event_type="file_hash_changed",
                    summary=f"File modified: {fpath} (size: {row['last_size']}→{current_size})",
                    severity="critical",
                    details={
                        "old_hash": row["last_hash"],
                        "new_hash": current_hash,
                        "old_size": row["last_size"],
                        "new_size": current_size,
                    },
                    source_file=str(fpath),
                )
                count += 1

            self._conn.execute(
                "UPDATE monitored_files SET last_hash=?, last_size=?, last_modified=?, last_checked=? WHERE id=?",
                (current_hash, current_size, now, now, row["id"]),
            )

        self._conn.commit()
        return count

    # ─── Anomaly Detection ────────────────────────────────

    def detect_anomalies(self) -> list[dict]:
        """Run anomaly rules against recent events. Returns detected anomalies."""
        if not self._conn:
            self.init_db()

        anomalies = []
        rules = self._conn.execute(
            "SELECT * FROM anomaly_rules WHERE enabled = 1"
        ).fetchall()

        for rule in rules:
            window_start = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=rule["window_seconds"])).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            matches = self._conn.execute(
                """SELECT COUNT(*) as cnt FROM audit_events
                   WHERE source = ? AND timestamp > ? AND (summary LIKE ? OR details LIKE ?)""",
                (rule["source"], window_start, f"%{rule['pattern']}%", f"%{rule['pattern']}%"),
            ).fetchone()

            if matches["cnt"] >= rule["threshold"]:
                # Get IDs of matching events for back-reference
                event_ids = self._conn.execute(
                    """SELECT id FROM audit_events
                       WHERE source = ? AND timestamp > ? AND (summary LIKE ? OR details LIKE ?)
                       ORDER BY timestamp DESC LIMIT 100""",
                    (rule["source"], window_start, f"%{rule['pattern']}%", f"%{rule['pattern']}%"),
                ).fetchall()
                log_refs = [r[0] for r in event_ids]

                anomaly = {
                    "rule": rule["name"],
                    "description": rule["description"],
                    "count": matches["cnt"],
                    "threshold": rule["threshold"],
                    "severity": rule["severity"],
                    "window_seconds": rule["window_seconds"],
                }
                anomalies.append(anomaly)

                # Log the anomaly as an event
                self.log_event(
                    source="anomaly_detector", category="anomaly",
                    event_type=f"anomaly_{rule['name']}",
                    summary=f"ANOMALY: {rule['description']} ({matches['cnt']} events in {rule['window_seconds']}s)",
                    severity=rule["severity"],
                    details=anomaly,
                )

                # Create incident with back-references
                self._conn.execute(
                    """INSERT INTO incidents
                       (rule_name, severity, summary, event_count, log_refs)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        rule["name"], rule["severity"],
                        f"{rule['description']} ({matches['cnt']} events in {rule['window_seconds']}s)",
                        matches["cnt"],
                        json.dumps(log_refs),
                    ),
                )
                self._conn.commit()

        return anomalies

    # ─── DPKG Log Collection ─────────────────────────────

    def collect_dpkg(self, since_hours: int = 24) -> int:
        """Parse /var/log/dpkg.log for package events."""
        dpkg_log = Path("/var/log/dpkg.log")
        if not dpkg_log.exists():
            return 0

        count = 0
        cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=since_hours)).strftime("%Y-%m-%d")

        try:
            lines = dpkg_log.read_text(errors="replace").splitlines()
        except PermissionError:
            return 0

        for i, line in enumerate(lines):
            if not line.strip():
                continue
            ts_match = re.match(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", line)
            if not ts_match:
                continue

            ts_str = ts_match.group(1).replace(" ", "T")
            if ts_str[:10] < cutoff:
                continue

            m = re.match(
                r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(install|upgrade|remove|configure)\s+(\S+)\s+(\S+)",
                line,
            )
            if m:
                action, package, version = m.group(1), m.group(2), m.group(3)
                severity = "info" if action in ("install", "upgrade", "configure") else "warning"
                self.log_event(
                    source="dpkg", category="modification",
                    event_type=f"package_{action}",
                    summary=f"dpkg {action}: {package} {version}",
                    severity=severity,
                    details={"action": action, "package": package, "version": version, "raw_line": line},
                    source_file=str(dpkg_log), source_line=i,
                )
                count += 1

        return count

    # ─── UFW Firewall Log Collection ─────────────────────

    def collect_ufw(self, since_minutes: int = 30) -> int:
        """Collect UFW firewall events from journal or /var/log/ufw.log."""
        count = 0

        # Try journalctl first
        try:
            result = subprocess.run(
                ["journalctl", "-k", "--since", f"{since_minutes} min ago",
                 "--no-pager", "--grep", "UFW"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    if "[UFW" not in line:
                        continue

                    action = "BLOCK" if "BLOCK" in line else "ALLOW" if "ALLOW" in line else "OTHER"
                    src_ip = re.search(r"SRC=(\S+)", line)
                    dst_port = re.search(r"DPT=(\d+)", line)
                    proto = re.search(r"PROTO=(\S+)", line)

                    meta = {"raw_line": line}
                    if src_ip: meta["src_ip"] = src_ip.group(1)
                    if dst_port: meta["dst_port"] = dst_port.group(1)
                    if proto: meta["proto"] = proto.group(1)

                    self.log_event(
                        source="ufw", category="network",
                        event_type=f"firewall_{action.lower()}",
                        summary=f"UFW {action}: {meta.get('src_ip', '?')} → :{meta.get('dst_port', '?')} ({meta.get('proto', '?')})",
                        severity="warning" if action == "BLOCK" else "info",
                        details=meta,
                        remote_ip=meta.get("src_ip"),
                    )
                    count += 1
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fallback: /var/log/ufw.log
        if count == 0:
            ufw_log = Path("/var/log/ufw.log")
            if ufw_log.exists():
                try:
                    for line in ufw_log.read_text(errors="replace").splitlines()[-200:]:
                        if "[UFW" not in line:
                            continue
                        action = "BLOCK" if "BLOCK" in line else "ALLOW"
                        src_ip = re.search(r"SRC=(\S+)", line)
                        dst_port = re.search(r"DPT=(\d+)", line)
                        self.log_event(
                            source="ufw", category="network",
                            event_type=f"firewall_{action.lower()}",
                            summary=f"UFW {action}: {src_ip.group(1) if src_ip else '?'} → :{dst_port.group(1) if dst_port else '?'}",
                            severity="warning" if action == "BLOCK" else "info",
                            details={"raw_line": line},
                            remote_ip=src_ip.group(1) if src_ip else None,
                        )
                        count += 1
                except PermissionError:
                    pass

        return count

    # ─── OpenClaw Session Log Collection ─────────────────

    def collect_openclaw(self, sessions_dir: str = None, max_sessions: int = 20) -> int:
        """Collect error/restart events from OpenClaw session logs."""
        if sessions_dir is None:
            sessions_dir = os.path.expanduser("~/.openclaw/agents/main/sessions")

        sdir = Path(sessions_dir)
        if not sdir.exists():
            return 0

        count = 0
        for session_file in sorted(sdir.glob("*.jsonl"))[-max_sessions:]:
            try:
                with open(session_file) as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                            role = entry.get("role", "")
                            ts = entry.get("ts", "")
                            content = str(entry.get("content", ""))

                            if role == "tool" and ("error" in content.lower() or "failed" in content.lower()):
                                self.log_event(
                                    source="openclaw", category="service",
                                    event_type="tool_error",
                                    summary=f"Tool error in {session_file.name}: {content[:200]}",
                                    severity="warning",
                                    details={"session": session_file.name, "raw_line": content[:500]},
                                )
                                count += 1

                            elif role == "system" and "restart" in content.lower():
                                self.log_event(
                                    source="openclaw", category="service",
                                    event_type="gateway_restart",
                                    summary=f"OpenClaw restart: {session_file.name}",
                                    severity="info",
                                    details={"session": session_file.name},
                                )
                                count += 1
                        except json.JSONDecodeError:
                            continue
            except Exception:
                continue

        return count

    # ─── Incident Creation ────────────────────────────────

    def create_incident(
        self,
        incident_type: str,
        severity: str,
        title: str,
        description: str = None,
        log_refs: list = None,
        metadata: dict = None,
    ) -> int:
        """Create a new incident from anomaly detection."""
        if not self._conn:
            self.init_db()

        # Check for existing open incident of same type (within 1 hour)
        existing = self._conn.execute(
            """SELECT id, log_refs FROM incidents
               WHERE type = ? AND resolved = 0
               AND detected_at > datetime('now', '-1 hour')""",
            (incident_type,),
        ).fetchone()

        if existing:
            # Update existing
            old_refs = json.loads(existing["log_refs"] or "[]")
            new_refs = list(set(old_refs + (log_refs or [])))
            self._conn.execute(
                "UPDATE incidents SET log_refs = ?, description = ? WHERE id = ?",
                (json.dumps(new_refs), description, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]

        cur = self._conn.execute(
            """INSERT INTO incidents (type, severity, title, description, log_refs, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                incident_type, severity, title, description,
                json.dumps(log_refs or []),
                json.dumps(metadata or {}),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    # ─── Enhanced Anomaly Detection with Incidents ────────

    def detect_anomalies_with_incidents(self) -> list[dict]:
        """Run anomaly rules and create incidents for triggers."""
        anomalies = self.detect_anomalies()

        for anomaly in anomalies:
            # Get matching event IDs for back-reference
            rule_name = anomaly["rule"]
            window_start = (
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=anomaly["window_seconds"])
            ).strftime("%Y-%m-%dT%H:%M:%S")

            events = self._conn.execute(
                """SELECT id FROM audit_events
                   WHERE timestamp > ? AND source_file IS NOT NULL
                   ORDER BY timestamp DESC LIMIT 100""",
                (window_start,),
            ).fetchall()
            log_ids = [e["id"] for e in events]

            incident_type_map = {
                "ssh_brute_force": "brute_force",
                "ssh_root_login": "unauthorized_access",
                "api_unknown_ip": "unauthorized_access",
                "service_restart_loop": "service_crash",
                "file_integrity_fail": "config_drift",
                "db_external_modify": "unauthorized_access",
                "firewall_port_scan": "port_scan",
                "unusual_outbound": "suspicious_access",
            }

            self.create_incident(
                incident_type=incident_type_map.get(rule_name, rule_name),
                severity=anomaly["severity"],
                title=f"{anomaly['description']}: {anomaly['count']} events",
                description=f"Rule '{rule_name}' triggered: {anomaly['count']} events in {anomaly['window_seconds']}s",
                log_refs=log_ids[:50],
                metadata=anomaly,
            )

        return anomalies

    # ─── Full Collection Run ──────────────────────────────

    def run(self, since_minutes: int = 30) -> dict:
        """Run full collection cycle: all sources + anomaly detection + incidents."""
        self.init_db()
        results = {
            "ssh": self.collect_ssh(since_minutes),
            "systemd": self.collect_systemd(since_minutes),
            "ufw": self.collect_ufw(since_minutes),
            "dpkg": self.collect_dpkg(since_hours=max(1, since_minutes // 60) or 24),
            "openclaw": self.collect_openclaw(),
            "file_integrity": self.check_file_integrity(),
        }
        results["anomalies"] = self.detect_anomalies_with_incidents()
        results["total_events"] = sum(v for k, v in results.items() if isinstance(v, int))

        self.close()
        return results
