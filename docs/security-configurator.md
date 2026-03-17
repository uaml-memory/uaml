# Security Configurator

> The missing piece: a GUI tool for hardening the environment where your AI agent runs.

## Overview

UAML Security Configurator is a **web-based wizard** that guides users through securing their operating system for AI agent deployment. No CLI knowledge required — everything is point-and-click.

**Key principle:** The configurator runs **locally only** (`127.0.0.1:8785`). It never exposes itself to the network. AI agents cannot access it — security decisions are always made by humans.

## Features

### 🔥 Firewall Configuration
- **Linux:** UFW, iptables
- **Windows:** Windows Firewall (netsh)
- **macOS:** pf (packet filter)

Generates and executes firewall rules to protect UAML ports and data directories.

### 🛡️ Antivirus Exclusions
- **Windows Defender** — PowerShell-based exclusion management
- **macOS Spotlight** — mdutil exclusions
- **Linux ClamAV** — clamd configuration

Excludes UAML data directories (`~/.uaml`, `~/.openclaw`) from scanning to prevent performance issues and false positives.

### 🔐 BitLocker VHD Encryption
- Creates encrypted virtual hard disks (VHD) for UAML data
- XTS-AES-256 encryption
- Recovery key management
- Windows-only feature

### 🌐 WSL2 Configuration
- Network isolation settings
- Firewall rules for WSL2 ↔ host communication
- DNS configuration

### 📁 Filesystem Hardening
- Sets restrictive permissions on UAML directories
- Linux: `chmod 700` on data directories
- Windows: ACL configuration

### 🔌 Network Profile
- Configures network interface settings
- Disables unnecessary services
- Sets appropriate firewall zones

## Quick Start

```python
from uaml.security.configurator import SecurityConfigurator

# Start the web UI
cfg = SecurityConfigurator()
cfg.serve()  # → http://127.0.0.1:8785

# Or use programmatically
commands = cfg.generate_commands()
for cmd in commands:
    print(f"{cmd.title}: {cmd.command}")
```

## Web UI Wizard

The wizard guides you through 6 steps:

1. **Platform Detection** — automatically detects your OS
2. **Firewall Rules** — configure ports and access rules
3. **AV Exclusions** — exclude UAML dirs from scanning
4. **Encryption** — set up BitLocker VHD (Windows)
5. **WSL2 Setup** — configure WSL2 networking (Windows)
6. **Review & Apply** — see all commands, execute with one click

Each command shows:
- Risk level (🟢 Low / 🟠 Medium / 🔴 High)
- Whether admin privileges are required
- Confirmation dialog for medium/high risk actions

## One-Click Execution

Commands execute directly on your machine via the ▶️ **Spustit** (Apply) button. No copy-paste, no script downloads. Results appear inline:
- ✅ Success — with command output
- ❌ Error — with error details and suggestions

## Expert Mode (Expert on Demand)

Temporarily grant your AI agent **controlled, audited access** to the host OS.

### How It Works

1. **Start a session** — choose access level (DIAGNOSTIC or REPAIR)
2. **Set time limit** — 1 to 60 minutes maximum
3. **AI executes commands** — only whitelisted commands allowed
4. **Full audit trail** — every command logged with timestamp, result, risk level
5. **Kill switch** — terminate the session at any time

### Access Levels

| Level | Allowed Commands | Use Case |
|-------|-----------------|----------|
| DIAGNOSTIC | `ls`, `cat`, `grep`, `systemctl status`, `ufw status`, `df`, `free`, `ps`, `netstat`, `ip`, `ping`, `dig` | Read-only system inspection |
| REPAIR | All diagnostic + `ufw allow/deny`, `chmod`, `chown`, `systemctl start/stop/restart`, `tee /etc/` | Fix configuration issues |

### Blocked Commands (Always)

These commands are **always blocked**, regardless of access level:
- `rm -rf /`, `mkfs`, `dd if=`, `format`
- `passwd`, `useradd`, `userdel`, `usermod`
- `shutdown`, `reboot`, `init 0`, `halt`
- `curl | bash`, `wget | bash`

