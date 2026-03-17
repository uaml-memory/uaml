# ADR-004: Five-Layer Data Classification Model

**Status:** accepted  
**Date:** 2026-03-05  
**Decision makers:** Pavel (Vedoucí)  
**Context source:** Pavel's strategic vision, team discussion

## Context

AI agents accumulate different types of information with different sensitivity levels, access requirements, and retention policies. A flat storage model makes it impossible to enforce proper data governance.

Pavel defined a 5-layer classification inspired by how humans organize their memories and knowledge.

## Decision

All data in UAML is classified into exactly one of five layers:

| Layer | Description | Sensitivity | Storage Analogy | Retention |
|-------|-------------|-------------|-----------------|-----------|
| **Identity** | Agent personality, preferences, core values | Highest | RAM disk | Indefinite |
| **Knowledge** | Learned facts, skills, expertise | High | SSD | Configurable |
| **Team** | Shared team experiences, collaborative learnings | Medium | SSD/HDD | 180 days default |
| **Operational** | Infrastructure, services, monitoring, security | Medium | SSD/HDD | 90 days default |
| **Project** | Client data, project artifacts, deliverables | Varies | HDD/NAS | Per-project |

Key principles:
- **Contextual isolation:** Data from different clients/projects MUST NOT cross boundaries
- **Layer-based access control:** Identity layer has strictest access
- **Layer-based retention:** Each layer has its own retention policy
- **Export control:** Identity export requires extra authorization

## Consequences

### Positive
- **Clear data governance:** Every record has a classification
- **GDPR-ready:** Retention policies per layer satisfy data minimization
- **Access control:** Layer-based permissions map cleanly to roles
- **Client isolation:** Project layer enforces per-client separation
- **Audit clarity:** Auditors can assess each layer independently

### Negative
- **Classification burden:** Every knowledge entry must be classified
- **Migration complexity:** Existing data needs layer assignment
- **Edge cases:** Some data fits multiple layers (resolved: pick the most sensitive)

### Risks
- Misclassification could expose sensitive data at wrong access level
- Mitigation: Default to higher sensitivity when uncertain

## Compliance Impact

- **GDPR Art. 5(1)(c):** Data minimization through layer-specific retention
- **GDPR Art. 5(1)(e):** Storage limitation enforced per layer
- **ISO 27001 A.8.2:** Information classification directly implemented
- **Certification:** Classification scheme is auditor-friendly — maps to ISO 27001 Annex A

## References

- Pavel's 5-layer model: MEMORY.md "Pavlovo 5-vrstvé dělení informací"
- Implementation: uaml/core/schema.py (DataLayer enum)
- Storage architecture plan: RAM disk / SSD / HDD / NAS hierarchy

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

