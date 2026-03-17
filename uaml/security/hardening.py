# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Security Hardening — OS-level audit and sandboxing.

Checks filesystem permissions, firewall status, logging config,
and provides platform-specific hardening for Linux, WSL2, and macOS.

Usage:
    from uaml.security.hardening import SecurityAuditor

    auditor = SecurityAuditor(data_dir="/path/to/uaml/data")
    report = auditor.full_audit()
    print(report.summary())
"""

from __future__ import annotations

import os
import sys
import stat
import platform
import subprocess
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SecurityFinding:
    """A single security finding."""
    category: str  # filesystem, firewall, logging, network, permissions
    severity: str  # critical, warning, info
    title: str
    detail: str
    recommendation: str
    platform: str = "all"  # linux, wsl2, macos, all


@dataclass
class SecurityReport:
    """Complete security audit report."""
    findings: list[SecurityFinding] = field(default_factory=list)
    platform: str = ""
    is_wsl2: bool = False
    data_dir: str = ""
    checked_at: str = ""

    def critical(self) -> list[SecurityFinding]:
        return [f for f in self.findings if f.severity == "critical"]

    def warnings(self) -> list[SecurityFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    def info(self) -> list[SecurityFinding]:
        return [f for f in self.findings if f.severity == "info"]

    def score(self) -> int:
        """Security score 0-100. Deductions: critical=-20, warning=-5."""
        s = 100
        s -= len(self.critical()) * 20
        s -= len(self.warnings()) * 5
        return max(0, s)

    def summary(self) -> dict:
        return {
            "score": self.score(),
            "platform": self.platform,
            "is_wsl2": self.is_wsl2,
            "data_dir": self.data_dir,
            "total_findings": len(self.findings),
            "critical": len(self.critical()),
            "warnings": len(self.warnings()),
            "info": len(self.info()),
        }

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "title": f.title,
                    "detail": f.detail,
                    "recommendation": f.recommendation,
                }
                for f in self.findings
            ],
        }


def _detect_platform() -> tuple[str, bool]:
    """Detect OS platform and WSL2."""
    system = platform.system().lower()
    is_wsl2 = False

    if system == "linux":
        try:
            with open("/proc/version", "r") as f:
                version_str = f.read().lower()
                if "microsoft" in version_str or "wsl" in version_str:
                    is_wsl2 = True
        except (OSError, IOError):
            pass

    if is_wsl2:
        return "wsl2", True
    return system, False


def _run_cmd(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    """Run a command and return (returncode, output)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout + result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


