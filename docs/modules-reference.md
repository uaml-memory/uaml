# UAML v1.0 — Module Reference

> Complete reference for all UAML modules. For quick start, see the [Facade API](#facade-api).

## Facade API

The simplest way to use UAML. One import, all features.

```python
from uaml.facade import UAML

uaml = UAML()
uaml.learn("Python 3.13 removed the GIL")
results = uaml.search("Python threading")
uaml.audit_report()
```

---

## Core Modules (`uaml.core`)

### MemoryStore (`core.store`)
SQLite-backed knowledge store. The heart of UAML.
- `learn(content, topic, source_type, confidence)` — store knowledge
- `search(query, limit, topic)` — full-text search
- `get(id)` — retrieve by ID
- `update(id, content)` — update entry
- `delete_entry(id)` — delete with cascade
- `purge(dry_run=True)` — bulk cleanup (safe by default)
- `stats()` — database statistics

### Schema (`core.schema`)
Database schema management with auto-migration.
- 5-layer architecture: identity, knowledge, team, operational, project
- Tables: `knowledge`, `audit_log`, `source_links`, `provenance`, `personality`

### Policy Engine (`core.policy`)
Query classification and model routing.
- `QueryClass` enum: FACTUAL, ANALYTICAL, CREATIVE, SENSITIVE
- `ModelProfile` enum: LOCAL_FAST, LOCAL_QUALITY, CLOUD_QUALITY
- `RiskLevel` enum: LOW, MEDIUM, HIGH, CRITICAL
- Route queries to appropriate models based on sensitivity

### Config Manager (`core.config`)
YAML/env-based configuration with `UAML_` prefix.
- Tiered config: default → file → environment
- Hot reload support

### Embeddings (`core.embeddings`)
Vector embedding generation for semantic search.
- Local model support (sentence-transformers)
- Dimensionality configuration

### Validation (`core.validation`)
Input validation and sanitization for all API inputs.

### Versioning (`core.versioning`)
Knowledge entry version tracking with diff support.

### Snapshot (`core.snapshot`)
Point-in-time database snapshots for temporal queries.

### Changelog (`core.changelog`)
Track all changes to knowledge entries.

### Batch Operations (`core.batch`)
Bulk import/export with progress tracking.

### Search (`core.search`)
Advanced search with filters, facets, and ranking.

### Tagging (`core.tagging`)
Auto-tagging and manual tag management.

### Templates (`core.templates`)
Response templates for consistent output formatting.

### Events (`core.events`)
Event bus for inter-module communication.

### Health Check (`core.health`)
System health monitoring and diagnostics.

### Scheduler (`core.scheduler`)
Maintenance task scheduling (cleanup, optimization).

### Retention (`core.retention`)
Data retention policies: archive, delete, flag_review, reduce_confidence.

### Deduplication (`core.dedup`)
Duplicate detection with merge strategies: keep_newest, keep_highest_confidence, keep_first.

### Contradiction Detection (`core.contradiction`)
Detect conflicting knowledge entries using word overlap analysis.

### Notifications (`core.notifications`)
Multi-channel notification center with throttling.

### Metrics (`core.metrics`)
Performance and usage metrics collection.

### Migration (`core.migration`)
Database schema migration management.

### Associative Memory (`core.associative`)
Link related knowledge entries for richer recall.

---

## Reasoning (`uaml.reasoning`)

### Temporal Reasoner (`reasoning.temporal`)
Time-aware queries with freshness scoring (exponential decay).

### Context Builder (`reasoning.context`)
Assemble optimal context for LLM prompts with budget management.

### Summarizer (`reasoning.summarizer`)
Automatic summarization of knowledge entries and conversations.

### Conflict Resolver (`reasoning.conflicts`)
Resolve contradictions between knowledge entries.

### Knowledge Scorer (`reasoning.scoring`)
Score entries: completeness 0.25, freshness 0.20, confidence 0.30, quality 0.25.

### Entity Extractor (`reasoning.entities`)
Extract named entities from text.

### Auto-Tagger (`reasoning.tagger`)
Automatic topic and category tagging.

### Knowledge Linker (`reasoning.linker`)
Discover and create links between related entries.

### Clustering (`reasoning.clustering`)
Group similar knowledge using Jaccard similarity.

### Search Cache (`reasoning.cache`)
LRU cache with TTL for search results.

### Analytics (`reasoning.analytics`)
Usage analytics and knowledge base insights.

### Incident Detection (`reasoning.incidents`)
Detect error clusters and anomalies in logs.

### Optimizer (`reasoning.optimizer`)
Database and query optimization recommendations.

---

## Security (`uaml.security`)

### Security Configurator (`security.configurator`)
Web UI wizard for OS hardening. See [Security Configurator docs](security-configurator.md).

### Expert Mode (`security.configurator.ExpertMode`)
Controlled, time-limited AI agent access to host OS.

### Hardening (`security.hardening`)
Security audit scoring and recommendations.
- `SecurityAuditor.score()`: 100 base, -20 per critical, -5 per warning

### Rate Limiter (`security.ratelimit`)
Token bucket rate limiting per agent per operation.

### RBAC (`security.rbac`)
Role-based access control for multi-agent setups.

### Data Sanitizer (`security.sanitizer`)
PII detection: email, phone, IP, credit card, API key, password fields.

---

## Compliance (`uaml.compliance`)

### Compliance Auditor (`compliance.auditor`)
Automated compliance checks against GDPR, ISO 27001.

### Consent Manager (`compliance.consent`)
Track and manage data subject consent records.

### DPIA Generator (`compliance.dpia`)
Data Protection Impact Assessment with auto-risk scoring.

### Data Inventory (`compliance.inventory`)
Catalog all data processing activities.

---

## Cryptography (`uaml.crypto`)

### Post-Quantum Encryption (`crypto.pqc`)
ML-KEM-768 (NIST FIPS 203) encryption for future-proof security.

### Key Escrow (`crypto.escrow`)
Shamir's Secret Sharing for key recovery.

### Digital Signatures (`crypto.signatures`)
Sign and verify knowledge entries and exports.

---

## Audit (`uaml.audit`)

### Access Log (`audit.access`)
Track all data access: who, what, when.

### Audit Collector (`audit.collector`)
Aggregate audit events from all modules.

### Log Store (`audit.logs`)
Structured application logging with separate `app_logs` table.

### Provenance Tracker (`audit.provenance`)
Track data lineage and transformation history.

### Audit Stream (`audit.stream`)
Real-time audit event streaming.

---

## Federation (`uaml.federation`)

### Federation Hub (`federation.hub`)
Multi-agent knowledge sharing with access controls.
- Identity layer NEVER shared
- Selective sync by topic/tag

### Messaging (`federation.messaging`)
Inter-agent communication protocol.

---

## Graph (`uaml.graph`)

### Local Graph (`graph.local`)
SQLite-based knowledge graph (no Neo4j required).
- BFS shortest path with configurable max_depth
- Node/edge CRUD operations

### Graph Sync (`graph.sync`)
Synchronize graph with knowledge store.

---

## Ingest (`uaml.ingest`)

### Chat Ingestor (`ingest.chat`)
Import chat history (OpenClaw, Discord, Telegram formats).

### Markdown Ingestor (`ingest.markdown`)
Import knowledge from Markdown files.

### Web Ingestor (`ingest.web`)
Extract and store knowledge from web pages.

### Continuous Ingestor (`ingest.continuous`)
Watch directories for new files and auto-import.

### Pipeline (`ingest.pipeline`)
Multi-stage ingestion with transformation steps.

### Search Ingestor (`ingest.search`)
Import from search engine results.

---

## I/O (`uaml.io`)

### Backup (`io.backup`)
Encrypted database backups with rotation.

### Exporter (`io.exporter`)
Export knowledge in multiple formats (JSON, CSV, Markdown).

### Importer (`io.importer`)
Import from external formats.

### Formats (`io.formats`)
Format detection and conversion utilities.

---

## Voice (`uaml.voice`)

### Text-to-Speech (`voice.tts`)
- **Starter tier:** Piper TTS (runs on Raspberry Pi)
- **Enterprise tier:** XTTS v2 (voice cloning)

### Speech-to-Text (`voice.stt`)
- **Starter tier:** Whisper.cpp
- **Enterprise tier:** faster-whisper with GPU acceleration

---

## Plugins (`uaml.plugins`)

### Plugin Manager (`plugins.manager`)
Load/unload plugins with error handling and lifecycle hooks.
- ON_ERROR hooks for graceful degradation
- Plugin isolation

---

## API & Integration

### REST API (`api.server`)
HTTP API server for external integrations.

### API Client (`api.client`)
Python client for the REST API.

### MCP Server (`mcp.server`)
Model Context Protocol bridge for LLM tool integration.

---

## Web (`uaml.web`)

### Web Dashboard (`web.app`)
Browser-based knowledge management UI.

---

## CLI (`uaml.cli`)

```bash
uaml init          # Initialize database
uaml learn "..."   # Store knowledge
uaml search "..."  # Search
uaml export        # Export data
uaml audit         # Run audit
uaml serve         # Start API server
```

---

## Focus Engine (`uaml.core.focus_engine`)

Intelligent context selection engine with token budgeting, relevance scoring, temporal decay, and deduplication. Selects the most relevant memory records within a configurable token budget.

- **`FocusEngine`** — main engine class
  - `process(query, records, config)` → filtered, ranked, deduplicated records within budget
  - `get_token_usage_report()` → usage statistics
- **3 recall tiers**: Tier 1 (summaries only), Tier 2 (summaries + recent), Tier 3 (full recall)
- **3 presets**: `conservative` (1500 tokens, tier 1), `standard` (3000 tokens, tier 2), `research` (8000 tokens, tier 3)

### Focus Config (`core.focus_config`)

Typed configuration management for Focus Engine.

- **Dataclasses**: `FocusEngineConfig`, `InputFilterConfig`, `OutputFilterConfig`, `AgentRulesConfig`
- **Functions**: `load_focus_config()`, `save_focus_config()`, `load_preset(name)`
- **`SavedConfigStore`** — SQLite-backed named config management with `filter_type` separation (input/output/both)
  - `save(name, config, filter_type=..., set_active=True)`
  - `load(name, filter_type=...)`, `delete(name)`, `set_active(name)`
  - `list(filter_type=None)`, `get_active_name(filter_type=...)`

### Rules Changelog (`core.rules_changelog`)

SQLite append-only audit trail for Focus Engine configuration changes.

- Records: who, when, what changed, why, expected impact
- `RulesChangelog.log_change(field, old_value, new_value, changed_by, reason)`
- `RulesChangelog.get_log(limit, offset)` → paginated history
- `RulesChangelog.get_stats()` → change frequency statistics

---

## Input Filters (`uaml.ingest.filters`)

Pipeline filter stages for the Focus Engine input path.

- **6 stages** (in order): `fe_length_filter`, `fe_max_tokens_filter`, `fe_rate_limit`, `fe_category_filter`, `fe_pii_detector`, `fe_relevance_gate`
- **`setup_input_filter(pipeline, config)`** — registers all stages
- **`detect_pii(text)`** — PII detection with Czech-specific patterns (IČO, DIČ, rodné číslo)
- Categories: `personal`, `financial`, `health`, `company`, `public`, `communication`

---

## Feature Gate (`uaml.feature_gate`)

Feature flag system for enabling/disabling features per license tier.

- **`FeatureGate`** — checks feature availability against license tier
- **`TrialManager`** — manages trial periods with freeze-on-expiry model
- **`@require_feature`** decorator — guards function access by feature flag
- 17 features in `FEATURE_MATRIX` across Starter/Pro/Enterprise tiers

---

## Licensing (`uaml.licensing`)

License key generation, validation, and tier management.

- **`LicenseKey`** — HMAC-SHA256 signed keys with tier, expiry, features
- **`LicenseManager`** — full lifecycle: generate, validate, revoke, renew
- **`LicenseServer`** — REST API for license operations
- Tiers: `starter`, `pro`, `enterprise`

---

## Customer Portal (`uaml.customer`)

Customer-facing web portal for registration, authentication, and dashboard.

- **`CustomerDB`** — SQLite user store with PBKDF2 password hashing
- **`CustomerPortal`** — HTTP handler for `/portal` routes (register, login, dashboard, logout)
- Bilingual: Czech + English (via `_STRINGS` dict + `?lang=` parameter)
- Dark-themed responsive UI

---

## Ethics Checker (`uaml.ethics.checker`)

Ethical rule evaluation engine.

- **14 default rules** across sensitivity categories
- **Asimov's Laws 4-tier hierarchy**: safety > human control > compliance > utility
- `EthicsChecker.check(data)` → `APPROVED` / `FLAGGED` / `REJECTED`
- YAML import/export for rule configuration

---

## Models (`uaml.core.models`)

Data models and type definitions used across the system.

- **Enums**: `DataLayer`, `MemoryType`, `SourceOrigin`, `LegalBasis`
- **Dataclasses**: `KnowledgeEntry`, `Entity`, `Task`, `Artifact`

### Base Ingest (`ingest.base`)

Base classes for ingest pipeline stages.

- **`BaseIngestor`** — abstract base class with `ingest()` method
- **`IngestStats`** — tracking for records processed/skipped/failed

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      UAML Facade API                          │
├──────────────────────────────────────────────────────────────┤
│  Reasoning    │  Security     │  Compliance   │  Federation  │
│  - Temporal   │  - Configurator│ - Auditor     │  - Hub       │
│  - Context    │  - Expert Mode│  - Consent    │  - Messaging │
│  - Scoring    │  - RBAC       │  - DPIA       │              │
│  - Clustering │  - Sanitizer  │  - Inventory  │              │
├──────────────────────────────────────────────────────────────┤
│                    Core (MemoryStore)                         │
│  Schema │ Policy │ Config │ Events │ Health │ Retention      │
├──────────────────────────────────────────────────────────────┤
│  Crypto (PQC)  │  Audit Trail  │  Graph  │  Ingest Pipeline │
├──────────────────────────────────────────────────────────────┤
│  I/O (Backup/Export)  │  Voice (TTS/STT)  │  Plugins        │
├──────────────────────────────────────────────────────────────┤
│                    SQLite (Local-First)                       │
└──────────────────────────────────────────────────────────────┘
```

---

*© 2026 GLG, a.s. — UAML v1.0*
