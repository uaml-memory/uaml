# ADR-001: Variant D — Certifiable Core with Universal Bridge

> **⚠️ Experimental Notice:** All features are experimental and under active development. Use at your own risk. APIs and behavior may change between versions.

**Status:** accepted  
**Date:** 2026-03-05  
**Decision makers:** Pavel (Vedoucí), Pepa2, Cyril  
**Context source:** Team discussion on Discord, strategic planning session

## Context

We need a persistent memory system for AI agents that can be certified for use in regulated industries (legal, insolvency, accounting). The system must be platform-agnostic — not tied to any specific AI agent framework.

Four architectural variants were evaluated:
- **A:** OpenClaw-native plugin (tightly coupled)
- **B:** Standalone REST service (loosely coupled, but complex)
- **C:** Library with OpenClaw adapter (middle ground)
- **D:** Certifiable core with universal bridge pattern

Target customers (lawyers, insolvency administrators, accountants) require the highest data protection standards, including GDPR compliance and potential ISO 27001 certification.

## Decision

**Variant D selected:** Build a certifiable core (memory.db + security + audit) that is 100% our own code, with a universal bridge layer that can connect to any AI framework.

- Core: SQLite-based, zero external dependencies, fully auditable
- OpenClaw: One adapter among many (not a dependency)
- Bridge: Capable of connecting to OpenClaw, LangChain, AutoGen, CrewAI, or any future framework
- Certification: We certify our core, not someone else's framework

## Consequences

### Positive
- **Certifiable:** Core is small, auditable, and fully under our control
- **Platform-agnostic:** Customers can use any AI framework
- **Future-proof:** Bridge can adapt to frameworks that don't exist yet
- **Commercial viability:** Proprietary software with free Community tier + paid enterprise tiers (PQC, compliance, multi-tenant)
- **Local operation:** Data never leaves customer hardware (key selling point for legal sector)

### Negative
- **More work upfront:** Must build adapters for each framework
- **No framework features for free:** Can't rely on OpenClaw internals
- **Testing surface:** Each adapter needs its own test suite

### Risks
- Bridge complexity may grow as frameworks evolve
- Must maintain backward compatibility for certified core
- Risk of feature creep in adapters polluting the core

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| A: OpenClaw plugin | Easy, fast development | Vendor lock-in, can't certify | Not certifiable independently |
| B: REST service | Clean separation | Complex deployment, latency | Over-engineered for our use case |
| C: Library + adapter | Good balance | Still somewhat coupled | Doesn't go far enough for certification |

## Compliance Impact

- **GDPR:** Core handles all data lifecycle (consent, erasure, retention) internally
- **ISO 27001:** Audit trail built into core, not delegated to framework
- **Certification:** Only core needs certification — adapters are customer responsibility

## References

- Team discussion: 2026-03-05, Discord #general
- Pavel's 5-layer data model: identity / knowledge / team / operational / project
- MEMORY.md: "Strategický produkt: UAML — Varianta D"

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