class SecurityAuditor:
    """Audit and recommend security hardening for UAML deployments."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir) if data_dir else Path.cwd()
        self.platform, self.is_wsl2 = _detect_platform()

    def full_audit(self) -> SecurityReport:
        """Run all security checks."""
        from datetime import datetime, timezone

        report = SecurityReport(
            platform=self.platform,
            is_wsl2=self.is_wsl2,
            data_dir=str(self.data_dir),
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

        self._check_filesystem(report)
        self._check_db_permissions(report)
        self._check_firewall(report)
        self._check_logging(report)
        self._check_network(report)

        if self.is_wsl2:
            self._check_wsl2_specific(report)
        elif self.platform == "darwin":
            self._check_macos_specific(report)

        return report

    def _check_filesystem(self, report: SecurityReport) -> None:
        """Check filesystem permissions on data directory."""
        if not self.data_dir.exists():
            report.findings.append(SecurityFinding(
                category="filesystem",
                severity="info",
                title="Data directory does not exist",
                detail=f"Path: {self.data_dir}",
                recommendation="Create the data directory with restricted permissions: chmod 700",
            ))
            return

        # Check directory permissions
        dir_stat = self.data_dir.stat()
        mode = dir_stat.st_mode

        # Check if world-readable
        if mode & stat.S_IROTH:
            report.findings.append(SecurityFinding(
                category="filesystem",
                severity="critical",
                title="Data directory is world-readable",
                detail=f"{self.data_dir} has permissions {oct(mode)[-3:]}",
                recommendation="Run: chmod 700 " + str(self.data_dir),
            ))

        # Check if group-writable
        if mode & stat.S_IWGRP:
            report.findings.append(SecurityFinding(
                category="filesystem",
                severity="warning",
                title="Data directory is group-writable",
                detail=f"{self.data_dir} has permissions {oct(mode)[-3:]}",
                recommendation="Run: chmod 700 " + str(self.data_dir),
            ))

        # Check owner
        if os.getuid() != dir_stat.st_uid:
            report.findings.append(SecurityFinding(
                category="filesystem",
                severity="warning",
                title="Data directory owned by different user",
                detail=f"Current UID: {os.getuid()}, Dir UID: {dir_stat.st_uid}",
                recommendation="Run: chown $(whoami) " + str(self.data_dir),
            ))

    def _check_db_permissions(self, report: SecurityReport) -> None:
        """Check permissions on database files."""
        db_files = list(self.data_dir.glob("**/*.db"))

        for db_path in db_files:
            try:
                mode = db_path.stat().st_mode
                if mode & stat.S_IROTH:
                    report.findings.append(SecurityFinding(
                        category="filesystem",
                        severity="critical",
                        title=f"Database file world-readable: {db_path.name}",
                        detail=f"{db_path} has permissions {oct(mode)[-3:]}",
                        recommendation=f"Run: chmod 600 {db_path}",
                    ))
            except OSError:
                pass

        if not db_files:
            report.findings.append(SecurityFinding(
                category="filesystem",
                severity="info",
                title="No database files found",
                detail=f"Searched in {self.data_dir}",
                recommendation="This is normal for a fresh installation",
            ))

    def _check_firewall(self, report: SecurityReport) -> None:
        """Check firewall status."""
        if self.platform in ("linux", "wsl2"):
            # Check ufw
            rc, output = _run_cmd(["ufw", "status"])
            if rc == 0:
                if "inactive" in output.lower():
                    report.findings.append(SecurityFinding(
                        category="firewall",
                        severity="warning",
                        title="UFW firewall is inactive",
                        detail="Uncomplicated Firewall is installed but not active",
                        recommendation="Run: sudo ufw enable && sudo ufw default deny incoming",
                        platform="linux",
                    ))
                elif "active" in output.lower():
                    report.findings.append(SecurityFinding(
                        category="firewall",
                        severity="info",
                        title="UFW firewall is active",
                        detail=output[:200],
                        recommendation="Good. Verify rules with: sudo ufw status verbose",
                        platform="linux",
                    ))
            else:
                # Check iptables
                rc, output = _run_cmd(["iptables", "-L", "-n"])
                if rc == 0 and "ACCEPT" in output:
                    report.findings.append(SecurityFinding(
                        category="firewall",
                        severity="info",
                        title="iptables rules present",
                        detail="Firewall rules found via iptables",
                        recommendation="Review rules with: sudo iptables -L -n -v",
                        platform="linux",
                    ))
                else:
                    report.findings.append(SecurityFinding(
                        category="firewall",
                        severity="warning",
                        title="No firewall detected",
                        detail="Neither ufw nor iptables rules found",
                        recommendation="Install and enable ufw: sudo apt install ufw && sudo ufw enable",
                        platform="linux",
                    ))

        elif self.platform == "darwin":
            rc, output = _run_cmd(["defaults", "read",
                                    "/Library/Preferences/com.apple.alf", "globalstate"])
            if rc == 0:
                state = output.strip()
                if state == "0":
                    report.findings.append(SecurityFinding(
                        category="firewall",
                        severity="warning",
                        title="macOS firewall is disabled",
                        detail="Application Firewall is not active",
                        recommendation="Enable in System Settings → Network → Firewall",
                        platform="macos",
                    ))
                else:
                    report.findings.append(SecurityFinding(
                        category="firewall",
                        severity="info",
                        title="macOS firewall is enabled",
                        detail=f"Firewall state: {state}",
                        recommendation="Good. Review settings in System Settings → Network → Firewall",
                        platform="macos",
                    ))

    def _check_logging(self, report: SecurityReport) -> None:
        """Check that audit logging is properly configured."""
        # Check if audit log DB exists
        audit_db = self.data_dir / "audit_log.db"
        if not audit_db.exists():
            # Check common locations
            for candidate in [
                self.data_dir / "data" / "audit_log.db",
                self.data_dir.parent / "data" / "audit_log.db",
            ]:
                if candidate.exists():
                    audit_db = candidate
                    break

        if audit_db.exists():
            report.findings.append(SecurityFinding(
                category="logging",
                severity="info",
                title="Audit log database found",
                detail=f"Path: {audit_db}",
                recommendation="Ensure regular backups and log rotation",
            ))
        else:
            report.findings.append(SecurityFinding(
                category="logging",
                severity="warning",
                title="No audit log database found",
                detail="UAML audit trail may not be active",
                recommendation="Enable audit logging in UAML configuration",
            ))

    def _check_network(self, report: SecurityReport) -> None:
        """Check for exposed network services."""
        if self.platform in ("linux", "wsl2"):
            rc, output = _run_cmd(["ss", "-tlnp"])
            if rc == 0:
                # Check for UAML/MCP ports listening on 0.0.0.0
                for line in output.splitlines():
                    if "0.0.0.0" in line and any(p in line for p in [":8080", ":5000", ":3000"]):
                        report.findings.append(SecurityFinding(
                            category="network",
                            severity="warning",
                            title="Service listening on all interfaces",
                            detail=line.strip(),
                            recommendation="Bind to 127.0.0.1 instead of 0.0.0.0 for local-only access",
                        ))

    def _check_wsl2_specific(self, report: SecurityReport) -> None:
        """WSL2-specific security checks."""
        # Check /mnt/c permissions (Windows filesystem)
        mnt_c = Path("/mnt/c")
        if mnt_c.exists():
            # Data should NOT be on Windows mount
            if str(self.data_dir).startswith("/mnt/"):
                report.findings.append(SecurityFinding(
                    category="filesystem",
                    severity="critical",
                    title="UAML data on Windows filesystem mount",
                    detail=f"Data dir {self.data_dir} is on /mnt/ — Windows filesystem has different permission model",
                    recommendation="Move data to Linux filesystem: ~/uaml-data/ or /home/$USER/.uaml/",
                    platform="wsl2",
                ))

            # Check wsl.conf for automount options
            wsl_conf = Path("/etc/wsl.conf")
            if wsl_conf.exists():
                try:
                    content = wsl_conf.read_text()
                    if "metadata" not in content:
                        report.findings.append(SecurityFinding(
                            category="filesystem",
                            severity="warning",
                            title="WSL2 metadata mount option not set",
                            detail="Without metadata, Linux permissions on /mnt/* are not enforced",
                            recommendation='Add to /etc/wsl.conf under [automount]: options = "metadata,umask=22,fmask=11"',
                            platform="wsl2",
                        ))
                except OSError:
                    pass
            else:
                report.findings.append(SecurityFinding(
                    category="filesystem",
                    severity="info",
                    title="No /etc/wsl.conf found",
                    detail="WSL2 uses default mount options",
                    recommendation='Create /etc/wsl.conf with [automount] options = "metadata,umask=22,fmask=11"',
                    platform="wsl2",
                ))

        # Check Windows Defender firewall awareness
        report.findings.append(SecurityFinding(
            category="firewall",
            severity="info",
            title="WSL2 network: NAT behind Windows",
            detail="WSL2 uses NAT networking — Windows Firewall controls inbound access",
            recommendation="Ensure Windows Firewall blocks inbound to WSL2 ports. Check: netsh advfirewall show allprofiles",
            platform="wsl2",
        ))

    def _check_macos_specific(self, report: SecurityReport) -> None:
        """macOS-specific security checks."""
        # Check Gatekeeper
        rc, output = _run_cmd(["spctl", "--status"])
        if rc == 0 and "disabled" in output.lower():
            report.findings.append(SecurityFinding(
                category="permissions",
                severity="warning",
                title="macOS Gatekeeper is disabled",
                detail="App execution is not restricted",
                recommendation="Enable: sudo spctl --master-enable",
                platform="macos",
            ))

        # Check SIP
        rc, output = _run_cmd(["csrutil", "status"])
        if rc == 0 and "disabled" in output.lower():
            report.findings.append(SecurityFinding(
                category="permissions",
                severity="critical",
                title="System Integrity Protection (SIP) is disabled",
                detail="macOS system protection is off",
                recommendation="Re-enable SIP from Recovery Mode: csrutil enable",
                platform="macos",
            ))

        # Check Full Disk Access
        report.findings.append(SecurityFinding(
            category="permissions",
            severity="info",
            title="macOS: Verify app permissions",
            detail="UAML should have minimal system permissions",
            recommendation="Check System Settings → Privacy & Security → Full Disk Access — remove UAML if listed",
            platform="macos",
        ))

    @staticmethod
    def hardening_checklist(platform_name: str = "all") -> list[dict]:
        """Get a platform-specific hardening checklist."""
        items = [
            {"step": "Set data directory permissions to 700", "cmd": "chmod 700 /path/to/uaml/data", "platform": "all"},
            {"step": "Set database file permissions to 600", "cmd": "chmod 600 /path/to/uaml/data/*.db", "platform": "all"},
            {"step": "Enable audit logging", "cmd": "uaml config set audit.enabled true", "platform": "all"},
            {"step": "Bind services to localhost only", "cmd": "uaml config set server.host 127.0.0.1", "platform": "all"},
            {"step": "Enable encryption at rest", "cmd": "uaml config set crypto.enabled true", "platform": "all"},
            {"step": "Enable UFW firewall", "cmd": "sudo ufw enable && sudo ufw default deny incoming", "platform": "linux"},
            {"step": "Store data on Linux filesystem (not /mnt/)", "cmd": "mv data ~/uaml-data/", "platform": "wsl2"},
            {"step": "Configure wsl.conf metadata", "cmd": 'echo \'[automount]\\noptions = "metadata"\\n\' | sudo tee /etc/wsl.conf', "platform": "wsl2"},
            {"step": "Enable macOS firewall", "cmd": "System Settings → Network → Firewall → Enable", "platform": "macos"},
            {"step": "Verify SIP is enabled", "cmd": "csrutil status", "platform": "macos"},
            {"step": "Review Full Disk Access", "cmd": "System Settings → Privacy & Security → Full Disk Access", "platform": "macos"},
            {"step": "Set up log rotation", "cmd": "uaml config set logging.max_size_mb 100", "platform": "all"},
            {"step": "Regular security audit", "cmd": "uaml security audit", "platform": "all"},
        ]

        if platform_name == "all":
            return items
        return [i for i in items if i["platform"] in (platform_name, "all")]
