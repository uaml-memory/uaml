# Changelog

> **⚠️ Experimental Notice:** All features are experimental and under active development. Use at your own risk. APIs and behavior may change between versions.

All notable changes to UAML will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.1] — 2026-03-18

### Fixed
- CLI `--version` flag crash — fixed `package_name` from `"uaml"` to `"uaml-memory"`
- `__version__` now correctly reports `1.1.1` (was stuck at `1.0.0`)

### Added
- **Update checker** — notifies users about new versions on CLI startup (once per day, non-blocking)
  - Opt-out: `UAML_NO_UPDATE_CHECK=1` environment variable
  - Shows: `💡 UAML Memory X.Y.Z is available. Upgrade: pip install --upgrade uaml-memory`

## [1.1.0] — 2026-03-18

### Added
- **Three-Layer Recovery Architecture** — L1 (compaction summaries) + L2 (UAML knowledge) + L3 (SQL archive) = **100% data recovery**, zero permanent data loss
- **UAML → SQL Recall Chain** (`tools/uaml_recall_chain.py`) — links UAML knowledge entries to original SQL messages via timestamp + content-hash matching; `detail_lookup()` returns verbatim original text with ±2 context messages; 91% link rate achieved
- **Input Quality Filter** (`tools/uaml_input_filter.py`) — 3-level importance classification (HIGH/MEDIUM/LOW) with configurable scoring rules; decisions and rules → HIGH, entity mentions → MEDIUM, noise → LOW; reduces recall noise by 55%
- **Context Enrichment** (`tools/uaml_context_enrichment.py`) — generates `UAML_CONTEXT.md` workspace file with top knowledge entries that survives compaction; auto-regeneration via cron
- **Context Broker** (`tools/uaml_context_broker.py`) — cross-session knowledge sharing with entity/topic overlap detection and decision-weight boosting (2×)
- **Compaction Metrics** (`tools/uaml_compaction_metrics.py`) — 4 measurement modes: `--baseline`, `--compare`, `--broker`, `--fallback`; production benchmarks included
- **Context Recovery Test** (`tools/uaml_context_recovery_test.py`) — measures real compaction loss vs. UAML+SQL recovery across all 3 layers
- **Relevance Benchmark** (`tools/uaml_relevance_benchmark.py`) — 15 topic-based precision tests; 100% precision, 99.5% average relevance score
- **Integration Test Suite** (`tools/uaml_integration_test.py`) — 11 tests covering DB, search, recall, focus engine, context summary, and fallback resilience
- **Auto-Maintenance Mode** — `--auto` flag for recall chain: 2-pass linking (30s + 120s window), designed for cron/scheduler; idempotent
- **Context Tuning Guide** (EN + CZ) — comprehensive documentation for tuning all 4 components: input filter thresholds, broker relevance, enrichment parameters, recall chain matching
- **Session Architecture Docs** (EN + CZ) — architectural overview of the three-layer system with diagrams

### Changed
- `knowledge` table: added `importance_level TEXT`, `importance_score INTEGER`, `chat_history_id INTEGER` columns
- Configurable database paths via environment variables (`UAML_MEMORY_DB`, `UAML_CHAT_DB`, `UAML_SESSION_DIR`)
- RFC updated with production benchmark data, dual-track architecture, certifiability section

### Performance
- **Compression**: 99.94% (46.2 MB session → 35.2 KB active context)
- **Entity recovery**: 100% (vs. 14% without UAML) through three-layer recall
- **Decision recovery**: 100% (vs. 43% without UAML)
- **Context overhead**: +15% (+4.7 KB structured knowledge)
- **Fallback resilience**: 97% — agent fully functional without UAML

### Architecture
- **Dual-Track Design**: OpenClaw builtin compaction always runs in parallel; UAML is an overlay/enhancement, never a replacement. Zero single-point-of-failure.
- **Provenance Chain**: Every UAML entry traceable to original SQL message via `chat_history_id` → full audit trail for regulated environments

## [1.0.0] — 2026-03-14

