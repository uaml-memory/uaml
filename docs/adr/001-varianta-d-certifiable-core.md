# ADR-001: Varianta D — Certifiable Core with Universal Bridge

> **⚠️ Experimental Notice:** All features are experimental and under active development. Use at your own risk. APIs and behavior may change between versions.

**Status:** Accepted  
**Date:** 2026-03-05  
**Decision Makers:** Pavel (Vedoucí), Metod, Cyril  
**Relates to:** ADR-002, ADR-003

## Context

We needed to decide the architecture for UAML (Universal Agent Memory Layer). Four variants were considered:
- **A:** Built on top of OpenClaw (tightly coupled)
- **B:** Fork OpenClaw and modify
- **C:** Standalone with OpenClaw adapter
- **D:** Certifiable core + universal bridge (framework-agnostic)

The target market (lawyers, insolvency administrators, accountants) requires certifiable software under GDPR, ISO 27001, and potentially sector-specific regulations (ČAK — Czech Bar Association).

## Decision

**Varianta D** — Build a certifiable core (memory.db + security + audit) that is 100% our code, with a universal bridge layer that can connect to any AI agent framework.

- Core is framework-agnostic: no OpenClaw, LangChain, or any framework dependency
- OpenClaw is one adapter/plugin among many
- Bridge can connect to OpenClaw, LangChain, AutoGen, CrewAI, custom runners
- Core is certifiable independently of the runtime framework

## Consequences

### Positive
- Certifiable: auditors review only our code, not third-party frameworks
- Universal: works with any AI agent framework, present or future
- Commercial: proprietary software with free Community tier + paid enterprise tiers (PQC, compliance, multi-tenant)
- Zero vendor lock-in for customers
- Smaller attack surface for security audits

### Negative
- More work: we build everything from scratch instead of leveraging existing tools
- Must maintain compatibility bridges for multiple frameworks
- No free ride on framework community/ecosystem

### Risks
- Competitor could build a certified solution faster on an existing framework
- Bridge maintenance burden grows with number of supported frameworks

## Alternatives Considered

- **Varianta A (OpenClaw-native):** Fastest to build, but ties certification to OpenClaw's codebase — rejected because we can't certify code we don't control
- **Varianta B (Fork):** Maintenance nightmare, diverging from upstream — rejected
- **Varianta C (Standalone + adapter):** Similar to D but less explicitly designed for certification — evolved into D

## References

- Pavel's strategic discussion 2026-03-05
- Competitive analysis: Zep, Mem0, Cognee, Microsoft GraphRAG (none combine ethics + PQC + local-first + certifiability)
- UAML DESIGN.md

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

