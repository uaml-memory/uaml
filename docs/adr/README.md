# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records for the UAML project.

ADRs document significant architectural decisions with context, rationale, consequences, and alternatives considered. They serve as an audit trail for certifiers and a knowledge base for team members.

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [000](000-template.md) | Template | - | - |
| [001](001-varianta-d-certifiable-core.md) | Varianta D — Certifiable Core with Universal Bridge | Accepted | 2026-03-05 |
| [002](002-five-layer-data-architecture.md) | Five-Layer Data Architecture | Accepted | 2026-03-08 |
| [003](003-pqc-encryption.md) | Post-Quantum Cryptography (ML-KEM-768 + AES-256-GCM) | Accepted | 2026-03-08 |
| [004](004-asimov-ethics-hierarchy.md) | Asimov Ethics Hierarchy (4-Tier) | Accepted | 2026-03-08 |
| [005](005-sqlite-over-vector-db.md) | SQLite + FTS5 Over Vector Databases | Accepted | 2026-03-05 |
| [006](006-mcp-bridge-interface.md) | MCP as Universal Bridge Interface | Accepted | 2026-03-06 |

## Process

1. Copy `000-template.md` to `NNN-short-title.md`
2. Fill in all sections — especially **Alternatives Considered**
3. Submit for team review
4. Status moves: Proposed → Accepted → (optionally) Deprecated/Superseded

## Why ADRs Matter for Certification

Certifiers (ISO 27001, GDPR compliance, ČAK) need evidence of:
- **Deliberate design choices** (not accidental architecture)
- **Risk assessment** (consequences section)
- **Traceability** (who decided, when, why)
- **Alternative evaluation** (due diligence)

ADRs provide this evidence in a lightweight, developer-friendly format.

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

