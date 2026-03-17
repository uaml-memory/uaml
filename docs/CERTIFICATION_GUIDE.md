# UAML Certification Guide — Focus Engine & Data Protection

**Version:** 1.0  
**Date:** 2026-03-14  
**Classification:** Cat A — Audit/Architecture  

© 2026 GLG, a.s.

---

## 1. Scope

This document covers the certifiable aspects of the UAML Focus Engine:
- Data input filtering and classification
- Data output filtering and context selection
- Token budget management
- Audit trail and change logging
- Agent isolation from rule configuration
- PII detection and data category enforcement

---

## 2. Architecture Overview

```
Data Sources → [Input Filter] → Neo4j/Storage → [Focus Engine] → Agent Context
                    ↑                                  ↑
              Human-configured                  Human-configured
              (Web UI only)                     (Web UI only)
                    ↓                                  ↓
              AI Agent: NO ACCESS              AI Agent: NO ACCESS
              to configuration                 to configuration
```

**Key principle:** AI agents operate UNDER the rules, not above them.

---

## 3. Certification-Relevant Parameters

These parameters directly affect data protection, access control, and compliance.
Marked with 🔒 in the system.

### 3.1 Input Filter

| Parameter | Type | Default | Range | Certification Impact |
|-----------|------|---------|-------|---------------------|
| `min_relevance_score` | float | 0.7 | 0.0–1.0 | Controls data quality threshold |
| `ttl_days` | int | 730 | 30–100000 | GDPR Art. 5(1)(e) — storage limitation |
| `require_classification` | bool | true | — | Ensures all data is categorized |
| `pii_detection` | bool | true | — | GDPR Art. 25 — data protection by design |

### 3.2 Output Filter

| Parameter | Type | Default | Range | Certification Impact |
|-----------|------|---------|-------|---------------------|
| `token_budget_per_query` | int | 2000 | 200–32000 | Controls data exposure volume |
| `recall_tier` | int | 1 | 1–3 | Controls data granularity in context |
| `sensitivity_threshold` | int | 3 | 1–5 | Controls access to sensitive data |
| `max_context_percentage` | int | 30 | 5–80 | Limits data exposure per request |

### 3.3 Agent Rules

| Parameter | Type | Default | Certification Impact |
|-----------|------|---------|---------------------|
| `report_token_usage` | bool | true | Auditability of data access |
| `never_expose_rules` | bool | true | Configuration confidentiality |
| `never_bypass_filter` | bool | true | Filter integrity guarantee |
| `log_all_recalls` | bool | true | Complete audit trail |

### 3.4 Programmatic Access

```python
from uaml.core.focus_config import FocusEngineConfig

config = FocusEngineConfig()
cert_params = config.certification_params()
# Returns dict of all certification-relevant parameters with current values
```

CLI:
```bash
uaml focus params --cert-only
```

---

## 4. Access Control Matrix

| Actor | Input Filter Config | Output Filter Config | Rules Change Log | Agent Rules |
|-------|-------------------|---------------------|-----------------|-------------|
| Human Owner | Read/Write | Read/Write | Read | Read/Write |
| Human Admin | Read/Write | Read/Write | Read | Read |
| AI Agent | **NO ACCESS** | **NO ACCESS** | **NO ACCESS** | **Read-only** |
| System (UAML) | Apply rules | Apply rules | Write (auto) | Apply rules |

### 4.1 Enforcement

- API endpoints for config changes require human authentication tokens
- Agent tokens are rejected at the API layer for config endpoints
- MCP tool `memory_focus_recall` can only READ results, not modify rules
- CLI commands require local system access (no remote agent execution)

---

## 5. Audit Trail

### 5.1 Rules Change Log

Every configuration change is recorded in `rules_changelog.db`:

| Field | Description |
|-------|-------------|
| `change_id` | Unique identifier (RC-{uuid}) |
| `timestamp` | ISO-8601 UTC timestamp |
| `user` | Authenticated user who made the change |
| `rule_path` | Full parameter path (e.g., `output_filter.token_budget_per_query`) |
| `old_value` | Previous value |
| `new_value` | New value |
| `reason` | User-provided justification |
| `expected_impact` | User's hypothesis about the change impact |
| `actual_impact` | Measured impact after evaluation period |

### 5.2 Recall Audit

Every `focus_recall` operation is logged in the UAML `audit_log` table:

```
action: focus_recall
details: budget=2000|used=1450|selected=5|rejected=3|tier=1|query=...
```

### 5.3 Decision Audit

Every recall decision (include/exclude) is returned with reason:

