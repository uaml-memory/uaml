# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Security Configurator — generate platform-specific security commands.

Generates firewall rules, antivirus exclusions, WSL2 configuration,
BitLocker setup, and network profile commands. NEVER executes them —
the user copies and runs manually.

Usage:
    from uaml.security.configurator import SecurityConfigurator

    config = SecurityConfigurator()
    commands = config.firewall_rules(ports=[8780, 8785], allow_from="lan")
    for cmd in commands:
        print(cmd.command)  # User copies and runs

Web UI:
    config.serve(port=8785)  # Opens wizard on localhost

CLI:
    config.cli_wizard()  # Interactive terminal wizard
"""

from __future__ import annotations

import os
import sys
import json
import time
import platform
import subprocess
import logging
import threading
import sqlite3
import stat as stat_module
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urlparse, parse_qs

try:
    import grp
    import pwd
    _HAS_POSIX_USERS = True
except ImportError:
    _HAS_POSIX_USERS = False

logger = logging.getLogger(__name__)


class Platform(Enum):
    """Detected platform."""
    LINUX = "linux"
    WSL2 = "wsl2"
    MACOS = "macos"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


class CommandCategory(Enum):
    """Category of generated command."""
    FIREWALL = "firewall"
    ANTIVIRUS = "antivirus"
    DIRECTORY_EXCLUSION = "directory_exclusion"
    WSL2_CONFIG = "wsl2_config"
    BITLOCKER = "bitlocker"
    NETWORK_PROFILE = "network_profile"
    FILESYSTEM = "filesystem"
    ENCRYPTION = "encryption"


class RiskLevel(Enum):
    """Risk level of applying the command."""
    LOW = "low"          # Safe, standard hardening
    MEDIUM = "medium"    # Changes system behavior
    HIGH = "high"        # Could lock out access if misconfigured


@dataclass
class GeneratedCommand:
    """A command generated for the user to run manually."""
    category: CommandCategory
    platform: Platform
    title: str
    description: str
    command: str
    risk: RiskLevel = RiskLevel.LOW
    requires_admin: bool = False
    notes: str = ""
    order: int = 0

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "platform": self.platform.value,
            "title": self.title,
            "description": self.description,
            "command": self.command,
            "risk": self.risk.value,
            "requires_admin": self.requires_admin,
            "notes": self.notes,
            "order": self.order,
        }


@dataclass
class ConfigProfile:
    """A saved security configuration profile."""
    name: str
    platform: Platform
    ports: list[int] = field(default_factory=list)
    allowed_ips: list[str] = field(default_factory=list)
    exclude_dirs: list[str] = field(default_factory=list)
    enable_bitlocker: bool = False
    network_profile: str = "private"
    wsl2_interop: bool = True
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "platform": self.platform.value,
            "ports": self.ports,
            "allowed_ips": self.allowed_ips,
            "exclude_dirs": self.exclude_dirs,
            "enable_bitlocker": self.enable_bitlocker,
            "network_profile": self.network_profile,
            "wsl2_interop": self.wsl2_interop,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConfigProfile:
        data = dict(data)
        data["platform"] = Platform(data.get("platform", "unknown"))
        return cls(**data)


class ExpertAccessLevel(Enum):
    """Level of AI agent access in Expert Mode."""
    NONE = "none"           # Default — no AI access
    DIAGNOSTIC = "diagnostic"  # Read-only commands (ls, cat, systemctl status, ufw status)
    REPAIR = "repair"       # Can modify system (ufw allow, chmod, etc.)


@dataclass
class ExpertCommand:
    """A command executed by AI agent during Expert Mode session."""
    command: str
    timestamp: str
    approved: bool = False
    executed: bool = False
    result: str = ""
    returncode: int = -1
    risk: RiskLevel = RiskLevel.LOW
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "timestamp": self.timestamp,
            "approved": self.approved,
            "executed": self.executed,
            "result": self.result[:2000],
            "returncode": self.returncode,
            "risk": self.risk.value,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


@dataclass
class ExpertSession:
    """A time-limited AI expert access session."""
    session_id: str
    started_at: str
    expires_at: str
    access_level: ExpertAccessLevel
    active: bool = True
    commands: list[ExpertCommand] = field(default_factory=list)
    reason: str = ""

    def is_expired(self) -> bool:
        now = datetime.now().isoformat()
        return now >= self.expires_at

    def remaining_seconds(self) -> int:
        expires = datetime.fromisoformat(self.expires_at)
        remaining = (expires - datetime.now()).total_seconds()
        return max(0, int(remaining))

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "expires_at": self.expires_at,
            "access_level": self.access_level.value,
            "active": self.active and not self.is_expired(),
            "remaining_seconds": self.remaining_seconds(),
            "commands_total": len(self.commands),
            "commands_executed": sum(1 for c in self.commands if c.executed),
            "commands_blocked": sum(1 for c in self.commands if c.blocked),
            "reason": self.reason,
            "commands": [c.to_dict() for c in self.commands],
        }


class ExpertMode:
    """Manages temporary AI agent access to the host system.

    Security model:
    - Time-limited sessions (default 15 min, max 60 min)
    - Command whitelist per access level
    - Full audit trail
    - User approval for dangerous commands
    - Kill switch always available
    """

    # Diagnostic-only commands (read-only, safe)
    DIAGNOSTIC_WHITELIST = [
        "ls", "cat", "head", "tail", "grep", "find", "stat", "file",
        "ufw status", "iptables -L", "iptables -S",
        "systemctl status", "systemctl list-units",
        "ss -tlnp", "netstat -tlnp", "ip addr", "ip route",
        "df -h", "free -h", "uptime", "whoami", "id",
        "ps aux", "top -bn1", "lsof -i", "nmap localhost",
        "ping -c", "dig", "nslookup", "curl -I",
        "Get-NetFirewallRule", "Get-NetConnectionProfile",
        "Get-MpPreference", "Get-MpComputerStatus",
        "wsl --list", "wsl --status",
        "sysctl", "dmesg | tail",
    ]

    # Repair commands (can modify system — require approval)
    REPAIR_WHITELIST = DIAGNOSTIC_WHITELIST + [
        "ufw allow", "ufw deny", "ufw delete", "ufw enable",
        "chmod", "chown", "mkdir -p",
        "systemctl start", "systemctl stop", "systemctl restart",
        "Add-MpPreference", "Remove-MpPreference",
        "New-NetFirewallRule", "Remove-NetFirewallRule",
        "Set-NetConnectionProfile",
        "tee /etc/wsl.conf",
    ]

    # Always blocked — never allow
    BLOCKED_COMMANDS = [
        "rm -rf /", "mkfs", "dd if=", "format",
        "passwd", "useradd", "userdel", "usermod",
        "shutdown", "reboot", "init 0", "halt",
        "curl | bash", "wget | bash",  # Remote code execution
    ]

    def __init__(self):
        self._sessions: list[ExpertSession] = []
        self._current_session: ExpertSession | None = None
        self._approval_callback: Callable[[str], bool] | None = None
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        """Check if there's an active, non-expired session."""
        if self._current_session is None:
            return False
        if self._current_session.is_expired():
            self._current_session.active = False
            return False
        return self._current_session.active

    @property
    def current_session(self) -> ExpertSession | None:
        if self.is_active:
            return self._current_session
        return None

    def start_session(
        self,
        duration_minutes: int = 15,
        access_level: ExpertAccessLevel = ExpertAccessLevel.DIAGNOSTIC,
        reason: str = "",
    ) -> ExpertSession:
        """Start a new expert access session.

        Args:
            duration_minutes: Session duration (1-60 minutes).
            access_level: DIAGNOSTIC (read-only) or REPAIR (can modify).
            reason: Why the session is being started.
        """
        if self.is_active:
            raise RuntimeError("An active Expert session is already running. Stop it first.")

        duration_minutes = max(1, min(60, duration_minutes))

        now = datetime.now()
        session = ExpertSession(
            session_id=f"expert-{now.strftime('%Y%m%d-%H%M%S')}",
            started_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=duration_minutes)).isoformat(),
            access_level=access_level,
            reason=reason,
        )

        with self._lock:
            self._current_session = session
            self._sessions.append(session)

        logger.info(
            f"Expert session started: {session.session_id}, "
            f"level={access_level.value}, duration={duration_minutes}min, "
            f"reason={reason}"
        )
        return session

    def stop_session(self) -> ExpertSession | None:
        """Stop the current expert session (kill switch)."""
        with self._lock:
            if self._current_session:
                self._current_session.active = False
                session = self._current_session
                self._current_session = None
                logger.info(f"Expert session stopped: {session.session_id}")
                return session
        return None

    def execute(self, command: str, auto_approve_low_risk: bool = True) -> ExpertCommand:
        """Execute a command in the expert session.

        Args:
            command: Command to execute.
            auto_approve_low_risk: Automatically approve low-risk diagnostic commands.
        """
        if not self.is_active:
            raise RuntimeError("No active Expert session.")

        session = self._current_session
        now = datetime.now().isoformat()

        # Check blocked commands
        cmd_lower = command.lower().strip()
        for blocked in self.BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                entry = ExpertCommand(
                    command=command,
                    timestamp=now,
                    blocked=True,
                    block_reason=f"Blocked command: contains '{blocked}'",
                    risk=RiskLevel.HIGH,
                )
                session.commands.append(entry)
                logger.warning(f"Expert: BLOCKED command: {command}")
                return entry

        # Determine risk and check whitelist
        risk = self._assess_risk(command)
        whitelist = (
            self.REPAIR_WHITELIST
            if session.access_level == ExpertAccessLevel.REPAIR
            else self.DIAGNOSTIC_WHITELIST
        )

        is_whitelisted = any(
            cmd_lower.startswith(w.lower()) for w in whitelist
        )

        if not is_whitelisted:
            entry = ExpertCommand(
                command=command,
                timestamp=now,
                blocked=True,
                block_reason=f"Command is not whitelisted for level '{session.access_level.value}'",
                risk=risk,
            )
            session.commands.append(entry)
            logger.warning(f"Expert: NOT WHITELISTED: {command}")
            return entry

        # Approval logic
        needs_approval = (
            risk in (RiskLevel.MEDIUM, RiskLevel.HIGH)
            or not auto_approve_low_risk
        )

        entry = ExpertCommand(
            command=command,
            timestamp=now,
            risk=risk,
        )

        if needs_approval:
            if self._approval_callback:
                entry.approved = self._approval_callback(command)
            else:
                entry.approved = False
                entry.blocked = True
                entry.block_reason = "Requires user approval (no approval callback set)"
                session.commands.append(entry)
                return entry
        else:
            entry.approved = True

        if not entry.approved:
            entry.blocked = True
            entry.block_reason = "User rejected command"
            session.commands.append(entry)
            return entry

        # Execute
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            entry.executed = True
            entry.result = (result.stdout + result.stderr)[:5000]
            entry.returncode = result.returncode
        except subprocess.TimeoutExpired:
            entry.executed = True
            entry.result = "Timeout (30s)"
            entry.returncode = -1
        except Exception as e:
            entry.result = f"Error: {e}"
            entry.returncode = -1

        session.commands.append(entry)
        logger.info(
            f"Expert: executed '{command}' → code={entry.returncode}"
        )
        return entry

    def set_approval_callback(self, callback: Callable[[str], bool]):
        """Set a callback for approving commands. Called with command string, returns bool."""
        self._approval_callback = callback

    def get_audit_trail(self) -> list[dict]:
        """Get complete audit trail of all sessions."""
        return [s.to_dict() for s in self._sessions]

    def _assess_risk(self, command: str) -> RiskLevel:
        """Assess risk level of a command."""
        cmd = command.lower().strip()

        high_risk = ["ufw enable", "ufw delete", "chmod 777", "systemctl stop",
                      "Remove-NetFirewallRule", "Enable-BitLocker"]
        medium_risk = ["ufw allow", "ufw deny", "chmod", "chown",
                       "systemctl restart", "Add-MpPreference", "New-NetFirewallRule",
                       "Set-NetConnectionProfile", "tee /etc/"]

        for h in high_risk:
            if h.lower() in cmd:
                return RiskLevel.HIGH
        for m in medium_risk:
            if m.lower() in cmd:
                return RiskLevel.MEDIUM
        return RiskLevel.LOW


