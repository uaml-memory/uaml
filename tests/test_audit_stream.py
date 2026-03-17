"""Tests for UAML Audit Stream Processor — incident lifecycle management."""

import json
import os
import sqlite3
import tempfile
import time

import pytest

from uaml.audit.stream import (
    StreamProcessor,
    DetectionPattern,
    IncidentType,
    DETECTION_PATTERNS,
    OpenIncident,
    AlertConfig,
    AlertEvent,
)


@pytest.fixture
def processor(tmp_path):
    """Create a StreamProcessor with temp DB."""
    db = tmp_path / "test_audit.db"
    proc = StreamProcessor(str(db), agent_id="test-agent", hostname="test-host")
    proc.init_db()
    yield proc
    proc.close()


class TestStreamSchema:
    """Test database schema initialization."""

    def test_schema_created(self, processor):
        tables = processor._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in tables}
        assert "audit_events" in names
        assert "incidents" in names
        assert "incident_lifecycle" in names
        assert "incident_segments" in names

    def test_anomaly_rules_loaded(self, processor):
        count = processor._conn.execute("SELECT COUNT(*) FROM anomaly_rules").fetchone()[0]
        assert count >= 8


class TestSpikeIncidents:
    """Test spike (short) incident processing."""

    def test_ssh_failed_login(self, processor):
        event_id = processor.process_event(
            source="ssh",
            raw_line="Mar  9 08:50:01 vmi3100682 sshd[12345]: Failed password for root from 1.2.3.4 port 22",
            timestamp="2026-03-09T08:50:01",
        )
        assert event_id is not None

        # Should create a closed incident
        incidents = processor._conn.execute(
            "SELECT * FROM incidents WHERE type = 'ssh_login_failed'"
        ).fetchall()
        assert len(incidents) >= 1
        assert incidents[0]["resolved"] == 1

        # Should have lifecycle entry
        lifecycle = processor._conn.execute(
            "SELECT * FROM incident_lifecycle WHERE pattern_name = 'ssh_login_failed'"
        ).fetchall()
        assert len(lifecycle) >= 1
        assert lifecycle[0]["lifecycle_type"] == "spike"
        assert lifecycle[0]["status"] == "closed"

    def test_ufw_block(self, processor):
        processor.process_event(
            source="ufw",
            raw_line="[UFW BLOCK] IN=eth0 SRC=5.6.7.8 DST=1.2.3.4 PROTO=TCP DPT=22",
            timestamp="2026-03-09T09:00:00",
        )

        incidents = processor._conn.execute(
            "SELECT * FROM incidents WHERE type = 'ufw_block'"
        ).fetchall()
        assert len(incidents) >= 1

    def test_service_failed(self, processor):
        processor.process_event(
            source="systemd",
            raw_line="Failed to start OpenClaw Gateway Service",
            timestamp="2026-03-09T09:01:00",
        )

        incidents = processor._conn.execute(
            "SELECT * FROM incidents WHERE type = 'service_failed'"
        ).fetchall()
        assert len(incidents) >= 1
        assert incidents[0]["severity"] == "critical"


