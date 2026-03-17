"""Tests for UAML Security Hardening."""

from __future__ import annotations

import os
import stat
import pytest
from pathlib import Path

from uaml.security.hardening import SecurityAuditor, SecurityReport, _detect_platform


class TestSecurityAuditor:
    def test_full_audit_runs(self, tmp_path):
        auditor = SecurityAuditor(data_dir=str(tmp_path))
        report = auditor.full_audit()
        assert isinstance(report, SecurityReport)
        assert report.checked_at != ""
        assert report.platform != ""

    def test_score_starts_at_100(self, tmp_path):
        report = SecurityReport()
        assert report.score() == 100

    def test_score_deductions(self):
        from uaml.security.hardening import SecurityFinding
        report = SecurityReport(findings=[
            SecurityFinding("fs", "critical", "bad", "d", "r"),
            SecurityFinding("fw", "warning", "meh", "d", "r"),
        ])
        assert report.score() == 75  # 100 - 20 - 5

    def test_summary(self, tmp_path):
        auditor = SecurityAuditor(data_dir=str(tmp_path))
        report = auditor.full_audit()
        summary = report.summary()
        assert "score" in summary
        assert "platform" in summary

    def test_to_dict(self, tmp_path):
        auditor = SecurityAuditor(data_dir=str(tmp_path))
        report = auditor.full_audit()
        d = report.to_dict()
        assert "findings" in d
        assert isinstance(d["findings"], list)

    def test_world_readable_dir(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        data.chmod(0o755)  # World-readable

        auditor = SecurityAuditor(data_dir=str(data))
        report = auditor.full_audit()
        critical = [f for f in report.findings
                    if f.severity == "critical" and "world-readable" in f.title]
        assert len(critical) >= 1

    def test_secure_dir(self, tmp_path):
        data = tmp_path / "secure"
        data.mkdir(mode=0o700)

        auditor = SecurityAuditor(data_dir=str(data))
        report = auditor.full_audit()
        fs_critical = [f for f in report.findings
                       if f.category == "filesystem" and f.severity == "critical"]
        assert len(fs_critical) == 0

    def test_world_readable_db(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir(mode=0o700)
        db = data / "test.db"
        db.write_text("fake db")
        db.chmod(0o644)  # World-readable

        auditor = SecurityAuditor(data_dir=str(data))
        report = auditor.full_audit()
        db_critical = [f for f in report.findings
                       if "world-readable" in f.title and "Database" in f.title]
        assert len(db_critical) >= 1

    def test_nonexistent_dir(self, tmp_path):
        auditor = SecurityAuditor(data_dir=str(tmp_path / "nonexistent"))
        report = auditor.full_audit()
        info = [f for f in report.findings if "does not exist" in f.title]
        assert len(info) >= 1

    def test_hardening_checklist_all(self):
        items = SecurityAuditor.hardening_checklist("all")
        assert len(items) >= 10

    def test_hardening_checklist_wsl2(self):
        items = SecurityAuditor.hardening_checklist("wsl2")
        assert all(i["platform"] in ("wsl2", "all") for i in items)
        wsl_specific = [i for i in items if i["platform"] == "wsl2"]
        assert len(wsl_specific) >= 2

    def test_hardening_checklist_macos(self):
        items = SecurityAuditor.hardening_checklist("macos")
        mac_specific = [i for i in items if i["platform"] == "macos"]
        assert len(mac_specific) >= 3

    def test_detect_platform(self):
        plat, is_wsl = _detect_platform()
        assert plat in ("linux", "wsl2", "darwin", "windows")

    def test_report_categories(self):
        from uaml.security.hardening import SecurityFinding
        report = SecurityReport(findings=[
            SecurityFinding("fs", "critical", "A", "d", "r"),
            SecurityFinding("fw", "warning", "B", "d", "r"),
            SecurityFinding("log", "info", "C", "d", "r"),
        ])
        assert len(report.critical()) == 1
        assert len(report.warnings()) == 1
        assert len(report.info()) == 1
