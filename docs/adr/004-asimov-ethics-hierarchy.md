# ADR-004: Asimov Ethics Hierarchy (4-Tier)

**Status:** Accepted  
**Date:** 2026-03-08  
**Decision Makers:** Pavel (Vedoucí), Metod, Cyril  
**Relates to:** ADR-001, ADR-002

## Context

AI agents processing sensitive data need ethical guardrails. A flat list of rules doesn't capture priority — what happens when rules conflict? Asimov's Laws of Robotics provide a natural hierarchy model adapted for data ethics.

## Decision

Implement a 4-tier ethics hierarchy inspired by Asimov's Laws:

| Tier | Name | Priority | Enforcement |
|------|------|----------|-------------|
| **T0** | Humanity / Data Weaponization | Highest | Hard block (never override) |
| **T1** | Individual / PII / GDPR | High | Hard block |
| **T2** | Commands / Override Check | Medium | Soft rule (warn + log) |
| **T3** | Self-Protection / Backup | Low | Soft rule (warn + log) |

**T0/T1 = hard blocks** — content is rejected, no override possible.  
**T2/T3 = soft rules** — content is flagged with warnings but can proceed.

T0 includes: data weaponization prevention, bias amplification, mass surveillance enablement.  
T1 includes: PII detection, credential filtering, GDPR consent tracking.

## Consequences

### Positive
- Clear conflict resolution: higher tier always wins
- Certifiable: auditors see explicit priority ordering
- 14 rules across 4 tiers — comprehensive but manageable
- Three operating modes: warn (log only), enforce (block), off

### Negative
- May block legitimate content (false positives on PII patterns)
- Ethics checks add latency to learn() operations
- Rules need periodic review as regulations evolve

### Risks
- Under-blocking: rule doesn't catch a new PII pattern → regular rule updates needed
- Over-blocking: legitimate technical content flagged → configurable per-rule sensitivity

## Alternatives Considered

- **Flat rule list (no hierarchy):** No conflict resolution mechanism — rejected
- **3-tier (remove T0):** Data weaponization is a real risk that needs its own tier — rejected
- **LLM-based ethics (no rules):** Not deterministic, not certifiable — rejected

## References

- Pavel's approval 2026-03-08
- Isaac Asimov's Three Laws of Robotics (conceptual basis)
- `uaml/ethics/checker.py`
- EU AI Act risk classification framework

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

