# Focus Engine — Implementation Reference

> © 2026 GLG, a.s. | UAML v1.0 | Status: DRAFT

## Overview

The Focus Engine controls what data enters and leaves the UAML knowledge graph. It consists of:

1. **Input Filter** (`uaml.ingest.filters`) — 6 filter stages before data storage
2. **Output Filter / Focus Engine** (`uaml.core.focus_engine`) — token-budgeted recall
3. **Configuration** (`uaml.core.focus_config`) — YAML/JSON config with validation and presets
4. **Rules Changelog** (`uaml.core.rules_changelog`) — SQLite audit trail for all config changes
5. **Saved Config Store** (`uaml.core.focus_config.SavedConfigStore`) — named config snapshots

## Architecture

```
Data In → [Input Filter Pipeline] → Neo4j/SQLite
                                        ↓
Agent Query → [Focus Engine] → Filtered Context → Agent
                   ↑
            FocusEngineConfig (YAML)
                   ↑
            Rules Changelog (SQLite audit)
```

## Input Filter (`uaml.ingest.filters`)

6 sequential filter stages applied to incoming data:

| Stage | Function | Purpose |
|-------|----------|---------|
| 1 | `create_length_filter` | Reject entries below `min_entry_length` chars |
| 2 | `create_max_tokens_filter` | Reject entries above `max_entry_tokens` tokens |
| 3 | `create_pii_detector` | Detect PII (emails, phones, IDs, credit cards) |
| 4 | `create_category_filter` | Enforce per-category policies (allow/deny/encrypt/require_consent) |
| 5 | `create_rate_limit_filter` | Token-bucket rate limiting (`rate_limit_per_min`) |
| 6 | `create_relevance_gate` | Reject below `min_relevance_score` threshold |

### PII Detection (`detect_pii`)

Returns `PIIDetectionResult` with:
- `has_pii: bool`
- `pii_types: list[str]` — detected types (email, phone, czech_id, credit_card, ip_address)
- `details: list[dict]` — type + masked value

### Setup

```python
from uaml.ingest.filters import setup_input_filter
from uaml.core.focus_config import FocusEngineConfig

config = FocusEngineConfig()
setup_input_filter(pipeline, config)
```

## Output Filter / Focus Engine (`uaml.core.focus_engine`)

### Key Classes

**`RecallCandidate`** — Input to the engine:
- `content: str` — full text
- `summary: str` — compressed version
- `relevance_score: float` — 0.0–1.0
- `timestamp: datetime` — creation time
- `source: str` — origin identifier
- `token_count: int` — estimated tokens

**`RecallDecision`** — Output per candidate:
- `candidate: RecallCandidate`
- `included: bool`
- `selected_content: str` — full or summary
- `adjusted_score: float` — after temporal decay
- `token_cost: int`

**`FocusResult`** — Aggregated result:
- `decisions: list[RecallDecision]`
- `total_tokens: int`
- `budget_remaining: int`
- `utilization_pct: float` — property

**`FocusEngine`** — Main processor:

```python
engine = FocusEngine(config)
result = engine.process(candidates, query="search term")
```

### Processing Pipeline

1. Filter by `min_relevance_score`
2. Apply temporal decay (`temporal_decay_factor`, `temporal_decay_halflife_days`)
3. Sort by adjusted score (descending)
4. Limit to `max_records`
5. Select content by recall tier (1=summary preferred, 2=mixed, 3=full)
6. Deduplicate by `dedup_similarity` threshold
7. Fill token budget (`token_budget_per_query`)

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `token_budget_per_query` | 2000 | Max tokens per recall |
| `min_relevance_score` | 0.3 | Minimum relevance threshold |
| `max_records` | 10 | Max entries returned |
| `temporal_decay_factor` | 0.5 | Decay strength |
| `temporal_decay_halflife_days` | 30 | Half-life for decay |
| `dedup_similarity` | 0.85 | Dedup threshold |
| `recall_tier` | 1 | 1=summaries, 2=mixed, 3=full |
| `sensitivity_threshold` | 3 | Sensitivity level filter |
| `compress_above_tokens` | 500 | Auto-compress threshold |
| `summary_preference` | 0.8 | Summary vs full weight |
| `max_context_percentage` | 30 | Max % of model context |

## Configuration (`uaml.core.focus_config`)

### Config Structure