class TestSustainedIncidents:
    """Test sustained (long) incident lifecycle."""

    def test_apt_install_lifecycle(self, processor):
        """Simulate an apt install: start → segments → end."""
        # START
        processor.process_event(
            source="dpkg",
            raw_line="2026-03-09 09:00:00 install neo4j 5.26.0-1 <none>",
            timestamp="2026-03-09T09:00:00",
        )
        assert "apt_install" in processor._open_incidents
        inc = processor._open_incidents["apt_install"]
        assert inc.pattern.name == "apt_install"

        # Intermediate events (within segment interval — no segment created yet)
        processor.process_event(
            source="dpkg",
            raw_line="2026-03-09 09:00:30 status half-installed neo4j 5.26.0-1",
            timestamp="2026-03-09T09:00:30",
        )

        # END
        processor.process_event(
            source="dpkg",
            raw_line="2026-03-09 09:01:00 status installed neo4j 5.26.0-1",
            timestamp="2026-03-09T09:01:00",
        )

        # Should be closed
        assert "apt_install" not in processor._open_incidents

        lifecycle = processor._conn.execute(
            "SELECT * FROM incident_lifecycle WHERE pattern_name = 'apt_install'"
        ).fetchall()
        assert len(lifecycle) >= 1
        assert lifecycle[0]["status"] == "closed"
        assert lifecycle[0]["outcome"] == "success"

    def test_service_restart_lifecycle(self, processor):
        """Simulate service stop → start."""
        processor.process_event(
            source="systemd",
            raw_line="Stopping OpenClaw Gateway...",
            timestamp="2026-03-09T10:00:00",
        )
        assert "service_restart" in processor._open_incidents

        processor.process_event(
            source="systemd",
            raw_line="Started OpenClaw Gateway.",
            timestamp="2026-03-09T10:00:05",
        )
        assert "service_restart" not in processor._open_incidents

    def test_sustained_auto_timeout(self, processor):
        """Sustained incidents auto-close after max_duration."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        ts_start = (now - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S")

        processor.process_event(
            source="dpkg",
            raw_line=f"{ts_start[:10]} {ts_start[11:19]} install bigpackage 1.0.0 <none>",
            timestamp=ts_start,
        )

        # Manually set started_at to exceed max_duration (1800s)
        inc = processor._open_incidents["apt_install"]
        inc.started_at = now - timedelta(seconds=2000)
        inc.last_segment_at = now - timedelta(seconds=120)

        # Send another dpkg event to trigger the timeout check
        ts_now = now.strftime("%Y-%m-%dT%H:%M:%S")
        processor.process_event(
            source="dpkg",
            raw_line=f"{ts_now[:10]} {ts_now[11:19]} status unpacked bigpackage 1.0.0",
            timestamp=ts_now,
        )

        assert "apt_install" not in processor._open_incidents

    def test_segment_creation(self, processor):
        """Segments are created at the configured interval."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        ts_start = (now - timedelta(seconds=180)).strftime("%Y-%m-%dT%H:%M:%S")

        processor.process_event(
            source="dpkg",
            raw_line=f"{ts_start[:10]} {ts_start[11:19]} install package1 1.0 <none>",
            timestamp=ts_start,
        )

        # Verify incident was opened
        assert "apt_install" in processor._open_incidents
        inc = processor._open_incidents["apt_install"]

        # started_at/last_segment_at should be ~180s ago, enough for segment_interval=60
        ts_mid = (now - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S")
        processor.process_event(
            source="dpkg",
            raw_line=f"{ts_mid[:10]} {ts_mid[11:19]} status unpacked package1 1.0",
            timestamp=ts_mid,
        )

        # Check segment was created
        segments = processor._conn.execute(
            "SELECT * FROM incident_segments WHERE lifecycle_id = ?",
            (inc.lifecycle_id,),
        ).fetchall()
        assert len(segments) >= 1
        assert segments[0]["segment_num"] == 1


class TestEventStorage:
    """Test raw event storage."""

    def test_event_stored(self, processor):
        event_id = processor.process_event(
            source="systemd",
            raw_line="Something happened",
            timestamp="2026-03-09T08:00:00",
        )
        assert event_id is not None

        row = processor._conn.execute(
            "SELECT * FROM audit_events WHERE id = ?", (event_id,)
        ).fetchone()
        assert row is not None
        assert row["source"] == "systemd"
        assert "Something happened" in row["summary"]

    def test_severity_auto_detection(self, processor):
        """Critical keywords → critical severity."""
        eid = processor.process_event(
            source="systemd",
            raw_line="kernel: FATAL error in module X",
        )
        row = processor._conn.execute(
            "SELECT severity FROM audit_events WHERE id = ?", (eid,)
        ).fetchone()
        assert row["severity"] == "critical"

    def test_empty_line_ignored(self, processor):
        result = processor.process_event(source="systemd", raw_line="")
        assert result is None

        result2 = processor.process_event(source="systemd", raw_line="   ")
        assert result2 is None


class TestRecovery:
    """Test incident recovery after restart."""

    def test_recover_open_incidents(self, tmp_path):
        """Open incidents should be recovered after restart."""
        db = tmp_path / "recovery_test.db"

        # First processor — create an open incident
        proc1 = StreamProcessor(str(db), agent_id="test", hostname="test")
        proc1.init_db()
        proc1.process_event(
            source="dpkg",
            raw_line="2026-03-09 09:00:00 install neo4j 5.26.0-1 <none>",
            timestamp="2026-03-09T09:00:00",
        )
        assert "apt_install" in proc1._open_incidents
        proc1._conn.close()
        proc1._conn = None

        # Second processor — should recover the open incident
        proc2 = StreamProcessor(str(db), agent_id="test", hostname="test")
        proc2.init_db()
        assert "apt_install" in proc2._open_incidents
        proc2.close()


class TestStats:
    """Test statistics."""

    def test_stats_empty(self, processor):
        stats = processor.stats()
        assert stats["total_events"] == 0
        assert stats["total_incidents"] == 0
        assert stats["open_incidents"] == 0

    def test_stats_after_events(self, processor):
        processor.process_event(
            source="ssh",
            raw_line="Failed password for root from 1.2.3.4",
            timestamp="2026-03-09T08:00:00",
        )
        stats = processor.stats()
        assert stats["total_events"] >= 1
        assert stats["total_incidents"] >= 1
        assert stats["open_incidents"] == 0  # spike = immediately closed


class TestPatternConfig:
    """Test detection pattern configuration."""

    def test_patterns_loaded(self):
        assert len(DETECTION_PATTERNS) >= 8
        spike_count = sum(1 for p in DETECTION_PATTERNS if p.incident_type == IncidentType.SPIKE)
        sustained_count = sum(1 for p in DETECTION_PATTERNS if p.incident_type == IncidentType.SUSTAINED)
        assert spike_count >= 4
        assert sustained_count >= 2

    def test_all_patterns_have_required_fields(self):
        for p in DETECTION_PATTERNS:
            assert p.name
            assert p.source
            assert p.start_pattern
            assert p.severity
            assert p.category

    def test_sustained_patterns_have_end(self):
        for p in DETECTION_PATTERNS:
            if p.incident_type == IncidentType.SUSTAINED:
                assert p.end_pattern is not None, f"{p.name} is sustained but has no end_pattern"


class TestMultipleIncidents:
    """Test handling multiple concurrent incidents."""

    def test_different_patterns_coexist(self, processor):
        """Different sustained incidents can be open simultaneously."""
        processor.process_event(
            source="dpkg",
            raw_line="2026-03-09 09:00:00 install pkg1 1.0 <none>",
            timestamp="2026-03-09T09:00:00",
        )
        processor.process_event(
            source="systemd",
            raw_line="Stopping some-service.service...",
            timestamp="2026-03-09T09:00:01",
        )

        assert "apt_install" in processor._open_incidents
        assert "service_restart" in processor._open_incidents

        # Close one
        processor.process_event(
            source="systemd",
            raw_line="Started some-service.service.",
            timestamp="2026-03-09T09:00:05",
        )

        assert "service_restart" not in processor._open_incidents
        assert "apt_install" in processor._open_incidents  # still open

    def test_spike_during_sustained(self, processor):
        """Spike incidents don't interfere with open sustained ones."""
        processor.process_event(
            source="dpkg",
            raw_line="2026-03-09 09:00:00 install pkg1 1.0 <none>",
            timestamp="2026-03-09T09:00:00",
        )

        # Spike during install
        processor.process_event(
            source="ssh",
            raw_line="Failed password for admin from 10.0.0.1",
            timestamp="2026-03-09T09:00:30",
        )

        # Sustained should still be open
        assert "apt_install" in processor._open_incidents

        incidents = processor._conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        assert incidents >= 2  # 1 sustained + 1 spike


class TestRealTimeAlerting:
    """Test real-time alert system."""

    def test_critical_triggers_immediate_alert(self, tmp_path):
        """Critical severity → immediate alert via callback."""
        alerts_received = []

        def on_alert(alert):
            alerts_received.append(alert)

        db = tmp_path / "alert_test.db"
        cfg = AlertConfig(enabled=True, callback=on_alert)
        proc = StreamProcessor(str(db), agent_id="test", hostname="test", alert_config=cfg)
        proc.init_db()

        proc.process_event(
            source="systemd",
            raw_line="Failed to start critical-service.service",
            timestamp="2026-03-09T09:00:00",
        )

        assert len(alerts_received) == 1
        assert alerts_received[0].severity == "critical"
        assert "service_failed" in alerts_received[0].pattern_name
        proc.close()

    def test_warning_burst_triggers_alert(self, tmp_path):
        """3 warnings in 60s → alert."""
        alerts_received = []

        def on_alert(alert):
            alerts_received.append(alert)

        db = tmp_path / "alert_test2.db"
        cfg = AlertConfig(enabled=True, callback=on_alert, warning_threshold=3, warning_window_seconds=60)
        proc = StreamProcessor(str(db), agent_id="test", hostname="test", alert_config=cfg)
        proc.init_db()

        for i in range(3):
            proc.process_event(
                source="ufw",
                raw_line=f"[UFW BLOCK] IN=eth0 SRC=1.2.3.{i} DST=5.6.7.8 PROTO=TCP DPT=22",
                timestamp=f"2026-03-09T09:00:0{i}",
            )

        # Should have triggered a warning burst alert
        warning_alerts = [a for a in alerts_received if a.severity == "warning"]
        assert len(warning_alerts) >= 1
        assert "BURST" in warning_alerts[0].title
        proc.close()

    def test_single_warning_no_alert(self, tmp_path):
        """Single warning → no alert (below threshold)."""
        alerts_received = []

        def on_alert(alert):
            alerts_received.append(alert)

        db = tmp_path / "alert_test3.db"
        cfg = AlertConfig(enabled=True, callback=on_alert, warning_threshold=3)
        proc = StreamProcessor(str(db), agent_id="test", hostname="test", alert_config=cfg)
        proc.init_db()

        proc.process_event(
            source="ufw",
            raw_line="[UFW BLOCK] IN=eth0 SRC=1.2.3.4 DST=5.6.7.8 PROTO=TCP DPT=22",
            timestamp="2026-03-09T09:00:00",
        )

        assert len(alerts_received) == 0
        proc.close()

    def test_alert_file_written(self, tmp_path):
        """Alerts are written to JSONL file."""
        alert_file = tmp_path / "alerts.jsonl"
        db = tmp_path / "alert_test4.db"
        cfg = AlertConfig(enabled=True, alert_file=str(alert_file))
        proc = StreamProcessor(str(db), agent_id="test", hostname="test", alert_config=cfg)
        proc.init_db()

        proc.process_event(
            source="systemd",
            raw_line="Failed to start some-service.service",
            timestamp="2026-03-09T09:00:00",
        )

        assert alert_file.exists()
        lines = alert_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["severity"] == "critical"
        assert "service_failed" in data["pattern"]
        proc.close()

    def test_disabled_alerting(self, tmp_path):
        """Disabled alerts → no callbacks."""
        alerts_received = []

        def on_alert(alert):
            alerts_received.append(alert)

        db = tmp_path / "alert_test5.db"
        cfg = AlertConfig(enabled=False, callback=on_alert)
        proc = StreamProcessor(str(db), agent_id="test", hostname="test", alert_config=cfg)
        proc.init_db()

        proc.process_event(
            source="systemd",
            raw_line="Failed to start something.service",
            timestamp="2026-03-09T09:00:00",
        )

        assert len(alerts_received) == 0
        proc.close()

    def test_recommended_action_included(self, tmp_path):
        """Alerts include recommended action."""
        alerts_received = []

        def on_alert(alert):
            alerts_received.append(alert)

        db = tmp_path / "alert_test6.db"
        cfg = AlertConfig(enabled=True, callback=on_alert)
        proc = StreamProcessor(str(db), agent_id="test", hostname="test", alert_config=cfg)
        proc.init_db()

        proc.process_event(
            source="ssh",
            raw_line="Failed password for root from 10.0.0.1 port 22",
            timestamp="2026-03-09T09:00:00",
        )

        # SSH failed login is warning, need burst for alert... let's use OOM instead
        proc.process_event(
            source="kernel",
            raw_line="Out of memory: Killed process 12345 (python3)",
            timestamp="2026-03-09T09:00:01",
        )

        oom_alerts = [a for a in alerts_received if "oom" in a.pattern_name]
        assert len(oom_alerts) >= 1
        assert "free -h" in oom_alerts[0].recommended_action
        proc.close()


# Need this import for timedelta in tests
from datetime import timedelta
