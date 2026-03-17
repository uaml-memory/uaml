# ADR-002: SQLite + FTS5 as Primary Storage (Not Vector DB)

**Status:** accepted  
**Date:** 2026-03-05  
**Decision makers:** Pavel (Vedoucí), Pepa2, Cyril  
**Context source:** Research benchmarks, LangMem/Zep analysis, team discussion

## Context

Modern AI memory systems typically use vector databases (Pinecone, Chroma, Weaviate) for semantic search. We evaluated this approach against SQLite + FTS5 full-text search.

Key requirements:
- Zero external dependencies (certifiability)
- Local-first operation (data sovereignty)
- Auditability (every record traceable)
- Performance for our scale (thousands, not millions of records)

## Decision

**SQLite + FTS5 as primary storage**, with optional TF-IDF hybrid search for improved retrieval quality. Vector DB support available as optional adapter, not core dependency.

Benchmarked on LongMemEval:
- FTS5 baseline: 14.8% hit rate (0ms latency, zero deps)
- Hybrid TF-IDF: 22.0% hit rate (+48% improvement, still zero deps)
- Neural embeddings (sentence-transformers): ~22% (bottleneck is evaluation method, not retrieval)
- Zep (reference, cloud): ~45% (but requires cloud, external dependency)

## Consequences

### Positive
- **Zero dependencies:** No Python ML libraries required in core
- **Certifiable:** SQLite is the most tested database engine in the world
- **Auditable:** Single file, standard SQL, trivial to inspect
- **Fast:** Sub-millisecond queries at our scale
- **Portable:** Single .db file, works everywhere Python runs
- **Backup:** Copy one file = complete backup

### Negative
- **Lower semantic recall:** FTS5 is keyword-based, misses semantic similarity
- **No vector search in core:** Customers who need it must install optional adapter
- **Scale ceiling:** SQLite may struggle at millions of records (not our current concern)

### Risks
- Competitors with vector DB may show better demo recall numbers
- Mitigation: Hybrid TF-IDF closes much of the gap without adding deps

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| ChromaDB | Good semantic search | Python dependency, not certifiable standalone | Adds uncertifiable dependency |
| Pinecone | Excellent recall | Cloud-only, data leaves customer hardware | Violates local-first requirement |
| pgvector | PostgreSQL ecosystem | Heavy dependency, complex deployment | Over-engineered for our use case |
| Hybrid (SQLite + optional vectors) | Best of both | Complexity | **This is what we do** — vectors as optional adapter |

## Compliance Impact

- **GDPR:** SQLite supports complete data deletion (VACUUM after DELETE)
- **ISO 27001:** Single-file DB simplifies backup, audit, and access control
- **Certification:** SQLite has extensive third-party testing and validation history

## References

- LongMemEval benchmark results: benchmarks/longmemeval/
- Research: LangMem (episodic/semantic/procedural memory types)
- Research: Zep/Graphiti (temporal weighting)
- Collaborative Memory (2025): private + shared dual-tier architecture

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