```yaml
version: "1.0"
input_filter:
  min_relevance_score: 0.7
  dedup_threshold: 0.95
  max_entry_tokens: 2000
  ttl_days: 730
  min_entry_length: 10
  require_classification: true
  pii_detection: true
  rate_limit_per_min: 100
  categories:
    personal: require_consent
    financial: encrypt
    health: deny
    company: allow
    public: allow
    communication: encrypt

output_filter:
  token_budget_per_query: 2000
  min_relevance_score: 0.3
  max_records: 10
  temporal_decay_factor: 0.5
  recall_tier: 1
  # ... (see full params above)

agent_rules:
  prefer_summaries_first: true
  lazy_loading: true
  report_token_usage: true
  budget_aware: true
  deduplicate_context: true
  prefer_fresh_data: true
  never_expose_rules: true
  never_bypass_filter: true
  log_all_recalls: true
```

### Built-in Presets

| Preset | Token Budget | Max Records | Relevance | Tier | Use Case |
|--------|-------------|-------------|-----------|------|----------|
| `conservative` | 1500 | 5 | 0.5 | 1 | Production, cost-sensitive |
| `standard` | 2000 | 10 | 0.3 | 1 | General use |
| `research` | 8000 | 25 | 0.2 | 3 | Deep analysis |

### API Functions

```python
from uaml.core.focus_config import (
    load_focus_config,    # Load from YAML/JSON file
    save_focus_config,    # Save to YAML/JSON file
    load_preset,          # Load built-in preset by name
    PRESETS,              # Dict of built-in presets
    FocusEngineConfig,    # Main config class
    SavedConfigStore,     # Named config snapshots (SQLite)
)
```

## Rules Changelog (`uaml.core.rules_changelog`)

SQLite-backed audit trail for all configuration changes.

### `RuleChange` dataclass
- `change_id: str` — UUID
- `timestamp: str` — ISO 8601
- `field_path: str` — e.g. `output_filter.token_budget_per_query`
- `old_value: Any`
- `new_value: Any`
- `reason: str`
- `changed_by: str`

### `RulesChangeLog` methods
- `log_change(change)` → `str` (change_id)
- `record_actual_impact(change_id, measurement)` — attach impact data
- `get_change(change_id)` → `RuleChange`
- `get_history(limit, offset, field_path, changed_by)` → `list[RuleChange]`
- `get_pending_evaluations(older_than_days)` → `list[RuleChange]`
- `get_stats()` → `dict` (total, by_field, by_user, recent)
- `export_json(limit)` → `str`

## Facade Integration

```python
from uaml.facade import UAML

uaml = UAML(db_path="memory.db")

# Focus recall
result = uaml.focus_recall(query="project status", budget=2000)

# Config management
uaml.load_focus_preset("conservative")
config = uaml.load_focus_config()
uaml.save_focus_config(config)
specs = uaml.focus_param_specs()
```

## MCP Tool

`memory_focus_recall` — token-budgeted recall with Focus Engine filtering.

Parameters:
- `query: str` (required)
- `budget: int` (optional, default from config)
- `tier: int` (optional, 1-3)

## CLI

```bash
uaml focus recall "project status" --budget 2000
uaml focus config --preset conservative
uaml focus params --cert-only
```

## REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/focus-config` | Current configuration |
| PUT | `/api/v1/focus-config` | Update configuration |
| GET | `/api/v1/focus-config/presets` | Built-in presets |
| GET | `/api/v1/focus-config/params` | Parameter specs |
| POST | `/api/v1/focus-recall` | Execute focus recall |
| GET | `/api/v1/rules-log` | Audit trail entries |
| GET | `/api/v1/rules-log/stats` | Changelog statistics |
| GET | `/api/v1/saved-configs?filter_type=input` | Named configs |
| POST | `/api/v1/saved-configs` | Save named config |
| POST | `/api/v1/saved-configs/load` | Load named config |
| POST | `/api/v1/saved-configs/delete` | Delete named config |
| GET | `/api/v1/active-config?filter_type=input` | Active config name |

## Test Coverage

- 62 unit tests (`tests/test_focus_engine.py`)
- 14 integration tests (`tests/test_focus_integration.py`)
- 12 SavedConfigStore tests
- 27 MCP tests (including `memory_focus_recall`)
- Total: 1347+ tests passing

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `uaml/core/focus_config.py` | 844 | Config, validation, presets, SavedConfigStore |
| `uaml/core/focus_engine.py` | 385 | Output filter, token budgeting |
| `uaml/ingest/filters.py` | 293 | 6 input filter stages |
| `uaml/core/rules_changelog.py` | 316 | Audit trail |
| `uaml/web/templates/input-filter.html` | — | Dashboard UI |
| `uaml/web/templates/output-filter.html` | — | Dashboard UI |
| `uaml/web/templates/rules-log.html` | — | Dashboard UI |