### Added
- **5 Memory Types**: Episodic, semantic, procedural, reasoning, associative (`MemoryType` enum)
- **5-Layer Data Architecture**: Identity, knowledge, team, operational, project (`DataLayer` enum)
- **Policy-aware recall**: `policy_recall()` with context budgeting and tier limits
- **Proactive recall**: `proactive_recall()` — intuitive memory surfacing
- **Associative memory**: `AssociativeEngine` with contextual recall
- **Reasoning traces**: `capture_reasoning()`, `auto_capture_reasoning()`, evidence chains
- **PQC encryption**: ML-KEM-768 (NIST FIPS 203) — encrypt/decrypt, file encryption
- **Key escrow**: Secret sharing with `KeyEscrow` (deposit/recover/revoke)
- **GDPR compliance toolkit**: `ConsentManager`, `ComplianceAuditor`, `access_report()`, `execute_erasure()`
- **DPIA & breach notification**: `DPIAGenerator`, `BreachRegister` (Art. 33/34/35)
- **Incident pipeline**: `IncidentPipeline` with lesson extraction and rule checking
- **Ingest system**: `ChatIngestor`, `MarkdownIngestor`, `WebIngestor`, `SearchIngestor` + registry
- **Tool result mining**: Automatic knowledge extraction from tool call results
- **Configuration discovery**: `discover_config()`, `find_databases()`, environment variables
- **Structured logging**: `LogStore` with query/stats/purge + log→incident escalation
- **Neo4j graph sync**: Push/pull, PQC encryption, quality gate, expert graph queries
- **Multi-size context summaries**: `context_summary(size=micro|compact|standard|full)`
- **Selective purge**: `store.purge()` with dry run + `delete_entry()`
- **Ethics checker**: Content screening pipeline with configurable rules
- **Export security**: Signed exports (SHA-256 manifest) + PQC-encrypted exports
- **REST API**: `/api/recall`, `/api/summaries`, `/api/compliance`, `/api/reasoning`, `/api/config`
- **CLI**: `uaml init|learn|search|stats|layers|compliance audit|gdpr|retention`
- **MCP server**: Model Context Protocol integration
- **Voice module**: `TTSEngine` (piper/espeak) + `STTEngine` (whisper/vosk)
- **LongMemEval benchmark**: 17 memory evaluation tests
- **668 tests**, 0 warnings, 100% pass rate
- **90+ bilingual docs** (EN + CZ)
- **Dependency audit**: Zero copyleft licenses (all MIT/BSD/Apache-2.0)

### Fixed
- Audit stream timestamp handling (event timestamps vs wall clock)
- All `datetime.utcnow()` deprecation warnings
- Source links column references in purge operations

### Security
- Post-quantum cryptography (ML-KEM-768) for data at rest and export
- Key escrow with threshold secret sharing
- Identity layer protection (requires explicit confirmation for export)
- Client data isolation enforced at query level
- Complete audit trail for all data operations

## [0.4.2] — 2026-03-12

### Added
- Compliance auditor (`compliance/auditor.py`) — automated GDPR + ISO 27001 checks
- Audit stream processor (`audit/stream.py`) — real-time log monitoring with incident lifecycle
- Real-time alerting for critical security events
- Neo4j sync for incident and segment data

### Changed
- Updated CLI to v0.4.2

## [0.4.1] — 2026-03-10

### Added
- Associative memory engine (`core/associative.py`) — 7-signal cross-memory linking
- Embedding engine (`core/embeddings.py`) — pluggable backends (sentence-transformers, TF-IDF)
- Ethics checker (`ethics/checker.py`) — content filtering pipeline
- Contradiction detection (`core/contradiction.py`) — 4-layer detection with resolution
- Reasoning traces (`reasoning/`) — decision provenance tracking
- Incident pipeline (`reasoning/incidents.py`) — automated learning from failures
- Policy engine (`core/policy.py`) — query classification, recall tiers, budget control
- Ingest pipelines (chat, markdown, web)
- Backup/restore/export/import (`io/`)
- MCP server (`mcp/server.py`) — Model Context Protocol integration
- PQC encryption (`crypto/pqc.py`) — ML-KEM-768 (NIST FIPS 203)
- Agent signatures (`crypto/signatures.py`)
- Neo4j graph sync (`graph/sync.py`) — dual-DB architecture

## [0.3.0] — 2026-03-08

### Added
- REST API server (`api/server.py`, `web/app.py`)
- API client library (`api/client.py`)
- Knowledge graph endpoints
- Timeline visualization
- Layer statistics

## [0.2.0] — 2026-03-06

### Added
- Core memory store (`core/store.py`) — SQLite-backed knowledge base
- Five memory layers: episodic, semantic, procedural, reasoning, associative
- Temporal validity (`valid_from`, `valid_until`, point-in-time queries)
- Full-text search
- Client context isolation (`client_ref`)
- Task management

## [0.1.0] — 2026-03-04

### Added
- Initial project structure
- CLI framework with `click`
- Basic knowledge entry CRUD
- SQLite storage backend

---

© 2026 GLG, a.s. All rights reserved.
