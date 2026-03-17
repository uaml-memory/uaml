# ADR-005: ML-DSA Agent Signatures for Data Integrity

**Status:** accepted  
**Date:** 2026-03-08  
**Decision makers:** Pavel (Vedoucí), Pepa2  
**Context source:** Multi-agent security requirements, NIST FIPS 204

## Context

In a multi-agent system, any agent can write to the shared knowledge database. Without authentication, a compromised agent could inject false data, modify existing entries, or impersonate another agent — all undetected.

This is especially critical for our target customers (legal sector) where data integrity is a legal requirement.

## Decision

Every agent signs every piece of data it produces using **ML-DSA (Dilithium) compatible digital signatures**.

Architecture:
1. Each agent generates a unique signing keypair on first run
2. Every knowledge entry, task, and artifact includes a signature envelope
3. The shared database accepts only correctly signed data
4. Any agent (or auditor) can verify signatures using public keys
5. Tampered data is detected automatically via signature mismatch

Current implementation uses Ed25519-compatible HMAC scheme with a clear upgrade path to ML-DSA when mature libraries are available.

## Consequences

### Positive
- **Tamper detection:** Any modification to signed data is immediately detectable
- **Non-repudiation:** Each entry is provably linked to a specific agent
- **Compromise isolation:** A compromised agent's damage is identifiable and containable
- **Audit trail:** Signatures provide cryptographic proof of authorship
- **Trust chain:** New agents must be explicitly trusted (public key registered)

### Negative
- **Storage overhead:** Each entry gains ~200 bytes for signature envelope
- **Key management:** Agent keys must be backed up and managed
- **Complexity:** Signature verification adds processing to every read

### Risks
- Key loss = inability to verify historical data (mitigation: key escrow)
- Clock skew between agents could cause timestamp verification issues

## Compliance Impact

- **GDPR Art. 5(1)(f):** Integrity and confidentiality — signatures ensure integrity
- **ISO 27001 A.8.3:** Access control — signatures prove identity
- **ISO 27001 A.8.15:** Audit trail — cryptographic proof of every action
- **Certification:** Digital signatures are a recognized security control

## References

- NIST FIPS 204: ML-DSA (Module-Lattice-Based Digital Signature Algorithm)
- Implementation: uaml/crypto/signatures.py
- Tests: tests/test_signatures.py (32 tests)

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

