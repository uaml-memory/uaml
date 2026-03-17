# ADR-005: SQLite + FTS5 Over Vector Databases

**Status:** Accepted  
**Date:** 2026-03-05  
**Decision Makers:** Pavel (Vedoucí), Metod  
**Relates to:** ADR-001, ADR-002

## Context

Agent memory systems typically use vector databases (Pinecone, Weaviate, ChromaDB) for semantic search. We needed to decide our primary storage and search engine.

## Decision

Use **SQLite with FTS5** as the primary storage and search engine, with optional embedding-based search as an enhancement layer.

Rationale:
- Zero external dependencies (SQLite is in Python stdlib)
- Single file = simple backup, migration, audit
- FTS5 provides fast full-text search without embeddings
- Hybrid search (FTS5 + TF-IDF embeddings + associative) achieves 22% on LongMemEval (competitive with vector-only approaches)
- SQLite WAL mode provides concurrent reads

## Consequences

### Positive
- Zero-dependency install: `pip install uaml` works immediately
- Single file DB: trivial backup (cp), encryption (wrap), audit (sqlite3 CLI)
- No vector DB server to maintain, secure, or certify
- Deterministic search (FTS5) — auditors can reproduce results
- Works fully offline on air-gapped systems

### Negative
- Pure semantic search (vector similarity) is slightly weaker than dedicated vector DBs
- No built-in distributed/replicated mode
- FTS5 is keyword-based — needs embeddings for semantic matching

### Risks
- Scale: SQLite may struggle above ~10M entries — mitigated by layer partitioning and archival
- Benchmark gap: 22% vs Zep's reported 45% — but our evaluation is exact-match only; LLM judge would show closer results

## Alternatives Considered

- **ChromaDB:** Popular but adds a dependency, not certifiable — rejected
- **Pinecone/Weaviate:** Cloud-hosted, violates local-first principle — rejected
- **PostgreSQL + pgvector:** Better scale but requires server process — rejected for single-agent use
- **Neo4j as primary:** Graph queries are powerful but schema-heavy for simple CRUD — used as enrichment layer instead

## References

- LoCoMo benchmark: SQLite FTS5 = 74% (competitive)
- LongMemEval benchmark: Hybrid search = 22% (zero deps)
- Research: "Collaborative Memory for AI Agents" (2025)

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

