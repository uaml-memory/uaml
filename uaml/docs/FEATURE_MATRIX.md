# UAML License Tier — Feature Matrix

> © 2026 GLG, a.s. | v1.0

## Tiers

| Tier | Price | Annual | Best For |
|------|-------|--------|----------|
| Community | Free | Free | Personal use, experimentation |
| Starter | €8/mo | €80/yr | Individual professionals |
| Professional | €29/mo | €290/yr | Power users, developers |
| Team | €190/mo | €1,900/yr | Organizations, multi-agent |
| Enterprise | Custom | Custom | Regulated industries |

## Features

| Feature | Community | Starter | Pro | Team | Enterprise |
|---------|:---------:|:-------:|:---:|:----:|:----------:|
| Store & recall | ✅ | ✅ | ✅ | ✅ | ✅ |
| Full-text search | ✅ | ✅ | ✅ | ✅ | ✅ |
| CLI | ✅ | ✅ | ✅ | ✅ | ✅ |
| PII detection | ✅ | ✅ | ✅ | ✅ | ✅ |
| Basic audit log | ✅ | ✅ | ✅ | ✅ | ✅ |
| Focus Engine | ❌ | ✅ | ✅ | ✅ | ✅ |
| Presets | ❌ | ✅ | ✅ | ✅ | ✅ |
| REST API | ❌ | ✅ | ✅ | ✅ | ✅ |
| Dashboard UI | ❌ | ✅ | ✅ | ✅ | ✅ |
| MCP bridge | ❌ | ❌ | ✅ | ✅ | ✅ |
| Export/Import | ❌ | ❌ | ✅ | ✅ | ✅ |
| Saved configs | ❌ | ❌ | ✅ | ✅ | ✅ |
| Rules audit trail | ❌ | ❌ | ✅ | ✅ | ✅ |
| Neo4j graph | ❌ | ❌ | ✅ | ✅ | ✅ |
| Temporal reasoning | ❌ | ❌ | ✅ | ✅ | ✅ |
| Contradiction detection | ❌ | ❌ | ✅ | ✅ | ✅ |
| Federation | ❌ | ❌ | ❌ | ✅ | ✅ |
| Multi-user RBAC | ❌ | ❌ | ❌ | ✅ | ✅ |
| Agent coordination | ❌ | ❌ | ❌ | ✅ | ✅ |
| Prompt protection | ❌ | ❌ | ❌ | ✅ | ✅ |
| GDPR tools | ❌ | ❌ | ❌ | ✅ | ✅ |
| Security Configurator | ❌ | ❌ | ❌ | ✅ | ✅ |
| PQC encryption | ❌ | ❌ | ❌ | ❌ | ✅ |
| Custom SLA | ❌ | ❌ | ❌ | ❌ | ✅ |
| On-premise support | ❌ | ❌ | ❌ | ❌ | ✅ |

## Limits

| Limit | Community | Starter | Pro | Team | Enterprise |
|-------|:---------:|:-------:|:---:|:----:|:----------:|
| Max memories | 10,000 | 100,000 | 1,000,000 | 5,000,000 | Unlimited |
| Max devices | 1 | 3 | 10 | 50 | Unlimited |

## Trial

7-day Professional trial included with every new installation.
After trial: custom rules stay active (protecting data) but cannot be edited without paid license.

## Feature Gate API

```python
from uaml.feature_gate import FeatureGate

gate = FeatureGate(license_manager=lm)
gate.is_available("focus_engine")    # → bool
gate.require("federation")           # raises FeatureNotAvailable
gate.available_features()            # → list[str]
```

## Upgrade

Portal: https://uaml-memory.com/portal
Sales: sales@uaml.ai