```json
{
  "entry_id": 42,
  "included": false,
  "reason": "Sensitivity 5 > threshold 3",
  "final_score": 0.0,
  "tokens_used": 0
}
```

---

## 6. Data Categories & GDPR Mapping

| Category | GDPR Article | Default Action | Rationale |
|----------|-------------|---------------|-----------|
| Personal data | Art. 6 (lawful basis) | Require consent | Processing requires legal basis |
| Financial data | Art. 6 + Art. 32 | Encrypt | Security of processing |
| Health data | Art. 9 (special categories) | Deny | Requires explicit consent + additional safeguards |
| Company data | Art. 6 | Allow | Legitimate interest |
| Public data | Art. 6(1)(f) | Allow | Publicly available |
| Communication | Art. 6 + ePrivacy | Encrypt | Communication confidentiality |

### 6.1 PII Detection

Built-in PII patterns:
- Email addresses
- Phone numbers (international + Czech format)
- Czech birth numbers (rodné číslo)
- Credit card numbers
- IBAN numbers
- IP addresses
- Czech IČO / DIČ

Auto-detection tags records with `pii_detected=true` and `sensitivity` level.

---

## 7. Token Budget & Cost Transparency

### 7.1 Token Impact Table

| Setting Change | Token Impact | Cost Impact | Quality Impact |
|----------------|-------------|-------------|----------------|
| Budget 500→2000 | +1500 tok/query | +€0.03/query | +40% precision |
| Budget 2000→4000 | +2000 tok/query | +€0.04/query | +20% precision |
| Relevance 0.3→0.5 | -800 tok/query | -€0.02/query | -10% coverage |
| Tier 1→3 | +3000 tok/query | +€0.06/query | +25% detail |

### 7.2 Token Usage Report

Every recall returns a `TokenUsageReport`:

```json
{
  "budget": 2000,
  "used": 1450,
  "remaining": 550,
  "records_selected": 5,
  "records_rejected": 3,
  "avg_tokens_per_record": 290.0,
  "estimated_cost_usd": 0.00435,
  "recall_tier": 1
}
```

---

## 8. Default Presets

| Preset | Budget | Min Relevance | Tier | Max Records | Use Case |
|--------|--------|--------------|------|-------------|----------|
| Conservative | 1500 | 0.5 | 1 (summaries) | 5 | Privacy-first, minimal exposure |
| Standard | 3000 | 0.3 | 2 (details) | 10 | Balanced quality/cost |
| Research | 8000 | 0.2 | 3 (raw) | 25 | Maximum context, research |

---

## 9. Freeze Behavior (Post-Trial)

After trial expiration:
1. Custom rules **remain active** — data protection continues
2. Rules cannot be edited, added, or removed
3. Dashboard shows read-only view
4. Default preset is enforced
5. No data is at risk — freeze is a licensing constraint, not a security gap

---

## 10. Compliance Checklist

| # | Requirement | Implementation | Status |
|---|------------|----------------|--------|
| 1 | Data classification | Category system with GDPR mapping | ✅ |
| 2 | PII detection | Regex/NER auto-detection | ✅ |
| 3 | Access control | Human-only config, agent isolation | ✅ |
| 4 | Audit trail | Rules Change Log + recall audit | ✅ |
| 5 | Token transparency | Real-time budget reporting | ✅ |
| 6 | Data minimization | Configurable relevance thresholds | ✅ |
| 7 | Storage limitation | TTL with configurable retention | ✅ |
| 8 | Right to erasure | Delete API with audit log | ✅ |
| 9 | Data portability | Export (JSON/YAML) | ✅ |
| 10 | Configuration rollback | Rules Change Log with rollback | ✅ |

---

## 11. API Reference

### Focus Engine Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/focus-config` | Current configuration |
| `PUT` | `/api/v1/focus-config` | Update configuration (human-only) |
| `GET` | `/api/v1/focus-config/presets` | Available presets |
| `GET` | `/api/v1/focus-config/params` | Parameter specifications |
| `POST` | `/api/v1/focus-recall` | Intelligent recall |
| `GET` | `/api/v1/rules-log` | Rules change history |
| `GET` | `/api/v1/rules-log/stats` | Change statistics |

### MCP Tools

| Tool | Description |
|------|-------------|
| `memory_focus_recall` | Intelligent recall with preset/budget |

### CLI Commands

| Command | Description |
|---------|-------------|
| `uaml focus recall "query"` | Recall with token report |
| `uaml focus config` | View/save configuration |
| `uaml focus params --cert-only` | Certification parameters |

---

*Document generated: 2026-03-14*  
*Next review: Before v1.0 release*
