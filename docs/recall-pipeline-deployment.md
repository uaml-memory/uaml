# UAML Recall Pipeline — Deployment Guide

> Deployed: 2026-03-15 | Status: Production | Nodes: Cyril (Notebook1), Metod (VPS)

## Architecture Overview

```
OpenClaw Session Logs (*.jsonl)
        │
        ▼
┌─────────────────────────┐
│  Bridge                 │  tools/uaml_openclaw_bridge.py
│  ├─ Noise filter        │  skips OK / NO_REPLY / HEARTBEAT_OK
│  ├─ PII detection       │  >3 PII = reject, ≤3 = tag
│  └─ Category classifier │  9 keyword categories
└─────────┬───────────────┘
          ▼
    data/memory.db (SQLite, FTS5)
          │
    ┌─────┴─────┐
    ▼           ▼
┌────────┐  ┌──────────────┐
│ MCP    │  │ Focus Engine  │  uaml/core/focus_engine.py
│ Server │  │ (output filter)│
│ :8770  │  └──────────────┘
└────────┘
    │
    ▼
┌────────────────┐
│ SyncEngine     │  uaml/sync.py
│ JSONL via git  │
└────────────────┘
```

### Components

| Component | File | Purpose |
|-----------|------|---------|
| **Bridge** | `tools/uaml_openclaw_bridge.py` | Ingests assistant messages from session logs into `data/memory.db` |
| **MCP Server** | `tools/uaml_mcp_server.py` | Exposes `memory_search` tool via MCP protocol (SSE, port 8770) |
| **Focus Engine** | `uaml/core/focus_engine.py` | Filters results by sensitivity, relevance, temporal decay, dedup, token budget |
| **SyncEngine** | `uaml/sync.py` | JSONL-based knowledge sync between nodes via git |
| **Fallback** | `tools/uaml_recall.sh` | Direct FTS search when MCP is unavailable |

### Input Filters (Bridge)

1. **Noise filter** — skips messages matching `OK`, `NO_REPLY`, `HEARTBEAT_OK`
2. **PII detection** — scans for personal data patterns; >3 PII hits = reject entire message, ≤3 = tag and ingest
3. **Category classifier** — keyword-based, assigns one of 9 categories:
   `decision`, `infrastructure`, `code`, `security`, `research`, `product`, `legal`, `communication`, `process`

## Per-Node Setup

Each agent node runs three services:

1. **Local bridge** (watch mode) — monitors own session logs, fills local `data/memory.db`
2. **Local MCP server** — serves recall tools to the agent via MCP protocol
3. **SyncEngine** — exports/imports factual knowledge as JSONL changelogs via git

## Systemd Services (user-level)

### uaml-bridge.service

```ini
[Unit]
Description=UAML Bridge — session log ingestion
After=network.target

[Service]
Type=simple
Environment=UAML_DB=%h/.openclaw/workspace/data/memory.db
Environment=UAML_AGENT=Cyril
ExecStart=/usr/bin/python3 %h/.openclaw/workspace/tools/uaml_openclaw_bridge.py --watch
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### uaml-mcp.service

```ini
[Unit]
Description=UAML MCP Server — recall search via SSE
After=network.target uaml-bridge.service

[Service]
Type=simple
Environment=UAML_DB=%h/.openclaw/workspace/data/memory.db
Environment=UAML_AGENT=Cyril
ExecStart=/usr/bin/python3 %h/.openclaw/workspace/tools/uaml_mcp_server.py --port 8770
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### Management

```bash
systemctl --user enable uaml-bridge.service uaml-mcp.service
systemctl --user start uaml-bridge.service uaml-mcp.service
systemctl --user status uaml-bridge.service uaml-mcp.service
journalctl --user -u uaml-mcp.service -f   # live logs
```

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `UAML_DB` | Yes | Path to `memory.db` | `~/.openclaw/workspace/data/memory.db` |
| `UAML_AGENT` | Yes | Agent name for record attribution | `Cyril`, `Metod` |
| `UAML_NODE_ID` | For sync | Node identifier for SyncEngine | `notebook1`, `vps` |

## SOUL.md Integration — Recall Protocol

Agents follow a three-tier recall mechanism (defined in SOUL.md):

1. **Try `memory_search`** (OpenClaw built-in) — searches markdown files
2. **Query `data/memory.db` via MCP** — structured knowledge with categories and confidence
   ```bash
   curl -s -X POST http://localhost:8770/message \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_search","arguments":{"query":"QUERY","limit":5}}}'
   ```
3. **Fallback script** (if MCP fails) — direct FTS search + report the issue
   ```bash
   tools/uaml_recall.sh "QUERY" 5
   ```

**Rule:** Never say "I don't know" before searching all three tiers.

## Data Schema

The `knowledge` table in `memory.db`:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key (autoincrement) |
| `ts` | TEXT | ISO 8601 timestamp |
| `agent` | TEXT | Source agent name |
| `topic` | TEXT | Extracted topic |
| `summary` | TEXT | One-line summary |
| `content` | TEXT | Full message content (FTS-indexed) |
| `category` | TEXT | One of 9 categories |
| `tags` | TEXT | Comma-separated tags |
| `confidence` | REAL | 0.0–1.0 confidence score |
| `source_type` | TEXT | Origin type (`session`, `sync`, `manual`) |
| `source_ref` | TEXT | Source file path or reference |

## Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| Bridge processes assistant messages only | User messages not indexed | Manual ingestion if needed |
| Keyword-based category classifier | No semantic understanding | Sufficient for current 9-category taxonomy |
| FTS search is lexical only | No semantic/vector search | Multiple query reformulations |
| PQC signing not active | `pqcrypto` library missing | Planned for future release |
| SyncEngine full export ~177MB | Large initial transfer | Use `scp` for first sync, git for deltas only |
