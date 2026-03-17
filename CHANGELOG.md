# Changelog

> **⚠️ Experimental Notice:** All features are experimental and under active development. Use at your own risk. APIs and behavior may change between versions.

All notable changes to UAML will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
