# ADR-002: Five-Layer Data Architecture

**Status:** Accepted  
**Date:** 2026-03-08  
**Decision Makers:** Pavel (Vedoucí), Metod, Cyril  
**Relates to:** ADR-001, ADR-005

## Context

AI agents need different types of memory with different security levels, sharing rules, and storage characteristics. Pavel proposed a 5-layer model based on human cognitive analogy:

1. Personal/identity data (never shared)
2. Knowledge and skills (semi-private)
3. Team experiences (shared but personal conclusions private)
4. Operational/security data (shared with access control)
5. Project data/media (centralized, largest by volume)

## Decision

Implement 5 data layers with distinct security and sharing policies:

| Layer | Analogy | Storage | Sharing |
|-------|---------|---------|---------|
| **IDENTITY** | RAM disk | Hot, encrypted | Never (restore only, not clone) |
| **KNOWLEDGE** | SSD | Semi-private | Explicit export/import only |
| **TEAM** | SSD/HDD | Shared | Per-team, personal conclusions private |
| **OPERATIONAL** | SSD/HDD | Access-controlled | Signed data, audit trail |
| **PROJECT** | HDD/NAS | Centralized | Per-client isolated |

Each knowledge entry has a `data_layer` field. Export respects layer boundaries — IDENTITY requires explicit `--confirm-identity` flag and master key.

## Consequences

### Positive
- Clear data classification from day one (ISO 27001 A.8.2 compliance)
- Per-layer export enables GDPR Art. 15 (right of access) and Art. 20 (portability)
- Identity protection by design (not an afterthought)
- Maps cleanly to physical storage tiers (RAM → SSD → HDD → NAS)

### Negative
- Every query/export must respect layer boundaries — adds complexity
- Layer assignment requires judgment (manual or heuristic)

### Risks
- Misclassification: sensitive data in wrong layer → exposure
- Mitigation: ethics pipeline checks + audit log for layer changes

## Alternatives Considered

- **Flat storage (no layers):** Simpler but impossible to implement per-client isolation or GDPR compliance — rejected
- **3-layer (private/shared/public):** Too coarse for our security requirements — rejected
- **Tag-based (no fixed layers):** Flexible but no structural guarantees for auditors — rejected

## References

- Pavel's 5-layer discussion 2026-03-05
- ISO 27001 A.8.2 (Data Classification)
- GDPR Art. 5 (Purpose Limitation), Art. 25 (Data Protection by Design)

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