class SecurityConfigurator:
    """Generates security configuration commands for manual execution.

    IMPORTANT: This tool NEVER executes commands. It only generates
    them for the user to review and run manually.
    """

    # Default UAML ports
    DEFAULT_PORTS = {
        "api": 8780,
        "dashboard": 8781,
        "security_dashboard": 8785,
    }

    # Default directories to exclude from antivirus
    DEFAULT_EXCLUDE_DIRS = [
        "~/.uaml",
        "~/.openclaw",
    ]

    def __init__(self, data_dir: str | None = None):
        self._platform = self._detect_platform()
        self._data_dir = data_dir or str(Path.home() / ".uaml")
        self._profiles: list[ConfigProfile] = []
        self._expert = ExpertMode()
        self._execution_log: list[dict] = []

    @property
    def platform(self) -> Platform:
        return self._platform

    @property
    def expert(self) -> ExpertMode:
        """Access the Expert Mode manager."""
        return self._expert

    @property
    def execution_log(self) -> list[dict]:
        """Get the execution history log."""
        return list(self._execution_log)

    def log_execution(self, command: str, title: str, success: bool,
                      returncode: int, output: str, risk: str = "low",
                      requires_admin: bool = False):
        """Log a command execution for audit trail."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "title": title,
            "success": success,
            "returncode": returncode,
            "output": output[:5000],
            "risk": risk,
            "requires_admin": requires_admin,
            "platform": self._platform.value,
            "executor": "user",  # Always user, never AI (unless Expert Mode)
        }
        self._execution_log.append(entry)
        return entry

    def generate_report(self, format: str = "html") -> str:
        """Generate an audit report of all executed commands.

        Args:
            format: "html" for printable report, "json" for machine-readable.
        """
        if format == "json":
            return json.dumps({
                "report": "UAML Security Configurator — Execution Report",
                "generated_at": datetime.now().isoformat(),
                "platform": self._platform.value,
                "total_commands": len(self._execution_log),
                "successful": sum(1 for e in self._execution_log if e["success"]),
                "failed": sum(1 for e in self._execution_log if not e["success"]),
                "executions": self._execution_log,
            }, indent=2, ensure_ascii=False)

        # HTML report
        rows = ""
        for i, e in enumerate(self._execution_log, 1):
            status = "✅" if e["success"] else "❌"
            risk_icon = {"low": "🟢", "medium": "🟠", "high": "🔴"}.get(e["risk"], "⚪")
            ts = e["timestamp"][:19].replace("T", " ")
            rows += f"""<tr>
                <td>{i}</td>
                <td>{ts}</td>
                <td>{risk_icon} {e['title']}</td>
                <td><code>{e['command'][:80]}</code></td>
                <td>{status} (code {e['returncode']})</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;">{e['output'][:100]}</td>
            </tr>"""

        total = len(self._execution_log)
        ok = sum(1 for e in self._execution_log if e["success"])
        fail = total - ok
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>UAML Security Report — {now}</title>
<style>
    body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 24px; color: #1a1a2e; }}
    h1 {{ border-bottom: 3px solid #6366f1; padding-bottom: 12px; }}
    .meta {{ color: #666; margin-bottom: 24px; }}
    .summary {{ display: flex; gap: 24px; margin: 24px 0; }}
    .stat {{ background: #f5f5ff; padding: 16px 24px; border-radius: 12px; text-align: center; flex: 1; }}
    .stat .num {{ font-size: 2rem; font-weight: 800; color: #6366f1; }}
    .stat .label {{ color: #666; font-size: 0.85rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th {{ background: #6366f1; color: white; padding: 10px; text-align: left; font-size: 0.85rem; }}
    td {{ padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 0.85rem; }}
    tr:hover {{ background: #f5f5ff; }}
    code {{ background: #f0f0f5; padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; }}
    .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; color: #999; font-size: 0.8rem; text-align: center; }}
    @media print {{ body {{ margin: 0; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>
<h1>🛡️ UAML Security Configurator — Report</h1>
<div class="meta">
    <p><strong>Date:</strong> {now}</p>
    <p><strong>Platform:</strong> {self._platform.value}</p>
    <p><strong>Generated by:</strong> UAML Security Configurator v1.0</p>
</div>

<div class="summary">
    <div class="stat"><div class="num">{total}</div><div class="label">Total commands</div></div>
    <div class="stat"><div class="num" style="color:#22c55e;">{ok}</div><div class="label">Passed</div></div>
    <div class="stat"><div class="num" style="color:#ef4444;">{fail}</div><div class="label">Failed</div></div>
</div>

<table>
<thead><tr><th>#</th><th>Time</th><th>Action</th><th>Command</th><th>Result</th><th>Output</th></tr></thead>
<tbody>{rows}</tbody>
</table>

<div class="footer">
    <p>© 2026 GLG, a.s. — UAML Security Configurator</p>
    <p>This report was auto-generated. All commands were executed by the user.</p>
</div>
</body>
</html>"""

    def _detect_platform(self) -> Platform:
        """Auto-detect the current platform."""
        system = platform.system().lower()
        if system == "linux":
            # Check for WSL2
            try:
                with open("/proc/version", "r") as f:
                    version = f.read().lower()
                if "microsoft" in version or "wsl" in version:
                    return Platform.WSL2
            except (FileNotFoundError, PermissionError):
                pass
            return Platform.LINUX
        elif system == "darwin":
            return Platform.MACOS
        elif system == "windows":
            return Platform.WINDOWS
        return Platform.UNKNOWN

    # ── Firewall Rules ──────────────────────────────────────────────

    def firewall_rules(
        self,
        ports: list[int] | None = None,
        allow_from: str = "localhost",
        direction: str = "inbound",
    ) -> list[GeneratedCommand]:
        """Generate firewall rules for UAML ports.

        Args:
            ports: List of ports to configure. Defaults to UAML standard ports.
            allow_from: "localhost", "lan", or specific IP/CIDR.
            direction: "inbound" or "outbound".
        """
        if ports is None:
            ports = list(self.DEFAULT_PORTS.values())

        commands = []
        p = self._platform

        if p in (Platform.LINUX, Platform.WSL2):
            commands.extend(self._linux_firewall(ports, allow_from, direction))
        elif p == Platform.MACOS:
            commands.extend(self._macos_firewall(ports, allow_from))
        elif p == Platform.WINDOWS:
            commands.extend(self._windows_firewall(ports, allow_from, direction))

        if p == Platform.WSL2:
            commands.extend(self._wsl2_firewall_extra(ports, allow_from))

        return commands

    def _linux_firewall(
        self, ports: list[int], allow_from: str, direction: str
    ) -> list[GeneratedCommand]:
        commands = []
        # Check if UFW is available
        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=self._platform,
            title="Activate UFW firewall",
            description="Enable UFW firewall with default deny incoming rule.",
            command="sudo ufw default deny incoming\nsudo ufw default allow outgoing\nsudo ufw enable",
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            notes="Warning: if connected via SSH, allow SSH port (22) first.",
            order=1,
        ))

        # SSH rule first
        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=self._platform,
            title="Allow SSH (port 22)",
            description="Allow SSH access to prevent remote lockout.",
            command="sudo ufw allow 22/tcp",
            risk=RiskLevel.LOW,
            requires_admin=True,
            order=2,
        ))

        source = self._resolve_source(allow_from)
        for port in ports:
            if source:
                cmd = f"sudo ufw allow from {source} to any port {port} proto tcp"
            else:
                cmd = f"sudo ufw allow {port}/tcp"

            commands.append(GeneratedCommand(
                category=CommandCategory.FIREWALL,
                platform=self._platform,
                title=f"Allow port {port}/tcp",
                description=f"Allow incoming TCP connections on port {port} ({self._port_label(port)}).",
                command=cmd,
                risk=RiskLevel.LOW,
                requires_admin=True,
                order=10 + port,
            ))

        # iptables alternative
        ipt_rules = []
        for port in ports:
            if source:
                ipt_rules.append(
                    f"sudo iptables -A INPUT -p tcp -s {source} --dport {port} -j ACCEPT"
                )
            else:
                ipt_rules.append(
                    f"sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT"
                )
        ipt_rules.append("sudo iptables -A INPUT -j DROP")

        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=self._platform,
            title="Alternative: iptables rules",
            description="If you do not use UFW, you can use iptables directly.",
            command="\n".join(ipt_rules),
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            notes="These commands are not persistent — they disappear after reboot. Use iptables-persistent for permanent storage.",
            order=100,
        ))

        return commands

    def _macos_firewall(
        self, ports: list[int], allow_from: str
    ) -> list[GeneratedCommand]:
        commands = []

        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=Platform.MACOS,
            title="Zapnout macOS Application Firewall",
            description="Enable the built-in macOS firewall.",
            command="sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on",
            risk=RiskLevel.LOW,
            requires_admin=True,
            order=1,
        ))

        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=Platform.MACOS,
            title="Zapnout Stealth Mode",
            description="Stealth mode — Mac does not respond to ping and port scans.",
            command="sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on",
            risk=RiskLevel.LOW,
            requires_admin=True,
            order=2,
        ))

        # pf rules for specific ports
        pf_rules = ["# UAML pf rules — add to /etc/pf.conf"]
        source = self._resolve_source(allow_from)
        for port in ports:
            if source:
                pf_rules.append(f"pass in on en0 proto tcp from {source} to any port {port}")
            else:
                pf_rules.append(f"pass in on en0 proto tcp from any to any port {port}")

        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=Platform.MACOS,
            title="PF rules for UAML ports",
            description="Packet filter rules to allow UAML ports.",
            command="\n".join(pf_rules) + "\n\n# Aplikovat:\nsudo pfctl -f /etc/pf.conf\nsudo pfctl -e",
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            notes="Back up /etc/pf.conf before editing.",
            order=10,
        ))

        return commands

    def _windows_firewall(
        self, ports: list[int], allow_from: str, direction: str
    ) -> list[GeneratedCommand]:
        commands = []
        dir_param = "Inbound" if direction == "inbound" else "Outbound"

        for port in ports:
            label = self._port_label(port)
            cmd = (
                f'New-NetFirewallRule -DisplayName "UAML {label} (port {port})" '
                f'-Direction {dir_param} -Protocol TCP -LocalPort {port} -Action Allow'
            )
            if allow_from == "localhost":
                cmd += ' -RemoteAddress "127.0.0.1"'
            elif allow_from == "lan":
                cmd += ' -RemoteAddress "LocalSubnet"'
            elif allow_from != "any":
                cmd += f' -RemoteAddress "{allow_from}"'

            commands.append(GeneratedCommand(
                category=CommandCategory.FIREWALL,
                platform=Platform.WINDOWS,
                title=f"Povolit port {port}/tcp ({label})",
                description=f"Windows Firewall rule for UAML {label}.",
                command=cmd,
                risk=RiskLevel.LOW,
                requires_admin=True,
                notes="Run in PowerShell as Administrator.",
                order=10 + port,
            ))

        return commands

    def _wsl2_firewall_extra(
        self, ports: list[int], allow_from: str
    ) -> list[GeneratedCommand]:
        """Extra firewall commands specific to WSL2."""
        commands = []

        # Port forwarding from Windows to WSL2
        forward_cmds = ["# PowerShell (Windows) — port forwarding do WSL2"]
        for port in ports:
            forward_cmds.append(
                f"netsh interface portproxy add v4tov4 "
                f"listenport={port} listenaddress=0.0.0.0 "
                f"connectport={port} connectaddress=$(wsl hostname -I | ForEach-Object {{ $_.Trim() }})"
            )

        commands.append(GeneratedCommand(
            category=CommandCategory.FIREWALL,
            platform=Platform.WSL2,
            title="WSL2: Port forwarding z Windows",
            description="Port forwarding from Windows host to WSL2 instance.",
            command="\n".join(forward_cmds),
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            notes="Run in PowerShell as Administrator on Windows host. WSL2 IP address may change after restart.",
            order=50,
        ))

        return commands

    # ── Antivirus / Directory Exclusions ────────────────────────────

    def directory_exclusions(
        self,
        dirs: list[str] | None = None,
    ) -> list[GeneratedCommand]:
        """Generate antivirus/indexing exclusion commands for UAML directories."""
        if dirs is None:
            dirs = [os.path.expanduser(d) for d in self.DEFAULT_EXCLUDE_DIRS]

        commands = []
        p = self._platform

        if p == Platform.WINDOWS or p == Platform.WSL2:
            commands.extend(self._windows_av_exclusions(dirs))
        if p == Platform.MACOS:
            commands.extend(self._macos_exclusions(dirs))
        if p in (Platform.LINUX, Platform.WSL2):
            commands.extend(self._linux_exclusions(dirs))

        return commands

    def _windows_av_exclusions(self, dirs: list[str]) -> list[GeneratedCommand]:
        commands = []

        for d in dirs:
            # Convert WSL2 path to Windows path if needed
            win_path = d
            if d.startswith("/home/"):
                win_path = f"\\\\wsl$\\Ubuntu{d}"

            commands.append(GeneratedCommand(
                category=CommandCategory.DIRECTORY_EXCLUSION,
                platform=Platform.WINDOWS,
                title=f"Windows Defender: exclusion for {Path(d).name}",
                description=f"Add directory to Windows Defender exclusions (skip scanning).",
                command=f'Add-MpPreference -ExclusionPath "{win_path}"',
                risk=RiskLevel.LOW,
                requires_admin=True,
                notes="PowerShell as Administrator. UAML database does not need AV scanning — data is encrypted.",
                order=20,
            ))

        # Disable real-time monitoring for specific processes
        commands.append(GeneratedCommand(
            category=CommandCategory.DIRECTORY_EXCLUSION,
            platform=Platform.WINDOWS,
            title="Windows Defender: exclusion for Python proces",
            description="Exclude Python process from real-time scanning (speeds up UAML operations).",
            command='Add-MpPreference -ExclusionProcess "python.exe"\nAdd-MpPreference -ExclusionProcess "python3.exe"',
            risk=RiskLevel.LOW,
            requires_admin=True,
            order=21,
        ))

        return commands

    def _macos_exclusions(self, dirs: list[str]) -> list[GeneratedCommand]:
        commands = []

        # Spotlight exclusion
        for d in dirs:
            commands.append(GeneratedCommand(
                category=CommandCategory.DIRECTORY_EXCLUSION,
                platform=Platform.MACOS,
                title=f"Spotlight: exclude {Path(d).name}",
                description="Prevent Spotlight from indexing UAML data (privacy + performance).",
                command=f"sudo mdutil -i off {d}\ntouch {d}/.metadata_never_index",
                risk=RiskLevel.LOW,
                requires_admin=True,
                order=20,
            ))

        # Time Machine exclusion
        for d in dirs:
            commands.append(GeneratedCommand(
                category=CommandCategory.DIRECTORY_EXCLUSION,
                platform=Platform.MACOS,
                title=f"Time Machine: exclude {Path(d).name}",
                description="Exclude UAML data from Time Machine backups (sensitive data).",
                command=f'sudo tmutil addexclusion "{d}"',
                risk=RiskLevel.LOW,
                requires_admin=True,
                notes="UAML has its own backup system — Time Machine backup could duplicate sensitive data.",
                order=25,
            ))

        return commands

    def _linux_exclusions(self, dirs: list[str]) -> list[GeneratedCommand]:
        commands = []

        # ClamAV exclusion
        clam_excludes = "\n".join(f"ExcludePath ^{d}" for d in dirs)
        commands.append(GeneratedCommand(
            category=CommandCategory.DIRECTORY_EXCLUSION,
            platform=Platform.LINUX,
            title="ClamAV: UAML directory exclusions",
            description="Add UAML directories to ClamAV scanner exclusions.",
            command=f"# Add to /etc/clamav/clamd.conf:\n{clam_excludes}",
            risk=RiskLevel.LOW,
            requires_admin=True,
            order=20,
        ))

        return commands

    # ── WSL2 Configuration ──────────────────────────────────────────

    def wsl2_config(
        self,
        interop: bool = True,
        automount_metadata: bool = True,
    ) -> list[GeneratedCommand]:
        """Generate WSL2-specific configuration."""
        commands = []

        wsl_conf = "[automount]\nenabled = true\noptions = \"metadata,umask=22,fmask=11\"\nmountFsTab = true"
        if not interop:
            wsl_conf += "\n\n[interop]\nenabled = false\nappendWindowsPath = false"
        else:
            wsl_conf += "\n\n[interop]\nenabled = true\nappendWindowsPath = true"

        commands.append(GeneratedCommand(
            category=CommandCategory.WSL2_CONFIG,
            platform=Platform.WSL2,
            title="WSL2: /etc/wsl.conf settings",
            description="WSL2 configuration — metadata for correct permissions, interop settings.",
            command=f"sudo tee /etc/wsl.conf << 'EOF'\n{wsl_conf}\nEOF",
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            notes="After this change, restart WSL2 with 'wsl --shutdown' from PowerShell.",
            order=30,
        ))

        # .wslconfig on Windows side
        wslconfig = "[wsl2]\nmemory=4GB\nprocessors=4\nswap=2GB\nlocalhostForwarding=true\n\n[experimental]\nautoMemoryReclaim=gradual"

        commands.append(GeneratedCommand(
            category=CommandCategory.WSL2_CONFIG,
            platform=Platform.WSL2,
            title="WSL2: .wslconfig (Windows strana)",
            description="Resource limits for WSL2 — memory, CPU, swap.",
            command=f"# Save as %USERPROFILE%\\.wslconfig:\n{wslconfig}",
            risk=RiskLevel.LOW,
            requires_admin=False,
            notes="Adjust memory and processors based on your hardware. Restart with 'wsl --shutdown'.",
            order=31,
        ))

        return commands

    # ── BitLocker ───────────────────────────────────────────────────

    def bitlocker_commands(
        self,
        vhd_path: str | None = None,
        vhd_size_gb: int = 10,
    ) -> list[GeneratedCommand]:
        """Generate BitLocker commands for UAML data encryption via VHD."""
        if vhd_path is None:
            vhd_path = r"C:\UAML\uaml-secure.vhdx"

        commands = []

        # Create VHD
        diskpart_script = (
            f"create vdisk file=\"{vhd_path}\" maximum={vhd_size_gb * 1024} type=expandable\n"
            f"select vdisk file=\"{vhd_path}\"\n"
            "attach vdisk\n"
            "create partition primary\n"
            "format fs=ntfs label=\"UAML-Secure\" quick\n"
            "assign letter=U\n"
            "exit"
        )

        commands.append(GeneratedCommand(
            category=CommandCategory.BITLOCKER,
            platform=Platform.WINDOWS,
            title="Create encrypted VHD disk",
            description=f"Creates a virtual disk ({vhd_size_gb} GB) for UAML data.",
            command=f"# Save as create-vhd.txt and run:\ndiskpart /s create-vhd.txt\n\n# Contents of create-vhd.txt:\n{diskpart_script}",
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            notes="The VHD is created as expandable — it uses space only as it fills up.",
            order=40,
        ))

        # Enable BitLocker on VHD
        commands.append(GeneratedCommand(
            category=CommandCategory.BITLOCKER,
            platform=Platform.WINDOWS,
            title="Zapnout BitLocker na VHD",
            description="Encrypts the VHD disk using BitLocker with a password.",
            command=(
                'Enable-BitLocker -MountPoint "U:" -EncryptionMethod XtsAes256 '
                '-PasswordProtector -Password (Read-Host -AsSecureString "Enter password for BitLocker")'
            ),
            risk=RiskLevel.HIGH,
            requires_admin=True,
            notes="Store the password securely! Without it, the data is inaccessible. Save the recovery key in a safe place.",
            order=41,
        ))

        # Save recovery key
        commands.append(GeneratedCommand(
            category=CommandCategory.BITLOCKER,
            platform=Platform.WINDOWS,
            title="Save BitLocker recovery key",
            description="Exports the recovery key in case the password is forgotten.",
            command=(
                '(Get-BitLockerVolume -MountPoint "U:").KeyProtector | '
                'Where-Object { $_.KeyProtectorType -eq "RecoveryPassword" } | '
                'Select-Object -ExpandProperty RecoveryPassword | '
                'Out-File "$env:USERPROFILE\\Desktop\\UAML-BitLocker-Recovery.txt"'
            ),
            risk=RiskLevel.LOW,
            requires_admin=True,
            notes="Store the recovery key in a safe place (not on the same disk!).",
            order=42,
        ))

        # Auto-mount VHD at startup
        commands.append(GeneratedCommand(
            category=CommandCategory.BITLOCKER,
            platform=Platform.WINDOWS,
            title="Auto-mount VHD at startup",
            description="Configures automatic VHD mounting after sign-in.",
            command=(
                f'# Add to Task Scheduler nebo startup skriptu:\n'
                f'$vhd = "{vhd_path}"\n'
                f'Mount-DiskImage -ImagePath $vhd\n'
                f'Unlock-BitLocker -MountPoint "U:" -Password (Read-Host -AsSecureString)'
            ),
            risk=RiskLevel.MEDIUM,
            requires_admin=True,
            order=43,
        ))

        return commands

    # ── Network Profile ─────────────────────────────────────────────

    def network_profile(
        self,
        profile: str = "private",
        interface: str | None = None,
    ) -> list[GeneratedCommand]:
        """Generate network profile configuration commands."""
        commands = []

        if self._platform == Platform.WINDOWS or self._platform == Platform.WSL2:
            if interface:
                cmd = f'Set-NetConnectionProfile -InterfaceAlias "{interface}" -NetworkCategory {profile.capitalize()}'
            else:
                cmd = f'Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory {profile.capitalize()}'

            commands.append(GeneratedCommand(
                category=CommandCategory.NETWORK_PROFILE,
                platform=Platform.WINDOWS,
                title=f"Set network profile: {profile}",
                description=f"Switches the network profile to '{profile}' — affects firewall behavior and sharing.",
                command=f"# First check current profile:\nGet-NetConnectionProfile\n\n# Change:\n{cmd}",
                risk=RiskLevel.MEDIUM,
                requires_admin=True,
                notes="Private = trusted network (home/office). Public = public network (stricter rules).",
                order=60,
            ))

        if self._platform in (Platform.LINUX, Platform.WSL2):
            commands.append(GeneratedCommand(
                category=CommandCategory.NETWORK_PROFILE,
                platform=Platform.LINUX,
                title="Restrict UAML binding to localhost",
                description="UAML services will listen only on localhost (127.0.0.1).",
                command="# Set in UAML configuration:\n# host: 127.0.0.1\n# Instead of: 0.0.0.0 (all interfaces)",
                risk=RiskLevel.LOW,
                requires_admin=False,
                notes="For remote access, use an SSH tunnel or reverse proxy (nginx).",
                order=60,
            ))

        return commands

    # ── Filesystem Hardening ────────────────────────────────────────

    def filesystem_hardening(
        self,
        data_dir: str | None = None,
    ) -> list[GeneratedCommand]:
        """Generate filesystem permission commands."""
        d = data_dir or self._data_dir
        commands = []

        if self._platform in (Platform.LINUX, Platform.WSL2, Platform.MACOS):
            commands.append(GeneratedCommand(
                category=CommandCategory.FILESYSTEM,
                platform=self._platform,
                title="Set UAML directory permissions",
                description="Restricts access to UAML data to the owner only.",
                command=f"chmod 700 {d}\nchmod 600 {d}/*.db\nchmod 600 {d}/*.key",
                risk=RiskLevel.LOW,
                requires_admin=False,
                notes="Ensures that only the owner can read/write UAML data.",
                order=70,
            ))

            commands.append(GeneratedCommand(
                category=CommandCategory.FILESYSTEM,
                platform=self._platform,
                title="Verify permissions",
                description="Verify command — shows current permissions.",
                command=f"ls -la {d}/\nstat {d}/",
                risk=RiskLevel.LOW,
                requires_admin=False,
                order=71,
            ))

        return commands

    # ── Full Configuration ──────────────────────────────────────────

    def full_configuration(
        self,
        ports: list[int] | None = None,
        allow_from: str = "localhost",
        exclude_dirs: list[str] | None = None,
        enable_bitlocker: bool = False,
        network_profile: str = "private",
    ) -> list[GeneratedCommand]:
        """Generate a complete security configuration."""
        all_commands = []

        all_commands.extend(self.firewall_rules(ports=ports, allow_from=allow_from))
        all_commands.extend(self.directory_exclusions(dirs=exclude_dirs))

        if self._platform == Platform.WSL2:
            all_commands.extend(self.wsl2_config())

        if enable_bitlocker and self._platform in (Platform.WINDOWS, Platform.WSL2):
            all_commands.extend(self.bitlocker_commands())

        all_commands.extend(self.network_profile(profile=network_profile))
        all_commands.extend(self.filesystem_hardening())

        # Sort by order
        all_commands.sort(key=lambda c: c.order)
        return all_commands

    # ── Export ───────────────────────────────────────────────────────

    def export_script(
        self,
        commands: list[GeneratedCommand],
        format: str = "text",
    ) -> str:
        """Export commands as a readable script or JSON."""
        if format == "json":
            return json.dumps(
                [c.to_dict() for c in commands],
                indent=2, ensure_ascii=False,
            )

        lines = [
            "# ═══════════════════════════════════════════════════════",
            "# UAML Security Configurator — generated commands",
            f"# Platform: {self._platform.value}",
            "# ⚠️  DO NOT BLINDLY COPY — read the notes for each command!",
            "# ═══════════════════════════════════════════════════════",
            "",
        ]

        current_cat = None
        for cmd in commands:
            if cmd.category != current_cat:
                current_cat = cmd.category
                lines.append(f"\n# ── {current_cat.value.upper().replace('_', ' ')} {'─' * 40}")
                lines.append("")

            risk_label = {"low": "🟢", "medium": "🟠", "high": "🔴"}[cmd.risk.value]
            admin_label = " [requires admin]" if cmd.requires_admin else ""

            lines.append(f"# {risk_label} {cmd.title}{admin_label}")
            lines.append(f"# {cmd.description}")
            if cmd.notes:
                lines.append(f"# ℹ️  {cmd.notes}")
            lines.append(cmd.command)
            lines.append("")

        return "\n".join(lines)

    # ── Helpers ─────────────────────────────────────────────────────

    def _resolve_source(self, allow_from: str) -> str:
        """Resolve allow_from to IP/CIDR."""
        if allow_from == "localhost":
            return "127.0.0.1"
        elif allow_from == "lan":
            return "192.168.0.0/16"
        elif allow_from == "any":
            return ""
        return allow_from

    def _port_label(self, port: int) -> str:
        """Get human label for a port."""
        labels = {v: k for k, v in self.DEFAULT_PORTS.items()}
        return labels.get(port, f"port-{port}")

    # ── Folder Access Manager ───────────────────────────────────────

    FOLDER_BLACKLIST = {
        '/etc', '/boot', '/proc', '/sys', '/dev', '/run',
        '/sbin', '/bin', '/usr/sbin', '/usr/bin', '/lib', '/lib64',
    }

    def _init_security_db(self):
        """Create/open security.db with managed_folders and folder_audit_log tables."""
        if hasattr(self, '_security_db') and self._security_db is not None:
            return self._security_db
        db_path = os.path.join(self._data_dir, "security.db")
        os.makedirs(self._data_dir, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS managed_folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                target_owner TEXT,
                target_group TEXT,
                target_mode TEXT,
                recursive INTEGER DEFAULT 0,
                notes TEXT,
                added_at TEXT DEFAULT (datetime('now')),
                added_by TEXT DEFAULT 'user'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS folder_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path TEXT NOT NULL,
                action TEXT NOT NULL,
                old_permissions TEXT,
                new_permissions TEXT,
                command_executed TEXT,
                success INTEGER,
                executed_by TEXT DEFAULT 'user',
                executed_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        self._security_db = conn
        return conn

    def _get_security_db(self):
        """Lazy accessor for security database connection."""
        if not hasattr(self, '_security_db') or self._security_db is None:
            return self._init_security_db()
        return self._security_db

    def _is_folder_allowed(self, path: str) -> bool:
        """Check if folder path is not blacklisted."""
        p = os.path.realpath(path)
        for bl in self.FOLDER_BLACKLIST:
            if p == bl or p.startswith(bl + '/'):
                return False
        return True

    def list_folder(self, path: str) -> dict:
        """List contents of a folder with permission info."""
        p = os.path.realpath(path)
        if not self._is_folder_allowed(p):
            return {"error": f"Path is blacklisted: {p}", "path": p, "entries": []}
        if not os.path.isdir(p):
            return {"error": f"Not a directory: {p}", "path": p, "entries": []}
        entries = []
        try:
            for name in sorted(os.listdir(p)):
                full = os.path.join(p, name)
                try:
                    st = os.stat(full)
                    entry = {
                        "name": name,
                        "type": "dir" if stat_module.S_ISDIR(st.st_mode) else "file",
                        "mode": oct(stat_module.S_IMODE(st.st_mode)),
                        "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    }
                    if _HAS_POSIX_USERS:
                        try:
                            entry["owner"] = pwd.getpwuid(st.st_uid).pw_name
                        except KeyError:
                            entry["owner"] = str(st.st_uid)
                        try:
                            entry["group"] = grp.getgrgid(st.st_gid).gr_name
                        except KeyError:
                            entry["group"] = str(st.st_gid)
                    else:
                        entry["owner"] = str(st.st_uid)
                        entry["group"] = str(st.st_gid)
                    entries.append(entry)
                except OSError:
                    entries.append({"name": name, "type": "unknown", "error": "Permission denied"})
        except PermissionError:
            return {"error": f"Permission denied: {p}", "path": p, "entries": []}
        return {"path": p, "entries": entries}

    def get_folder_permissions(self, path: str) -> dict:
        """Get current permissions for a folder."""
        p = os.path.realpath(path)
        if not self._is_folder_allowed(p):
            return {"error": f"Path is blacklisted: {p}"}
        if not os.path.exists(p):
            return {"error": f"Path does not exist: {p}"}
        try:
            st = os.stat(p)
        except OSError as e:
            return {"error": str(e)}
        mode_int = stat_module.S_IMODE(st.st_mode)
        mode_octal = oct(mode_int)[2:]  # strip '0o'
        # Build human-readable mode string
        parts = []
        for who in ('USR', 'GRP', 'OTH'):
            r = 'r' if mode_int & getattr(stat_module, f'S_IR{who}') else '-'
            w = 'w' if mode_int & getattr(stat_module, f'S_IW{who}') else '-'
            x = 'x' if mode_int & getattr(stat_module, f'S_IX{who}') else '-'
            parts.append(r + w + x)
        mode_human = ''.join(parts)
        result = {
            "path": p,
            "mode": mode_int,
            "mode_octal": mode_octal,
            "mode_human": mode_human,
        }
        if _HAS_POSIX_USERS:
            try:
                result["owner"] = pwd.getpwuid(st.st_uid).pw_name
            except KeyError:
                result["owner"] = str(st.st_uid)
            try:
                result["group"] = grp.getgrgid(st.st_gid).gr_name
            except KeyError:
                result["group"] = str(st.st_gid)
        else:
            result["owner"] = str(st.st_uid)
            result["group"] = str(st.st_gid)
        return result

    def diff_permissions(self, path: str, target_mode: str,
                         target_owner: str = None, target_group: str = None) -> dict:
        """Compare current vs target permissions."""
        current = self.get_folder_permissions(path)
        if "error" in current:
            return current
        changes = []
        commands = []
        target = {"mode": target_mode}
        if target_owner:
            target["owner"] = target_owner
        if target_group:
            target["group"] = target_group
        # Mode diff
        if current["mode_octal"] != target_mode:
            changes.append(f"mode: {current['mode_octal']} -> {target_mode}")
        # Owner diff
        if target_owner and current.get("owner") != target_owner:
            changes.append(f"owner: {current.get('owner')} -> {target_owner}")
        # Group diff
        if target_group and current.get("group") != target_group:
            changes.append(f"group: {current.get('group')} -> {target_group}")
        # Generate commands if there are changes
        if changes:
            commands = self.generate_permission_commands(
                path, target_mode,
                owner=target_owner if target_owner and current.get("owner") != target_owner else None,
                group=target_group if target_group and current.get("group") != target_group else None,
            )
        return {
            "path": current["path"],
            "current": {
                "mode": current["mode_octal"],
                "owner": current.get("owner"),
                "group": current.get("group"),
            },
            "target": target,
            "changes": changes,
            "commands": commands,
        }

    def generate_permission_commands(self, path: str, mode: str,
                                     owner: str = None, group: str = None,
                                     recursive: bool = False) -> list:
        """Generate chmod/chown commands (platform-aware)."""
        commands = []
        p = os.path.realpath(path)
        plat = self._platform
        rec_flag = "-R " if recursive else ""
        if plat == Platform.WINDOWS:
            # Windows: use icacls
            if mode:
                commands.append(f'icacls "{p}" /reset')
            if owner:
                commands.append(f'icacls "{p}" /setowner "{owner}"')
        else:
            # Linux, WSL2, macOS
            if mode:
                commands.append(f"chmod {rec_flag}{mode} {p}")
            if owner and group:
                commands.append(f"chown {rec_flag}{owner}:{group} {p}")
            elif owner:
                commands.append(f"chown {rec_flag}{owner} {p}")
            elif group:
                commands.append(f"chgrp {rec_flag}{group} {p}")
        return commands

    def add_managed_folder(self, path: str, target_mode: str = '700',
                           target_owner: str = None, target_group: str = None,
                           recursive: bool = False, notes: str = '') -> dict:
        """Add a folder to managed list."""
        p = os.path.realpath(path)
        if not self._is_folder_allowed(p):
            return {"error": f"Path is blacklisted: {p}"}
        if not os.path.isdir(p):
            return {"error": f"Not a directory: {p}"}
        db = self._get_security_db()
        try:
            db.execute(
                "INSERT INTO managed_folders (path, target_owner, target_group, target_mode, recursive, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (p, target_owner, target_group, target_mode, 1 if recursive else 0, notes),
            )
            db.commit()
            self.log_folder_action(p, 'add', '', f'mode={target_mode}', '', True)
            return {"success": True, "path": p}
        except sqlite3.IntegrityError:
            return {"error": f"Folder already managed: {p}"}

    def remove_managed_folder(self, folder_id: int) -> bool:
        """Remove from managed list."""
        db = self._get_security_db()
        cur = db.execute("SELECT path FROM managed_folders WHERE id = ?", (folder_id,))
        row = cur.fetchone()
        if not row:
            return False
        folder_path = row["path"]
        db.execute("DELETE FROM managed_folders WHERE id = ?", (folder_id,))
        db.commit()
        self.log_folder_action(folder_path, 'remove', '', '', '', True)
        return True

    def get_managed_folders(self) -> list:
        """Get all managed folders with current status."""
        db = self._get_security_db()
        cur = db.execute("SELECT * FROM managed_folders ORDER BY added_at DESC")
        results = []
        for row in cur.fetchall():
            entry = dict(row)
            # Get current permissions and compare with target
            current = self.get_folder_permissions(entry["path"])
            entry["current_permissions"] = current
            if "error" not in current:
                changes = []
                if current["mode_octal"] != (entry.get("target_mode") or ""):
                    changes.append(f"mode: {current['mode_octal']} -> {entry.get('target_mode')}")
                if entry.get("target_owner") and current.get("owner") != entry["target_owner"]:
                    changes.append(f"owner: {current.get('owner')} -> {entry['target_owner']}")
                if entry.get("target_group") and current.get("group") != entry["target_group"]:
                    changes.append(f"group: {current.get('group')} -> {entry['target_group']}")
                entry["needs_update"] = len(changes) > 0
                entry["pending_changes"] = changes
            else:
                entry["needs_update"] = None
                entry["pending_changes"] = []
            results.append(entry)
        return results

    def log_folder_action(self, folder_path: str, action: str,
                          old_perms: str, new_perms: str,
                          command: str, success: bool):
        """Log an action to folder_audit_log."""
        db = self._get_security_db()
        db.execute(
            "INSERT INTO folder_audit_log (folder_path, action, old_permissions, new_permissions, "
            "command_executed, success) VALUES (?, ?, ?, ?, ?, ?)",
            (folder_path, action, old_perms, new_perms, command, 1 if success else 0),
        )
        db.commit()

    def get_folder_audit_log(self, folder_path: str = None, limit: int = 50) -> list:
        """Get audit log, optionally filtered by folder."""
        db = self._get_security_db()
        if folder_path:
            cur = db.execute(
                "SELECT * FROM folder_audit_log WHERE folder_path = ? ORDER BY executed_at DESC LIMIT ?",
                (folder_path, limit),
            )
        else:
            cur = db.execute(
                "SELECT * FROM folder_audit_log ORDER BY executed_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]

    # ── Web UI ──────────────────────────────────────────────────────

    def serve(self, port: int = 8785, host: str = "127.0.0.1"):
        """Start the Security Configurator web server.

        Runs on localhost only. Users can execute commands directly
        from the browser by clicking 'Run'. Each execution requires
        explicit user confirmation.

        Args:
            port: Port to listen on (default 8785).
            host: Host to bind to. ALWAYS 127.0.0.1 for security.
        """
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler
        except ImportError:
            raise RuntimeError("http.server not available")

        # Force localhost binding for security
        if host != "127.0.0.1":
            logger.warning("Security Configurator forced to 127.0.0.1 (localhost only)")
            host = "127.0.0.1"

        configurator = self

        class ConfigHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    html = configurator.generate_web_ui()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                elif self.path == "/api/platform":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "platform": configurator.platform.value,
                    }).encode("utf-8"))
                elif self.path == "/api/status":
                    import socket
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "hostname": socket.gethostname(),
                        "platform": configurator.platform.value,
                        "agent": "UAML Security Configurator",
                        "version": "1.0.0",
                    }).encode("utf-8"))
                elif self.path == "/api/expert/status":
                    session = configurator.expert.current_session
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "active": configurator.expert.is_active,
                        "session": session.to_dict() if session else None,
                    }, ensure_ascii=False).encode("utf-8"))

                elif self.path == "/api/expert/audit":
                    self._json_response(200, {
                        "sessions": configurator.expert.get_audit_trail(),
                    })

                elif self.path == "/api/history":
                    self._json_response(200, {
                        "executions": configurator.execution_log,
                    })

                elif self.path.startswith("/api/report"):
                    fmt = "html"
                    if "json" in self.path:
                        fmt = "json"
                    report = configurator.generate_report(format=fmt)
                    ct = "application/json" if fmt == "json" else "text/html; charset=utf-8"
                    self.send_response(200)
                    self.send_header("Content-Type", ct)
                    if fmt == "html":
                        self.send_header("Content-Disposition", 'inline; filename="uaml-security-report.html"')
                    self.end_headers()
                    self.wfile.write(report.encode("utf-8"))

                elif self.path.startswith("/api/folders/"):
                    parsed = urlparse(self.path)
                    qs = parse_qs(parsed.query)
                    route = parsed.path

                    if route == "/api/folders/list":
                        folder_path = qs.get("path", [""])[0]
                        if not folder_path:
                            self._json_response(400, {"error": "Missing 'path' parameter"})
                        elif not configurator._is_folder_allowed(folder_path):
                            self._json_response(403, {"error": f"Path is blacklisted: {folder_path}"})
                        else:
                            self._json_response(200, configurator.list_folder(folder_path))

                    elif route == "/api/folders/managed":
                        self._json_response(200, {"folders": configurator.get_managed_folders()})

                    elif route == "/api/folders/permissions":
                        folder_path = qs.get("path", [""])[0]
                        if not folder_path:
                            self._json_response(400, {"error": "Missing 'path' parameter"})
                        elif not configurator._is_folder_allowed(folder_path):
                            self._json_response(403, {"error": f"Path is blacklisted: {folder_path}"})
                        else:
                            self._json_response(200, configurator.get_folder_permissions(folder_path))

                    elif route == "/api/folders/diff":
                        folder_path = qs.get("path", [""])[0]
                        mode = qs.get("mode", [""])[0]
                        owner = qs.get("owner", [None])[0]
                        group = qs.get("group", [None])[0]
                        if not folder_path or not mode:
                            self._json_response(400, {"error": "Missing 'path' and/or 'mode' parameter"})
                        elif not configurator._is_folder_allowed(folder_path):
                            self._json_response(403, {"error": f"Path is blacklisted: {folder_path}"})
                        else:
                            self._json_response(200, configurator.diff_permissions(folder_path, mode, owner, group))

                    elif route == "/api/folders/audit":
                        folder_path = qs.get("path", [None])[0]
                        limit = int(qs.get("limit", ["50"])[0])
                        self._json_response(200, {"log": configurator.get_folder_audit_log(folder_path, limit)})

                    else:
                        self._json_response(404, {"error": "Unknown folders endpoint"})

                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/api/execute":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        command = data.get("command", "")
                        title = data.get("title", command[:60])
                        risk = data.get("risk", "low")
                        admin = data.get("requires_admin", False)
                        if not command:
                            self._json_response(400, {"error": "No command provided"})
                            return

                        # Execute the command
                        result = subprocess.run(
                            command,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        output = (result.stdout + result.stderr)[:5000]
                        success = result.returncode == 0

                        # Log execution
                        configurator.log_execution(
                            command=command, title=title, success=success,
                            returncode=result.returncode, output=output,
                            risk=risk, requires_admin=admin,
                        )

                        self._json_response(200, {
                            "success": success,
                            "returncode": result.returncode,
                            "stdout": result.stdout[:5000],
                            "stderr": result.stderr[:5000],
                        })
                    except subprocess.TimeoutExpired:
                        configurator.log_execution(
                            command=command, title=title, success=False,
                            returncode=-1, output="Timeout 60s",
                            risk=risk, requires_admin=admin,
                        )
                        self._json_response(200, {
                            "success": False,
                            "returncode": -1,
                            "stdout": "",
                            "stderr": "Command timed out (timeout 60s)",
                        })
                    except Exception as e:
                        self._json_response(500, {"error": str(e)})

                elif self.path == "/api/generate":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        commands = configurator.full_configuration(
                            ports=data.get("ports"),
                            allow_from=data.get("allow_from", "localhost"),
                            exclude_dirs=data.get("exclude_dirs"),
                            enable_bitlocker=data.get("enable_bitlocker", False),
                            network_profile=data.get("network_profile", "private"),
                        )
                        self._json_response(200, {
                            "commands": [c.to_dict() for c in commands],
                        })
                    except Exception as e:
                        self._json_response(500, {"error": str(e)})

                elif self.path == "/api/expert/start":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        session = configurator.expert.start_session(
                            duration_minutes=data.get("duration_minutes", 15),
                            access_level=ExpertAccessLevel(data.get("access_level", "diagnostic")),
                            reason=data.get("reason", ""),
                        )
                        # Set web-based approval (always approve for web UI — user clicked the button)
                        configurator.expert.set_approval_callback(lambda cmd: True)
                        self._json_response(200, {"session": session.to_dict()})
                    except Exception as e:
                        self._json_response(400, {"error": str(e)})

                elif self.path == "/api/expert/stop":
                    session = configurator.expert.stop_session()
                    self._json_response(200, {
                        "stopped": True,
                        "session": session.to_dict() if session else None,
                    })

                elif self.path == "/api/expert/execute":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        command = data.get("command", "")
                        if not command:
                            self._json_response(400, {"error": "No command"})
                            return
                        result = configurator.expert.execute(command)
                        self._json_response(200, {"result": result.to_dict()})
                    except RuntimeError as e:
                        self._json_response(403, {"error": str(e)})
                    except Exception as e:
                        self._json_response(500, {"error": str(e)})

                elif self.path == "/api/download":
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body)
                        fmt = data.get("format", "sh")
                        commands = configurator.full_configuration(
                            ports=data.get("ports"),
                            allow_from=data.get("allow_from", "localhost"),
                            exclude_dirs=data.get("exclude_dirs"),
                            enable_bitlocker=data.get("enable_bitlocker", False),
                            network_profile=data.get("network_profile", "private"),
                        )
                        script = configurator.export_script(commands, format="text")

                        if fmt == "ps1":
                            script = "# PowerShell Security Setup\n# Run as Administrator\n\n" + script
                            filename = "uaml-security-setup.ps1"
                            ct = "application/octet-stream"
                        elif fmt == "bat":
                            script = "@echo off\nREM UAML Security Setup\nREM Run as Administrator\n\n" + script
                            filename = "uaml-security-setup.bat"
                            ct = "application/octet-stream"
                        else:
                            script = "#!/bin/bash\n# UAML Security Setup\n# Run with sudo\n\n" + script
                            filename = "uaml-security-setup.sh"
                            ct = "application/x-sh"

                        self.send_response(200)
                        self.send_header("Content-Type", ct)
                        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                        self.end_headers()
                        self.wfile.write(script.encode("utf-8"))
                    except Exception as e:
                        self._json_response(500, {"error": str(e)})

                elif self.path.startswith("/api/folders/"):
                    content_length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_length)
                    try:
                        data = json.loads(body) if body else {}
                    except json.JSONDecodeError:
                        self._json_response(400, {"error": "Invalid JSON"})
                        return

                    if self.path == "/api/folders/add":
                        folder_path = data.get("path", "")
                        if not folder_path:
                            self._json_response(400, {"error": "Missing 'path'"})
                            return
                        if not configurator._is_folder_allowed(folder_path):
                            self._json_response(403, {"error": f"Path is blacklisted: {folder_path}"})
                            return
                        result = configurator.add_managed_folder(
                            path=folder_path,
                            target_mode=data.get("target_mode", "700"),
                            target_owner=data.get("target_owner"),
                            target_group=data.get("target_group"),
                            recursive=data.get("recursive", False),
                            notes=data.get("notes", ""),
                        )
                        code = 200 if "success" in result else 400
                        self._json_response(code, result)

                    elif self.path == "/api/folders/remove":
                        folder_id = data.get("id")
                        if folder_id is None:
                            self._json_response(400, {"error": "Missing 'id'"})
                            return
                        removed = configurator.remove_managed_folder(int(folder_id))
                        self._json_response(200, {"success": removed})

                    elif self.path == "/api/folders/apply":
                        folder_path = data.get("path", "")
                        mode = data.get("mode", "")
                        owner = data.get("owner")
                        group = data.get("group")
                        recursive = data.get("recursive", False)
                        if not folder_path:
                            self._json_response(400, {"error": "Missing 'path'"})
                            return
                        if not configurator._is_folder_allowed(folder_path):
                            self._json_response(403, {"error": f"Path is blacklisted: {folder_path}"})
                            return
                        if not os.path.exists(folder_path):
                            self._json_response(400, {"error": f"Path does not exist: {folder_path}"})
                            return
                        # Get current permissions before change
                        old_perms = configurator.get_folder_permissions(folder_path)
                        old_str = f"mode={old_perms.get('mode_octal', '?')} owner={old_perms.get('owner', '?')} group={old_perms.get('group', '?')}"
                        commands = configurator.generate_permission_commands(
                            folder_path, mode, owner=owner, group=group, recursive=recursive,
                        )
                        results = []
                        all_success = True
                        for cmd in commands:
                            try:
                                proc = subprocess.run(
                                    cmd, shell=True, capture_output=True, text=True, timeout=30,
                                )
                                success = proc.returncode == 0
                                if not success:
                                    all_success = False
                                results.append({
                                    "command": cmd,
                                    "success": success,
                                    "stdout": proc.stdout[:2000],
                                    "stderr": proc.stderr[:2000],
                                })
                            except subprocess.TimeoutExpired:
                                all_success = False
                                results.append({
                                    "command": cmd,
                                    "success": False,
                                    "stderr": "Timeout (30s)",
                                })
                            except Exception as e:
                                all_success = False
                                results.append({
                                    "command": cmd,
                                    "success": False,
                                    "stderr": str(e),
                                })
                        new_str = f"mode={mode} owner={owner or '?'} group={group or '?'}"
                        for cmd_result in results:
                            configurator.log_folder_action(
                                folder_path, 'apply', old_str, new_str,
                                cmd_result["command"], cmd_result["success"],
                            )
                        self._json_response(200, {
                            "success": all_success,
                            "commands_executed": results,
                        })

                    else:
                        self._json_response(404, {"error": "Unknown folders endpoint"})

                else:
                    self.send_response(404)
                    self.end_headers()

            def _json_response(self, code: int, data: dict):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

            def log_message(self, format, *args):
                logger.info(f"SecurityConfigurator: {args[0]}")

        server = HTTPServer((host, port), ConfigHandler)
        logger.info(f"Security Configurator running at http://{host}:{port}")
        print(f"🛡️  UAML Security Configurator")
        print(f"   http://{host}:{port}")
        print(f"   Platform: {self._platform.value}")
        print(f"   ⚠️  Localhost only — AI agent has no access")
        print(f"   Ctrl+C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()
            print("\nSecurity Configurator stopped.")

    def generate_web_ui(self) -> str:
        """Generate the Security Configurator web UI HTML."""
        html = _CONFIGURATOR_HTML.replace("{{PLATFORM}}", self._platform.value)
        return html.replace("{{PLATFORM_UPPER}}", self._platform.value.upper())


# ── Web UI HTML Template ────────────────────────────────────────────

_CONFIGURATOR_HTML = """<!DOCTYPE html>
<html lang="cs">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UAML Security Configurator</title>
    <style>
        :root { --bg: #0a0a0f; --surface: #12121a; --card: #1a1a2e; --border: #2a2a3e; --text: #e4e4ef; --muted: #8888a0; --accent: #6366f1; --accent2: #818cf8; --green: #22c55e; --yellow: #eab308; --red: #ef4444; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
        .container { max-width: 900px; margin: 0 auto; padding: 24px; }

        header { text-align: center; padding: 40px 0 32px; border-bottom: 1px solid var(--border); margin-bottom: 32px; }
        header h1 { font-size: 2rem; font-weight: 800; margin-bottom: 8px; }
        header h1 span { color: var(--accent2); }
        header p { color: var(--muted); }
        .platform-badge { display: inline-block; background: var(--accent); color: white; padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 600; margin-top: 12px; }
        .warning-banner { background: rgba(234,179,8,0.1); border: 1px solid var(--yellow); border-radius: 12px; padding: 16px; margin-bottom: 32px; text-align: center; }
        .warning-banner span { color: var(--yellow); font-weight: 600; }

        .wizard-steps { display: flex; gap: 8px; margin-bottom: 32px; flex-wrap: wrap; position: relative; z-index: 1; }
        .step { flex: 1; min-width: 120px; text-align: center; padding: 12px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border); cursor: pointer; transition: all 0.2s; user-select: none; }
        .step:hover { background: var(--card); border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(99,102,241,0.3); }
        .step.active { background: var(--accent); border-color: var(--accent); }
        .step.active:hover { background: #5558e6; }
        .step.done { background: var(--card); border-color: var(--green); }
        .step.done .num { color: var(--green); }
        .step .num { font-size: 1.5rem; font-weight: 800; }
        .step .label { font-size: 0.75rem; margin-top: 4px; }
        .step.done { border-color: var(--green); }
        .step .num { font-size: 1.2rem; font-weight: 700; }
        .step .label { font-size: 0.75rem; color: var(--muted); margin-top: 4px; }
        .step.active .label { color: rgba(255,255,255,0.8); }

        .section { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 24px; margin-bottom: 24px; display: none; }
        .section.visible { display: block; }
        .section h2 { font-size: 1.3rem; margin-bottom: 16px; }
        .section p.desc { color: var(--muted); margin-bottom: 20px; }

        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; font-weight: 600; margin-bottom: 6px; font-size: 0.9rem; }
        .form-group .hint { color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
        input[type="text"], input[type="number"], select { width: 100%; padding: 10px 14px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 0.95rem; }
        input:focus, select:focus { outline: none; border-color: var(--accent); }
        .checkbox-group { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
        .checkbox-group input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--accent); }

        .port-list { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
        .port-tag { background: var(--card); border: 1px solid var(--border); padding: 6px 14px; border-radius: 20px; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
        .port-tag .remove { cursor: pointer; color: var(--red); font-weight: bold; }
        .add-port { display: flex; gap: 8px; margin-top: 12px; }
        .add-port input { width: 120px; }

        button { padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-weight: 600; font-size: 0.95rem; transition: all 0.2s; }
        .btn-primary { background: var(--accent); color: white; }
        .btn-primary:hover { background: var(--accent2); }
        .btn-secondary { background: var(--card); color: var(--text); border: 1px solid var(--border); }
        .btn-danger { background: var(--red); color: white; }
        .btn-group { display: flex; gap: 12px; margin-top: 24px; }

        .output-section { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 24px; margin-top: 32px; display: none; }
        .output-section.visible { display: block; }
        .output-section h2 { margin-bottom: 16px; }

        .command-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
        .command-card .cmd-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .command-card .cmd-title { font-weight: 600; }
        .command-card .cmd-desc { color: var(--muted); font-size: 0.85rem; margin-bottom: 12px; }
        .command-card pre { background: var(--bg); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 0.8rem; line-height: 1.5; position: relative; }
        .command-card .notes { color: var(--yellow); font-size: 0.8rem; margin-top: 8px; }
        .risk-low { color: var(--green); }
        .risk-medium { color: var(--yellow); }
        .risk-high { color: var(--red); }
        .copy-btn { padding: 4px 12px; font-size: 0.75rem; background: var(--accent); color: white; border: none; border-radius: 6px; cursor: pointer; }
        .copy-btn:hover { background: var(--accent2); }
        .run-btn { padding: 4px 12px; font-size: 0.75rem; background: var(--green); color: white; border: none; border-radius: 6px; cursor: pointer; margin-right: 4px; }
        .run-btn:hover { opacity: 0.9; }
        .run-btn.running { background: var(--yellow); color: #000; }
        .run-btn.done { background: var(--green); opacity: 0.7; }
        .run-btn.failed { background: var(--red); }
        .exec-result { margin-top: 8px; padding: 10px; border-radius: 8px; font-size: 0.8rem; font-family: monospace; max-height: 200px; overflow-y: auto; display: none; }
        .exec-result.visible { display: block; }
        .exec-result.success { background: rgba(34,197,94,0.1); border: 1px solid var(--green); }
        .exec-result.error { background: rgba(239,68,68,0.1); border: 1px solid var(--red); }
        .confirm-modal { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .confirm-box { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 32px; max-width: 500px; width: 90%; }
        .confirm-box h3 { margin-bottom: 12px; color: var(--yellow); }
        .confirm-box pre { background: var(--bg); padding: 12px; border-radius: 8px; font-size: 0.8rem; margin: 12px 0; max-height: 150px; overflow-y: auto; }
        .confirm-box .btn-group { margin-top: 16px; }

        .admin-badge { font-size: 0.7rem; background: var(--yellow); color: #000; padding: 2px 8px; border-radius: 10px; font-weight: 600; }

        .sticky-header { position: fixed; top: 0; left: 0; right: 0; z-index: 1000; background: #0a0e1a; border-bottom: 2px solid var(--border); padding: 10px 24px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 8px rgba(0,0,0,0.5); }
        .sticky-header h1 { margin: 0; font-size: 1.2rem; font-weight: 800; }
        .sticky-header h1 span { color: var(--accent2); }
        .sticky-header .host-info { color: var(--muted); font-size: 0.85rem; }
        .sticky-header .host-info .machine-name { color: #c4a6ff; font-weight: bold; }

        footer { text-align: center; color: var(--muted); font-size: 0.8rem; padding: 40px 0 20px; border-top: 1px solid var(--border); margin-top: 40px; }
    </style>
</head>
<body>
<div class="sticky-header">
    <h1>🛡️ UAML <span>Security Configurator</span></h1>
    <div class="host-info">
        <span class="machine-name" id="machineName">localhost</span> ·
        <span id="headerPlatform">{{PLATFORM_UPPER}}</span>
    </div>
</div>
<div class="container" style="margin-top: 60px;">
    <header>
        <h1>🛡️ UAML <span>Security Configurator</span></h1>
        <p>Security command generator for your platform</p>
        <div class="platform-badge" id="platformBadge">Platform: {{PLATFORM_UPPER}}</div>
    </header>

    <div class="warning-banner">
        <span>⚠️ This tool runs only on your machine (localhost).</span><br>
        AI agent has no access. You run commands by clicking the button.
    </div>

    <div class="wizard-steps">
        <div class="step active" onclick="showStep(0)"><div class="num">1</div><div class="label">Firewall</div></div>
        <div class="step" onclick="showStep(1)"><div class="num">2</div><div class="label">AV Exclusions</div></div>
        <div class="step" onclick="showStep(2)"><div class="num">3</div><div class="label">WSL2</div></div>
        <div class="step" onclick="showStep(3)"><div class="num">4</div><div class="label">BitLocker</div></div>
        <div class="step" onclick="showStep(4)"><div class="num">5</div><div class="label">Network</div></div>
        <div class="step" onclick="showStep(5)"><div class="num">6</div><div class="label">Files</div></div>
        <div class="step" onclick="showStep(6)"><div class="num">7</div><div class="label">📁 Folder Access</div></div>
    </div>

    <!-- Step 1: Firewall -->
    <div class="section visible" id="step-0">
        <h2>🔥 Firewall Rules</h2>
        <p class="desc">Set which ports to allow and from where.</p>
        <div class="form-group">
            <label>Ports to allow:</label>
            <div class="port-list" id="portList">
                <div class="port-tag">8780 (API) <span class="remove" onclick="removePort(this)">×</span></div>
                <div class="port-tag">8781 (Dashboard) <span class="remove" onclick="removePort(this)">×</span></div>
                <div class="port-tag">8785 (Security) <span class="remove" onclick="removePort(this)">×</span></div>
            </div>
            <div class="add-port">
                <input type="number" id="newPort" placeholder="Port" min="1" max="65535">
                <button class="btn-secondary" onclick="addPort()">+ Add</button>
            </div>
        </div>
        <div class="form-group">
            <label>Allow access from:</label>
            <select id="allowFrom">
                <option value="localhost">Localhost only (127.0.0.1)</option>
                <option value="lan">Local network (LAN)</option>
                <option value="any">Anywhere (⚠️ dangerous)</option>
            </select>
            <div class="hint">For remote access, we recommend using an SSH tunnel instead of opening ports.</div>
        </div>
        <div class="btn-group">
            <button class="btn-primary" onclick="nextStep()">Next →</button>
        </div>
    </div>

    <!-- Step 2: AV Exclusions -->
    <div class="section" id="step-1">
        <h2>🛡️ Antivirus exclusions</h2>
        <p class="desc">UAML data is encrypted — AV scanning is unnecessary and slows operations down.</p>
        <div class="form-group">
            <label>Directories to exclude:</label>
            <input type="text" id="excludeDir1" value="~/.uaml">
            <input type="text" id="excludeDir2" value="~/.openclaw" style="margin-top:8px">
        </div>
        <div class="checkbox-group">
            <input type="checkbox" id="excludePython" checked>
            <label for="excludePython">Exclude Python process from real-time scanning</label>
        </div>
        <div class="btn-group">
            <button class="btn-secondary" onclick="prevStep()">← Back</button>
            <button class="btn-primary" onclick="nextStep()">Next →</button>
        </div>
    </div>

    <!-- Step 3: WSL2 -->
    <div class="section" id="step-2">
        <h2>🐧 WSL2 Configuration</h2>
        <p class="desc">Settings specific to Windows Subsystem for Linux.</p>
        <div class="checkbox-group">
            <input type="checkbox" id="wslInterop" checked>
            <label for="wslInterop">Enable Windows interop (running .exe from WSL)</label>
        </div>
        <div class="checkbox-group">
            <input type="checkbox" id="wslMetadata" checked>
            <label for="wslMetadata">Automount with metadata (correct permissions)</label>
        </div>
        <div class="checkbox-group">
            <input type="checkbox" id="wslPortForward" checked>
            <label for="wslPortForward">Port forwarding z Windows do WSL2</label>
        </div>
        <div class="form-group">
            <label>WSL2 memory (GB):</label>
            <input type="number" id="wslMemory" value="4" min="1" max="64">
        </div>
        <div class="btn-group">
            <button class="btn-secondary" onclick="prevStep()">← Back</button>
            <button class="btn-primary" onclick="nextStep()">Next →</button>
        </div>
    </div>

    <!-- Step 4: BitLocker -->
    <div class="section" id="step-3">
        <h2>🔐 BitLocker encryption</h2>
        <p class="desc">Create an encrypted VHD disk for UAML data (Windows).</p>
        <div class="checkbox-group">
            <input type="checkbox" id="enableBitlocker">
            <label for="enableBitlocker">Enable BitLocker VHD</label>
        </div>
        <div class="form-group">
            <label>VHD file path:</label>
            <input type="text" id="vhdPath" value="C:\\UAML\\uaml-secure.vhdx">
        </div>
        <div class="form-group">
            <label>VHD size (GB):</label>
            <input type="number" id="vhdSize" value="10" min="1" max="500">
        </div>
        <div class="btn-group">
            <button class="btn-secondary" onclick="prevStep()">← Back</button>
            <button class="btn-primary" onclick="nextStep()">Next →</button>
        </div>
    </div>

    <!-- Step 5: Network -->
    <div class="section" id="step-4">
        <h2>🌐 Network profile</h2>
        <p class="desc">Network profile settings affect firewall behavior.</p>
        <div class="form-group">
            <label>Network profile:</label>
            <select id="networkProfile">
                <option value="private">Private (home/office)</option>
                <option value="public">Public (public network)</option>
            </select>
            <div class="hint">Private = less restrictive. Public = safer for untrusted networks.</div>
        </div>
        <div class="btn-group">
            <button class="btn-secondary" onclick="prevStep()">← Back</button>
            <button class="btn-primary" onclick="nextStep()">Next →</button>
        </div>
    </div>

    <!-- Step 6: Filesystem -->
    <div class="section" id="step-5">
        <h2>📁 File Permissions</h2>
        <p class="desc">Set correct permissions for UAML data directories.</p>
        <div class="form-group">
            <label>UAML data directory:</label>
            <input type="text" id="dataDir" value="~/.uaml">
        </div>
        <div class="btn-group">
            <button class="btn-secondary" onclick="prevStep()">← Back</button>
            <button class="btn-primary" onclick="generateCommands()">🔧 Generate Commands</button>
        </div>
    </div>

    <!-- Step 7: Folder Access Manager -->
    <div class="section" id="step-6">
        <h2>📁 Folder Access Manager</h2>
        <p class="desc">Manage folder permissions on the host machine. Add folders to monitoring, view and change permissions.</p>

        <div class="form-group">
            <label>Browse folder:</label>
            <div style="display:flex;gap:8px;">
                <input type="text" id="folderPath" value="/" placeholder="/path/to/folder">
                <button class="btn-primary" onclick="scanFolder()">🔍 Scan</button>
            </div>
        </div>

        <div id="folderContents" style="margin-top:16px;"></div>

        <h3 style="margin-top:24px;margin-bottom:12px;">Managed Folders</h3>
        <div id="managedFoldersList"><p style="color:var(--muted);">Loading...</p></div>

        <div class="form-group" style="margin-top:16px;">
            <label>Add folder to managed list:</label>
            <div style="display:flex;gap:8px;">
                <input type="text" id="addFolderPath" placeholder="/path/to/folder">
                <select id="addFolderTarget" style="width:150px;">
                    <option value="700">700 (owner only)</option>
                    <option value="750">750 (owner+group)</option>
                    <option value="755">755 (read all)</option>
                </select>
                <button class="btn-primary" onclick="addManagedFolder()">+ Add</button>
            </div>
        </div>

        <h3 style="margin-top:24px;margin-bottom:12px;">Audit Log</h3>
        <div id="folderAuditLog"><p style="color:var(--muted);">Loading...</p></div>

        <div class="btn-group">
            <button class="btn-secondary" onclick="prevStep()">← Back</button>
            <button class="btn-primary" onclick="generateCommands()">🔧 Generate Commands</button>
        </div>
    </div>

    <!-- Output -->
    <div class="output-section" id="outputSection">
        <h2>📋 Generated Commands</h2>
        <p style="color:var(--muted);margin-bottom:20px;">Click ▶️ Run for each command, or run all at once.</p>
        <div id="commandList"></div>
        <div class="btn-group">
            <button class="btn-primary" onclick="runAll()" style="background:var(--green);">▶️ Run All</button>
            <button class="btn-secondary" onclick="copyAll()">📋 Copy All</button>
            <button class="btn-secondary" onclick="downloadScript()">💾 Download Script</button>
        </div>
    </div>
</div>

    <!-- Execution History -->
    <div class="output-section" id="historySection" style="display:none;margin-top:24px;">
        <h2>📜 Execution History</h2>
        <p style="color:var(--muted);margin-bottom:16px;">Complete log — for documentation, IT audit or management.</p>
        <div id="historyLog"></div>
        <div class="btn-group" style="margin-top:16px;">
            <button class="btn-primary" onclick="window.open('/api/report','_blank')">📄 Open HTML Report</button>
            <button class="btn-secondary" onclick="downloadReport()">💾 Download Report</button>
            <button class="btn-secondary" onclick="copyHistory()">📋 Copy Log</button>
        </div>
    </div>

    <!-- Expert Mode -->
    <div class="section visible" style="margin-top:40px; border-color: var(--yellow);">
        <h2>🤖 Expert on Demand</h2>
        <p class="desc">Temporarily allow AI agent access for diagnostics and fixes. Everything is logged and under your control.</p>

        <div id="expertInactive">
            <div class="form-group">
                <label>Access level:</label>
                <select id="expertLevel">
                    <option value="diagnostic">🔍 Diagnostic (read-only — ls, status, logs)</option>
                    <option value="repair">🔧 Repair (can change settings — with approval)</option>
                </select>
            </div>
            <div class="form-group">
                <label>Access duration (minutes):</label>
                <input type="number" id="expertDuration" value="15" min="1" max="60">
                <div class="hint">Max. 60 minutes. Access is removed automatically when it expires.</div>
            </div>
            <div class="form-group">
                <label>Reason (optional):</label>
                <input type="text" id="expertReason" placeholder="E.g. network not working, port blocked...">
            </div>
            <button class="btn-primary" onclick="startExpert()" style="background:var(--yellow);color:#000;">🤖 Povolit AI diagnostiku</button>
        </div>

        <div id="expertActive" style="display:none;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                <div>
                    <span style="font-size:1.1rem;font-weight:700;color:var(--green);">🟢 Expert Mode active</span>
                    <span id="expertTimer" style="margin-left:12px;color:var(--yellow);font-weight:600;"></span>
                    <span id="expertLevelBadge" style="margin-left:8px;font-size:0.8rem;background:var(--yellow);color:#000;padding:2px 8px;border-radius:10px;"></span>
                </div>
                <button class="btn-danger" onclick="stopExpert()">⛔ Zastavit</button>
            </div>
            <div id="expertLog" style="background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:16px;max-height:400px;overflow-y:auto;font-family:monospace;font-size:0.8rem;line-height:1.6;">
                <div style="color:var(--muted);">Waiting for AI agent commands...</div>
            </div>
            <div style="margin-top:12px;color:var(--muted);font-size:0.8rem;">
                ℹ️ Every command is logged. Dangerous commands require your approval. Click ⛔ Stop anytime.
            </div>
        </div>

        <div id="expertAudit" style="margin-top:24px;display:none;">
            <h3 style="color:var(--accent2);margin-bottom:12px;">📋 Audit trail</h3>
            <div id="expertAuditLog"></div>
        </div>
    </div>

<footer>
    <p>© 2026 GLG, a.s. — UAML Security Configurator v1.0</p>
    <p style="margin-top:4px;">⚠️ AI agent does not have access to this tool. Runs on localhost only. Commands are executed by the user.</p>
</footer>

<script>
let currentStep = 0;
const totalSteps = 7;
const detectedPlatform = "{{PLATFORM}}";

document.getElementById('platformBadge').textContent = 'Platform: ' + detectedPlatform.toUpperCase();
document.getElementById('headerPlatform').textContent = detectedPlatform.toUpperCase();
// Populate sticky header with hostname
fetch('/api/status').then(r => r.json()).then(d => {
    document.getElementById('machineName').textContent = d.hostname || 'localhost';
}).catch(() => {
    document.getElementById('machineName').textContent = location.hostname;
});

function showStep(n) {
    for (let i = 0; i < totalSteps; i++) {
        document.getElementById('step-' + i).classList.remove('visible');
        document.querySelectorAll('.step')[i].classList.remove('active');
    }
    document.getElementById('step-' + n).classList.add('visible');
    document.querySelectorAll('.step')[n].classList.add('active');
    for (let i = 0; i < n; i++) {
        document.querySelectorAll('.step')[i].classList.add('done');
    }
    currentStep = n;
}

function nextStep() { if (currentStep < totalSteps - 1) showStep(currentStep + 1); }
function prevStep() { if (currentStep > 0) showStep(currentStep - 1); }

function addPort() {
    const input = document.getElementById('newPort');
    const port = parseInt(input.value);
    if (port && port > 0 && port < 65536) {
        const list = document.getElementById('portList');
        const tag = document.createElement('div');
        tag.className = 'port-tag';
        tag.innerHTML = port + ' <span class="remove" onclick="removePort(this)">×</span>';
        list.appendChild(tag);
        input.value = '';
    }
}

function removePort(el) { el.parentElement.remove(); }

function getPorts() {
    return Array.from(document.querySelectorAll('.port-tag')).map(t => parseInt(t.textContent));
}

function generateCommands() {
    const ports = getPorts();
    const allowFrom = document.getElementById('allowFrom').value;
    const excludeDirs = [document.getElementById('excludeDir1').value, document.getElementById('excludeDir2').value].filter(Boolean);
    const enableBitlocker = document.getElementById('enableBitlocker').checked;
    const networkProfile = document.getElementById('networkProfile').value;
    const dataDir = document.getElementById('dataDir').value;
    const wslInterop = document.getElementById('wslInterop').checked;
    const wslMemory = document.getElementById('wslMemory').value;

    const commands = [];
    const riskIcon = { low: '🟢', medium: '🟠', high: '🔴' };

    // Firewall
    if (detectedPlatform === 'wsl2' || detectedPlatform === 'linux') {
        commands.push({ cat: 'FIREWALL', title: 'Activate UFW', desc: 'Enable firewall with deny incoming.', cmd: 'sudo ufw default deny incoming\\nsudo ufw default allow outgoing\\nsudo ufw enable', risk: 'medium', admin: true, notes: 'Allow SSH port first!' });
        commands.push({ cat: 'FIREWALL', title: 'Allow SSH', desc: 'Allows SSH.', cmd: 'sudo ufw allow 22/tcp', risk: 'low', admin: true });
        ports.forEach(p => {
            const src = allowFrom === 'localhost' ? ' from 127.0.0.1' : allowFrom === 'lan' ? ' from 192.168.0.0/16' : '';
            commands.push({ cat: 'FIREWALL', title: 'Povolit port ' + p, desc: 'TCP port ' + p, cmd: 'sudo ufw allow' + src + ' to any port ' + p + ' proto tcp', risk: 'low', admin: true });
        });
    }
    if (detectedPlatform === 'wsl2' || detectedPlatform === 'windows') {
        ports.forEach(p => {
            let cmd = 'New-NetFirewallRule -DisplayName "UAML port ' + p + '" -Direction Inbound -Protocol TCP -LocalPort ' + p + ' -Action Allow';
            if (allowFrom === 'localhost') cmd += ' -RemoteAddress "127.0.0.1"';
            else if (allowFrom === 'lan') cmd += ' -RemoteAddress "LocalSubnet"';
            commands.push({ cat: 'FIREWALL (Windows)', title: 'Windows Firewall: port ' + p, desc: 'PowerShell rule.', cmd: cmd, risk: 'low', admin: true, notes: 'PowerShell as Administrator.' });
        });
    }

    // AV exclusions
    excludeDirs.forEach(d => {
        if (detectedPlatform === 'wsl2' || detectedPlatform === 'windows') {
            const winPath = d.startsWith('/home/') ? '\\\\\\\\wsl$\\\\Ubuntu' + d : d;
            commands.push({ cat: 'AV EXCLUSIONS', title: 'Windows Defender: ' + d, desc: 'Exclude directory from scanning.', cmd: 'Add-MpPreference -ExclusionPath "' + winPath + '"', risk: 'low', admin: true });
        }
        if (detectedPlatform === 'macos') {
            commands.push({ cat: 'AV EXCLUSIONS', title: 'Spotlight: ' + d, desc: 'Excludes from indexing.', cmd: 'sudo mdutil -i off ' + d + '\\ntouch ' + d + '/.metadata_never_index', risk: 'low', admin: true });
        }
    });

    // WSL2
    if (detectedPlatform === 'wsl2') {
        commands.push({ cat: 'WSL2', title: 'wsl.conf', desc: 'Konfigurace WSL2.', cmd: 'sudo tee /etc/wsl.conf << EOF\\n[automount]\\nenabled = true\\noptions = "metadata,umask=22,fmask=11"\\n[interop]\\nenabled = ' + wslInterop + '\\nEOF', risk: 'medium', admin: true, notes: 'Restart: wsl --shutdown' });
    }

    // BitLocker
    if (enableBitlocker) {
        const vhdPath = document.getElementById('vhdPath').value;
        const vhdSize = document.getElementById('vhdSize').value;
        commands.push({ cat: 'BITLOCKER', title: 'Create VHD', desc: 'Virtual disk for UAML data.', cmd: 'diskpart: create vdisk file="' + vhdPath + '" maximum=' + (vhdSize * 1024) + ' type=expandable', risk: 'medium', admin: true });
        commands.push({ cat: 'BITLOCKER', title: 'Encrypt VHD', desc: 'BitLocker encryption.', cmd: 'Enable-BitLocker -MountPoint "U:" -EncryptionMethod XtsAes256 -PasswordProtector', risk: 'high', admin: true, notes: 'Store the password securely!' });
    }

    // Network
    commands.push({ cat: 'NETWORK', title: 'Network profile: ' + networkProfile, desc: 'Profile setting.', cmd: detectedPlatform === 'windows' || detectedPlatform === 'wsl2' ? 'Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory ' + networkProfile.charAt(0).toUpperCase() + networkProfile.slice(1) : '# Set host: 127.0.0.1 in UAML configuration', risk: 'medium', admin: true });

    // Filesystem
    commands.push({ cat: 'FILES', title: 'Permissions', desc: 'Set correct UAML directory permissions.', cmd: 'chmod 700 ' + dataDir + '\\nchmod 600 ' + dataDir + '/*.db\\nchmod 600 ' + dataDir + '/*.key', risk: 'low', admin: false });

    // Render
    const list = document.getElementById('commandList');
    list.innerHTML = '';
    let lastCat = '';
    commands.forEach((c, i) => {
        if (c.cat !== lastCat) {
            lastCat = c.cat;
            list.innerHTML += '<h3 style="margin:24px 0 12px;color:var(--accent2);">' + c.cat + '</h3>';
        }
        list.innerHTML += '<div class="command-card" id="card-' + i + '"><div class="cmd-header"><span class="cmd-title">' + riskIcon[c.risk] + ' ' + c.title + '</span><span>' + (c.admin ? '<span class="admin-badge">ADMIN</span> ' : '') + '<button class="run-btn" id="run-' + i + '" onclick="runCmd(' + i + ')">▶️ Run</button><button class="copy-btn" onclick="copyCmd(' + i + ')">📋</button></span></div><div class="cmd-desc">' + c.desc + '</div><pre id="cmd-' + i + '">' + c.cmd.replace(/\\n/g, '\\n') + '</pre>' + (c.notes ? '<div class="notes">ℹ️ ' + c.notes + '</div>' : '') + '<div class="exec-result" id="result-' + i + '"></div></div>';
    });

    document.getElementById('outputSection').classList.add('visible');
    document.getElementById('outputSection').scrollIntoView({ behavior: 'smooth' });
    window._commands = commands;
}

function copyCmd(i) {
    const el = document.getElementById('cmd-' + i);
    navigator.clipboard.writeText(el.textContent);
}

function copyAll() {
    if (!window._commands) return;
    const text = window._commands.map(c => '# ' + c.title + '\\n' + c.cmd.replace(/\\\\n/g, '\\n')).join('\\n\\n');
    navigator.clipboard.writeText(text);
}

function downloadScript() {
    if (!window._commands) return;
    let text = '#!/bin/bash\\n# UAML Security Configurator — generated script\\n# ⚠️ READ BEFORE RUNNING!\\n\\n';
    window._commands.forEach(c => { text += '# ' + c.title + '\\n# ' + c.desc + '\\n' + c.cmd.replace(/\\\\n/g, '\\n') + '\\n\\n'; });
    const blob = new Blob([text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'uaml-security-setup.sh';
    a.click();
}

async function runCmd(i) {
    const c = window._commands[i];
    if (!c) return;

    // Confirmation dialog for medium/high risk
    if (c.risk === 'high') {
        if (!confirm('⚠️ HIGH RISK\\n\\n' + c.title + '\\n\\nDo you really want to run this command?')) return;
    } else if (c.risk === 'medium') {
        if (!confirm('🟠 ' + c.title + '\\n\\nDo you want to run this command?')) return;
    }

    const btn = document.getElementById('run-' + i);
    const result = document.getElementById('result-' + i);
    btn.textContent = '⏳ Running...';
    btn.className = 'run-btn running';

    try {
        const cmdText = c.cmd.replace(/\\\\n/g, '\\n');
        const lines = cmdText.split('\\n').filter(l => !l.startsWith('#') && l.trim());
        let allOutput = '';
        let success = true;

        for (const line of lines) {
            const resp = await fetch('/api/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: line, title: c.title, risk: c.risk, requires_admin: c.admin })
            });
            const data = await resp.json();
            if (data.stdout) allOutput += data.stdout + '\\n';
            if (data.stderr) allOutput += data.stderr + '\\n';
            if (!data.success) { success = false; allOutput += '❌ Command failed (code ' + data.returncode + ')\\n'; break; }
        }

        result.textContent = allOutput || (success ? '✅ Hotovo' : '❌ Chyba');
        result.className = 'exec-result visible ' + (success ? 'success' : 'error');
        btn.textContent = success ? '✅ Hotovo' : '❌ Chyba';
        btn.className = 'run-btn ' + (success ? 'done' : 'failed');
    } catch (e) {
        result.textContent = '❌ Error: ' + e.message + '\\n\\nTip: Make sure the server is running (python -c "from uaml.security.configurator import SecurityConfigurator; SecurityConfigurator().serve()")';
        result.className = 'exec-result visible error';
        btn.textContent = '❌ Chyba';
        btn.className = 'run-btn failed';
    }
}

// ── Expert Mode ──
let expertInterval = null;

async function startExpert() {
    const level = document.getElementById('expertLevel').value;
    const duration = parseInt(document.getElementById('expertDuration').value);
    const reason = document.getElementById('expertReason').value;

    if (!confirm('🤖 Allow AI agent ' + (level === 'repair' ? 'REPAIR' : 'DIAGNOSTICS') + ' for ' + duration + ' minutes?\\n\\nAll commands will be logged.')) return;

    try {
        const resp = await fetch('/api/expert/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ access_level: level, duration_minutes: duration, reason: reason })
        });
        const data = await resp.json();
        if (data.error) { alert('Chyba: ' + data.error); return; }

        document.getElementById('expertInactive').style.display = 'none';
        document.getElementById('expertActive').style.display = 'block';
        document.getElementById('expertLevelBadge').textContent = level === 'repair' ? '🔧 OPRAVA' : '🔍 DIAGNOSTIKA';

        // Start timer
        expertInterval = setInterval(updateExpertStatus, 2000);
        updateExpertStatus();
    } catch (e) {
        alert('Chyba: ' + e.message);
    }
}

async function stopExpert() {
    if (!confirm('⛔ Zastavit Expert Mode?')) return;
    try {
        await fetch('/api/expert/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        if (expertInterval) { clearInterval(expertInterval); expertInterval = null; }
        document.getElementById('expertInactive').style.display = 'block';
        document.getElementById('expertActive').style.display = 'none';
        loadAuditTrail();
    } catch (e) { alert('Chyba: ' + e.message); }
}

async function updateExpertStatus() {
    try {
        const resp = await fetch('/api/expert/status');
        const data = await resp.json();
        if (!data.active) {
            if (expertInterval) { clearInterval(expertInterval); expertInterval = null; }
            document.getElementById('expertInactive').style.display = 'block';
            document.getElementById('expertActive').style.display = 'none';
            loadAuditTrail();
            return;
        }
        const s = data.session;
        const mins = Math.floor(s.remaining_seconds / 60);
        const secs = s.remaining_seconds % 60;
        document.getElementById('expertTimer').textContent = '⏱️ ' + mins + ':' + (secs < 10 ? '0' : '') + secs;

        // Update log
        const log = document.getElementById('expertLog');
        if (s.commands.length > 0) {
            log.innerHTML = s.commands.map(c => {
                const icon = c.blocked ? '🚫' : c.executed ? (c.returncode === 0 ? '✅' : '❌') : '⏳';
                const riskIcon = { low: '🟢', medium: '🟠', high: '🔴' }[c.risk];
                let line = '<div style="margin-bottom:8px;border-bottom:1px solid var(--border);padding-bottom:8px;">';
                line += '<span style="color:var(--muted);font-size:0.7rem;">' + c.timestamp.substring(11, 19) + '</span> ';
                line += riskIcon + ' ' + icon + ' <code>' + c.command + '</code>';
                if (c.blocked) line += '<br><span style="color:var(--red);">→ ' + c.block_reason + '</span>';
                if (c.executed && c.result) line += '<br><span style="color:var(--muted);">' + c.result.substring(0, 200) + '</span>';
                line += '</div>';
                return line;
            }).join('');
        }
    } catch (e) { /* ignore poll errors */ }
}

async function loadAuditTrail() {
    try {
        const resp = await fetch('/api/expert/audit');
        const data = await resp.json();
        if (data.sessions && data.sessions.length > 0) {
            const audit = document.getElementById('expertAudit');
            audit.style.display = 'block';
            const log = document.getElementById('expertAuditLog');
            log.innerHTML = data.sessions.map(s => {
                let html = '<div class="command-card"><div class="cmd-header"><span class="cmd-title">' + s.session_id + '</span><span class="admin-badge">' + s.access_level.toUpperCase() + '</span></div>';
                html += '<div class="cmd-desc">Commands: ' + s.commands_executed + ' executed, ' + s.commands_blocked + ' blocked of ' + s.commands_total + ' total</div>';
                if (s.reason) html += '<div class="notes">Reason: ' + s.reason + '</div>';
                html += '</div>';
                return html;
            }).join('');
        }
    } catch (e) { /* ignore */ }
}

// History functions
async function refreshHistory() {
    try {
        const resp = await fetch('/api/history');
        const data = await resp.json();
        if (data.executions && data.executions.length > 0) {
            const section = document.getElementById('historySection');
            section.style.display = 'block';
            const log = document.getElementById('historyLog');
            const riskIcon = { low: '🟢', medium: '🟠', high: '🔴' };
            log.innerHTML = data.executions.map((e, i) => {
                const ts = e.timestamp.substring(0, 19).replace('T', ' ');
                const icon = e.success ? '✅' : '❌';
                return '<div class="command-card"><div class="cmd-header"><span class="cmd-title">' + (riskIcon[e.risk]||'⚪') + ' ' + e.title + '</span><span style="color:var(--muted);font-size:0.8rem;">' + ts + '</span></div><div class="cmd-desc">' + icon + ' Code: ' + e.returncode + (e.requires_admin ? ' | 🔑 Admin' : '') + '</div><pre style="font-size:0.75rem;max-height:100px;overflow:auto;">' + e.command + '</pre>' + (e.output ? '<div style="font-size:0.75rem;color:var(--muted);margin-top:4px;max-height:60px;overflow:auto;">' + e.output.substring(0, 200) + '</div>' : '') + '</div>';
            }).join('');
        }
    } catch (e) { /* ignore */ }
}

function downloadReport() {
    const a = document.createElement('a');
    a.href = '/api/report';
    a.download = 'uaml-security-report.html';
    a.click();
}

function copyHistory() {
    fetch('/api/report.json').then(r => r.json()).then(data => {
        const text = data.executions.map(e => e.timestamp.substring(0,19) + ' | ' + e.title + ' | ' + (e.success ? 'OK' : 'FAIL') + ' | ' + e.command).join('\\n');
        navigator.clipboard.writeText(text);
    });
}

// Auto-refresh history after each command execution
const origRunCmd = runCmd;
runCmd = async function(i) { await origRunCmd(i); setTimeout(refreshHistory, 500); };

// Load audit trail on page load
setTimeout(loadAuditTrail, 1000);
setTimeout(refreshHistory, 1500);

async function runAll() {
    if (!window._commands) return;
    if (!confirm('Run ALL commands sequentially?\\n\\nEach result will be shown.')) return;
    for (let i = 0; i < window._commands.length; i++) {
        await runCmd(i);
        await new Promise(r => setTimeout(r, 500)); // pause between commands
    }
}

// ── Folder Access Manager ──
async function scanFolder() {
    const path = document.getElementById('folderPath').value;
    const res = await fetch('/api/folders/list?path=' + encodeURIComponent(path));
    const data = await res.json();
    const el = document.getElementById('folderContents');
    if (data.error) { el.innerHTML = '<p style="color:var(--red);">' + data.error + '</p>'; return; }
    let html = '<table style="width:100%;font-size:0.85rem;"><thead><tr><th>Name</th><th>Type</th><th>Permissions</th><th>Owner</th><th>Size</th></tr></thead><tbody>';
    (data.entries || []).forEach(e => {
        const click = e.type === 'dir' ? ' style="cursor:pointer;color:var(--blue);" onclick="document.getElementById(&apos;folderPath&apos;).value=&apos;' + e.path.replace(/'/g,"&apos;") + '&apos;;scanFolder()"' : '';
        html += '<tr><td' + click + '>' + (e.type === 'dir' ? '📁 ' : '📄 ') + e.name + '</td><td>' + e.type + '</td><td><code>' + (e.mode||'?') + '</code></td><td>' + (e.owner||'?') + '</td><td>' + (e.size||'') + '</td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

async function loadManagedFolders() {
    const res = await fetch('/api/folders/managed');
    const data = await res.json();
    const el = document.getElementById('managedFoldersList');
    if (!data.folders || data.folders.length === 0) { el.innerHTML = '<p style="color:var(--muted);">No managed folders yet.</p>'; return; }
    let html = '<table style="width:100%;font-size:0.85rem;"><thead><tr><th>Path</th><th>Target</th><th>Current</th><th>Status</th><th></th></tr></thead><tbody>';
    data.folders.forEach(f => {
        const status = f.current_mode === f.target_mode ? '<span style="color:var(--green);">✅ OK</span>' : '<span style="color:var(--yellow);">⚠️ Drift</span>';
        html += '<tr><td>' + f.path + '</td><td><code>' + f.target_mode + '</code></td><td><code>' + (f.current_mode||'?') + '</code></td><td>' + status + '</td><td><button class="btn-danger" style="padding:2px 8px;font-size:0.75rem;" onclick="removeManagedFolder(' + f.id + ')">✕</button></td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

async function addManagedFolder() {
    const path = document.getElementById('addFolderPath').value;
    const target = document.getElementById('addFolderTarget').value;
    if (!path) { alert('Enter a folder path'); return; }
    const res = await fetch('/api/folders/add', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path, target_mode: target}) });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    document.getElementById('addFolderPath').value = '';
    loadManagedFolders();
    loadFolderAudit();
}

async function removeManagedFolder(id) {
    if (!confirm('Remove this folder from managed list?')) return;
    await fetch('/api/folders/remove', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id}) });
    loadManagedFolders();
}

async function loadFolderAudit() {
    const res = await fetch('/api/folders/audit');
    const data = await res.json();
    const el = document.getElementById('folderAuditLog');
    if (!data.entries || data.entries.length === 0) { el.innerHTML = '<p style="color:var(--muted);">No audit entries yet.</p>'; return; }
    let html = '<table style="width:100%;font-size:0.8rem;"><thead><tr><th>Time</th><th>Action</th><th>Path</th><th>Details</th></tr></thead><tbody>';
    data.entries.slice(0,20).forEach(e => {
        html += '<tr><td>' + e.ts + '</td><td>' + e.action + '</td><td>' + e.path + '</td><td>' + (e.details||'') + '</td></tr>';
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

// Load folder data when step 7 is shown
const origShowStep = showStep;
showStep = function(n) {
    origShowStep(n);
    if (n === 6) { loadManagedFolders(); loadFolderAudit(); }
};

// Initialize
showStep(0);
</script>
</body>
</html>"""
