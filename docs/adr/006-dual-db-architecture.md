# ADR-006: Dual-Database Architecture (SQLite + Neo4j)

**Status:** accepted  
**Date:** 2026-03-05  
**Decision makers:** Pavel (Vedoucí)  
**Context source:** Knowledge graph requirements, team discussion

## Context

We need both fast transactional storage and rich graph-based knowledge exploration. A single database cannot optimally serve both needs.

Pavel proposed a two-tier architecture separating raw data storage from curated expert knowledge.

## Decision

**Two-tier database architecture:**

| Tier | Technology | Purpose | Data Quality |
|------|-----------|---------|-------------|
| **Tier 1: Raw** | SQLite | Chat, notes, TODO, audit, basic relations | Raw, unfiltered |
| **Tier 2: Expert** | Neo4j | Verified knowledge, dependencies, sources | Curated, verified |

Data flow:
1. All data enters SQLite first (fast, reliable, certifiable)
2. Background process cleans, verifies, and enriches data
3. Verified data with proven relationships promoted to Neo4j
4. Neo4j enables graph traversal, relationship discovery, expert queries

Quality gate: Only `verified` or `peer-reviewed` data enters Neo4j. Deduplication, source verification, and relationship validation happen during promotion.

## Consequences

### Positive
- **Best of both:** Fast writes (SQLite) + rich queries (Neo4j)
- **Quality control:** Neo4j contains only verified knowledge
- **Certifiable core:** SQLite tier is self-contained and certifiable
- **Visualization:** Neo4j enables interactive knowledge graph exploration
- **Hybrid search:** Combine fulltext (SQLite) + graph traversal (Neo4j)

### Negative
- **Sync complexity:** Must keep tiers consistent
- **Two systems to maintain:** Operational overhead
- **Neo4j dependency:** Tier 2 adds an external dependency (but it's optional)

### Risks
- Sync lag between tiers could cause stale data in Neo4j
- Mitigation: Idempotent MERGE operations, sync tracking table

## Compliance Impact

- **Data quality:** Two-tier model ensures auditors see only verified data in expert layer
- **Audit trail:** Raw tier preserves all original data, expert tier shows provenance
- **Certification:** Core (SQLite) certified independently; Neo4j is optional enrichment

## References

- Pavel's two-tier proposal: "SQLite = raw data, Neo4j = curated expert knowledge"
- Neo4j sync engine: uaml/graph/sync.py
- Current Neo4j stats: 2,301 nodes, 9,547 relationships

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