### Security Guarantees

- **Time-limited** — sessions auto-expire (max 60 minutes)
- **Command whitelist** — only pre-approved commands execute
- **User approval** — every command requires approval callback
- **Kill switch** — instant session termination
- **Full audit trail** — exportable as HTML/JSON report

## Audit Reports

Every executed command is logged. Generate reports for:
- IT department audits
- Management documentation
- Compliance (ISO 27001, GDPR)
- Personal record-keeping

### Report Formats

- **HTML** — printable, professional layout with summary statistics
- **JSON** — machine-readable for integration with other tools

### Report Contents

| Field | Description |
|-------|-------------|
| Timestamp | When the command was executed |
| Title | Human-readable action name |
| Command | Exact command that was run |
| Risk Level | 🟢 Low / 🟠 Medium / 🔴 High |
| Result | Success/failure + exit code |
| Output | Command stdout/stderr (truncated to 5KB) |
| Executor | Always "user" (or "expert" for Expert Mode) |
| Platform | Detected OS |

### Accessing Reports

```
# Via Web UI
Click "📄 Otevřít HTML report" or "💾 Stáhnout report"

# Via API
GET http://127.0.0.1:8785/api/report        → HTML report
GET http://127.0.0.1:8785/api/report.json    → JSON report
GET http://127.0.0.1:8785/api/history        → Raw execution log
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/platform` | GET | Detected platform info |
| `/api/generate` | GET | Generated commands for current platform |
| `/api/execute` | POST | Execute a command |
| `/api/history` | GET | Execution history log |
| `/api/report` | GET | HTML audit report |
| `/api/report.json` | GET | JSON audit report |
| `/api/expert/start` | POST | Start Expert Mode session |
| `/api/expert/stop` | POST | Stop Expert Mode session |
| `/api/expert/execute` | POST | Execute command in Expert Mode |
| `/api/expert/status` | GET | Current Expert Mode session status |
| `/api/expert/audit` | GET | Expert Mode audit trail |

## Architecture

```
┌─────────────────────────────────────────┐
│            Web Browser (localhost)        │
│  ┌─────────────────────────────────────┐ │
│  │     6-Step Wizard UI (Dark Theme)   │ │
│  │  ┌──────┬──────┬──────┬──────────┐  │ │
│  │  │ FW   │ AV   │ Enc  │ Expert   │  │ │
│  │  └──────┴──────┴──────┴──────────┘  │ │
│  │     ▶️ Execute  │  📄 Report        │ │
│  └─────────────────────────────────────┘ │
└──────────────────┬──────────────────────┘
                   │ HTTP (127.0.0.1:8785)
┌──────────────────┴──────────────────────┐
│         SecurityConfigurator             │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Command    │  │   ExpertMode      │  │
│  │ Generator  │  │  ┌─────────────┐  │  │
│  │            │  │  │ Whitelist   │  │  │
│  │ Platform   │  │  │ Blacklist   │  │  │
│  │ Detection  │  │  │ Kill Switch │  │  │
│  └────────────┘  │  │ Audit Trail │  │  │
│                  │  └─────────────┘  │  │
│  ┌────────────┐  └───────────────────┘  │
│  │ Execution  │                         │
│  │ Logger     │  → HTML/JSON Reports    │
│  └────────────┘                         │
└──────────────────────────────────────────┘
                   │
        subprocess.run() (local OS)
```

## USP (Unique Selling Point)

> **From firewall setup to post-quantum encryption — one product for the entire security lifecycle of an AI agent.**

Unlike traditional security tools that offer all-or-nothing AI access, UAML provides:
- **Controlled transparency** — every action visible, logged, exportable
- **Graduated access** — diagnostic vs. repair levels
- **Time-limited sessions** — no permanent elevated access
- **Human-in-the-loop** — approval required for every action

## Requirements

- Python 3.10+
- No external dependencies (uses `http.server` from stdlib)
- Admin/root privileges for some operations (marked in UI)

---

*© 2026 GLG, a.s. — UAML Security Configurator v1.0*
