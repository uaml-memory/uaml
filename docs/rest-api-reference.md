# UAML REST API Reference

> © 2026 GLG, a.s. | UAML v1.0 | Status: DRAFT

## Overview

The UAML dashboard exposes a REST API on port 8780 (default). All endpoints return JSON. No authentication required for local access.

## System & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/system` | System info (version, uptime, Python, OS) |
| GET | `/api/health` | Health check |
| GET | `/api/stats` | Database statistics (memories, sources, layers) |

## Knowledge Graph

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/knowledge` | All memories (with pagination: `?limit=&offset=`) |
| GET | `/api/knowledge/<id>` | Single memory entry |
| POST | `/api/knowledge` | Store new memory (body: `{content, source, ...}`) |

## Focus Engine (v1 API)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/focus-config` | Current focus configuration |
| PUT | `/api/v1/focus-config` | Update focus configuration |
| GET | `/api/v1/focus-config/presets` | Built-in presets list |
| POST | `/api/v1/focus-recall` | Execute focus recall (body: `{query, budget, tier}`) |

### Saved Configurations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/saved-configs?filter_type=input\|output` | List saved configs |
| GET | `/api/v1/saved-configs/<name>` | Get config by name |
| POST | `/api/v1/saved-configs` | Save config (body: `{name, config, filter_type, description}`) |
| POST | `/api/v1/saved-configs/load` | Load config (body: `{name, filter_type}`) |
| POST | `/api/v1/saved-configs/delete` | Delete config (body: `{name, filter_type}`) |
| POST | `/api/v1/saved-configs/activate` | Set active config (body: `{name, filter_type}`) |
| GET | `/api/v1/active-config?filter_type=input\|output` | Get active config name |

### Rules Changelog

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/rules-log?limit=50&offset=0` | Audit trail entries |
| GET | `/api/v1/rules-log/stats` | Changelog statistics |

## Data & Reasoning

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tasks` | Tasks from knowledge graph |
| GET | `/api/timeline` | Timeline events |
| GET | `/api/layers` | Data layer breakdown |
| GET | `/api/reasoning` | Reasoning trace entries |
| GET | `/api/compliance` | Compliance status |

## Projects & Team

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects` | All projects |
| GET | `/api/projects/<id>` | Single project detail |
| GET | `/api/infrastructure` | Infrastructure entries |
| GET | `/api/team` | Team members |
| GET | `/api/languages` | Available languages |

## Configuration & Summaries

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Current UAML configuration |
| GET | `/api/summaries?kind=daily\|weekly&limit=10` | Summary index |

## Response Format

All endpoints return JSON:

```json
{
  "field": "value",
  ...
}
```

Error responses:
```json
{
  "error": "description"
}
```

HTTP status codes: `200` OK, `400` Bad Request, `404` Not Found, `500` Internal Error.

## MCP Tools (via MCP bridge)

9 tools available through the MCP protocol:

| Tool | Description |
|------|-------------|
| `memory_store` | Store a memory entry |
| `memory_recall` | Recall memories by query |
| `memory_focus_recall` | Token-budgeted recall with Focus Engine |
| `memory_search` | Full-text search |
| `memory_forget` | Soft-delete a memory |
| `memory_stats` | Database statistics |
| `memory_health` | Health check |
| `memory_export` | Export memories |
| `memory_import` | Import memories |

## Dashboard Pages

| Route | Template | Description |
|-------|----------|-------------|
| `/` | `index.html` | Main dashboard |
| `/input-filter` | `input-filter.html` | Input filter configuration |
| `/output-filter` | `output-filter.html` | Output filter / Focus Engine config |
| `/rules-log` | `rules-log.html` | Rules change audit trail |
