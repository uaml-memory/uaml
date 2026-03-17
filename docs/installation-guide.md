# UAML v1.0 — Installation Guide for Testers

> Step-by-step guide for first testers. Current state as of March 2026.

## Requirements

- **Python 3.10+** (tested on 3.12)
- **pip** (Python package manager)
- **OS:** Linux, Windows (WSL2 recommended), macOS
- **Disk:** ~50 MB for UAML + SQLite database
- **RAM:** ~100 MB runtime (more for voice pipeline)

## Step 1: Install UAML

```bash
# Install from source (current method)
git clone https://github.com/uaml/uaml.git
cd uaml
pip install -e .

# Or when published to PyPI:
# pip install uaml
```

## Step 2: Initialize Database

```bash
# Create the UAML database
python3 -c "from uaml.core.store import MemoryStore; MemoryStore(); print('✅ Database created')"
```

This creates `~/.uaml/uaml.db` (SQLite).

## Step 3: Verify Installation

```bash
# Run all tests
python3 -m pytest tests/ -q

# Expected: 1117 passed

# Quick smoke test
python3 -c "
from uaml.facade import UAML
uaml = UAML()
uaml.learn('Test entry — UAML installation successful')
results = uaml.search('installation')
print('✅ UAML works!' if results else '❌ Something wrong')
"
```

## Step 4: Start Services

### UAML API Server (port 8780)
```bash
python3 -c "from uaml.api.server import serve; serve()" &
# → http://127.0.0.1:8780
```

### UAML Web Dashboard (port 8781)
```bash
python3 -c "from uaml.web.app import serve; serve()" &
# → http://127.0.0.1:8781
```

### Security Configurator (port 8785)
```bash
python3 -c "from uaml.security.configurator import SecurityConfigurator; SecurityConfigurator().serve()" &
# → http://127.0.0.1:8785
```

Open in browser: `http://127.0.0.1:8785`

## Step 5: Security Configurator (Recommended)

1. Open `http://127.0.0.1:8785` in your browser
2. The wizard detects your OS automatically
3. Follow 6 steps:
   - **Firewall** — configure rules for UAML ports
   - **AV Exclusions** — exclude `~/.uaml` from scanning
   - **Encryption** — BitLocker VHD (Windows only)
   - **WSL2** — network config (Windows only)
   - **Filesystem** — restrict permissions on data dirs
   - **Review** — see all commands, click ▶️ Apply
4. Each command shows risk level (🟢/🟠/🔴)
5. Download audit report for documentation

## Using the Facade API

```python
from uaml.facade import UAML

uaml = UAML()

# Store knowledge
uaml.learn("Python 3.13 removed the GIL", topic="python")

# Search
results = uaml.search("Python threading")
for r in results:
    print(f"[{r.score:.2f}] {r.entry.content}")

# Audit
report = uaml.audit_report()

# Stats
stats = uaml.stats()
print(f"Total entries: {stats['knowledge']}")
```

## Available Modules by Tier

### Community (Free)
- `uaml.core.store` — MemoryStore (SQLite)
- `uaml.core.schema` — 5-layer architecture
- `uaml.core.policy` — Query classification
- `uaml.core.config` — Configuration management
- `uaml.crypto.pqc` — Post-quantum encryption
- `uaml.facade` — Unified API
- `uaml.cli` — Command-line interface

### Starter (€8/mo)
- Everything in Community, plus:
- `uaml.compliance.*` — Auditor, Consent, DPIA, Inventory
- `uaml.api.*` — REST API server + client
- `uaml.security.configurator` — Security Configurator

### Professional (€29/mo)
- Everything in Starter, plus:
- `uaml.voice.*` — TTS + STT pipeline
- `uaml.security.configurator.ExpertMode` — Expert on Demand
- `uaml.graph.*` — Knowledge graph
- `uaml.federation.*` — Multi-agent sharing
- `uaml.reasoning.*` — Temporal, context, scoring, clustering

### Team (€190/mo)
- Everything in Professional, plus:
- Up to 5 AI agents
- `uaml.graph.sync` — Neo4j synchronization
- `uaml.security.rbac` — Role-based access control
- `uaml.audit.*` — Full audit trail + provenance

### Enterprise (Custom)
- Everything in Team, unlimited agents
- Key escrow, FIDO2, DPIA tools
- On-premise deployment, SLA

## Ports Summary

| Service | Port | URL |
|---------|------|-----|
| UAML API | 8780 | http://127.0.0.1:8780 |
| UAML Dashboard | 8781 | http://127.0.0.1:8781 |
| Security Configurator | 8785 | http://127.0.0.1:8785 |

## Troubleshooting

### Port already in use
```bash
# Check what's using the port
ss -tlnp | grep 8785
# Kill the process
kill <PID>
```

### Database locked
```bash
# Only one process should write at a time
# Check for running UAML processes
ps aux | grep uaml
```

### Windows / WSL2
- Ports are auto-forwarded from WSL2 to Windows
- Open `http://localhost:8785` in Windows browser
- If not working, check: `wsl --list --verbose`

### Raspberry Pi
- Tested on Pi 4 (4GB RAM)
- Voice pipeline: use Piper TTS + Whisper.cpp (lightweight)
- SQLite works great on ARM

## Reporting Issues

Email: support@uaml.ai

Include:
- OS and Python version
- Error message / traceback
- Steps to reproduce

---

*© 2026 GLG, a.s. — UAML v1.0*
