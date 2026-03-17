# UAML API Quick Reference

> © 2026 GLG, a.s. | v1.0

## Python Facade

```python
from uaml.facade import UAML
uaml = UAML()

uaml.learn(content, topic=None, source_type=None, confidence=0.8)
uaml.search(query, limit=10, topic=None)          # → list[MemoryEntry]
uaml.recall(query, budget_tokens=500)              # Starter+ (Focus Engine)
uaml.apply_preset("conservative"|"standard"|"research")  # Starter+
uaml.audit_report()                                # → dict
uaml.export(path, format="jsonl")                  # Professional+
uaml.import_data(path)                             # Professional+
```

## REST API (port 8780)

### Core

```
GET  /api/health                          → system health
GET  /api/stats                           → {memories, sources, layers}
GET  /api/knowledge?limit=N&offset=M      → list memories
GET  /api/knowledge/<id>                  → single entry
POST /api/knowledge                       → store {content, source, topic, confidence}
```

### Focus Engine

```
GET  /api/v1/focus-config                 → current config
PUT  /api/v1/focus-config                 → update config / apply preset
GET  /api/v1/focus-config/presets         → available presets
POST /api/v1/focus-recall                 → {query, budget, tier} → filtered context
```

### Saved Configs (Professional+)

```
GET  /api/v1/saved-configs?filter_type=input|output
POST /api/v1/saved-configs                → {name, config, filter_type, description}
POST /api/v1/saved-configs/load           → {name, filter_type}
POST /api/v1/saved-configs/activate       → {name, filter_type}
POST /api/v1/saved-configs/delete         → {name, filter_type}
```

### Audit

```
GET  /api/v1/rules-log?limit=50&offset=0  → rules changelog
GET  /api/v1/rules-log/stats              → changelog statistics
```

### Coordination (Team+)

```
GET  /api/v1/coordination/rules           → orchestration rules
GET  /api/v1/coordination/events          → active events
GET  /api/v1/coordination/trust?channel=X → trust level
POST /api/v1/coordination/sanitize        → sanitize untrusted input
```

## MCP Tools (port 8770)

| Tool | Args | Returns |
|------|------|---------|
| `memory_store` | `{content, topic?, source?, confidence?}` | `{id, status}` |
| `memory_recall` | `{query, limit?}` | `[{content, confidence, ts}]` |
| `memory_search` | `{query, limit?, topic?}` | `[{content, score}]` |
| `memory_focus_recall` | `{query, budget?, tier?}` | `{context, tokens_used}` |
| `memory_forget` | `{id}` | `{status}` |
| `memory_stats` | `{}` | `{total, by_topic, by_source}` |
| `memory_health` | `{}` | `{status, db_size, uptime}` |
| `memory_export` | `{format?, path?}` | `{path, count}` |
| `memory_import` | `{path}` | `{imported, skipped}` |

## Response Format

```json
{"field": "value"}           // success
{"error": "description"}     // error (400/404/500)
```

## CLI

```bash
uaml learn "content"         uaml search "query"
uaml recall "query" -b 500   uaml stats
uaml export -o file.jsonl    uaml import -f file.jsonl
uaml health                  uaml guide
uaml config show             uaml license status
```
