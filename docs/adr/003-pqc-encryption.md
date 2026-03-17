# ADR-003: Post-Quantum Cryptography (ML-KEM-768 + AES-256-GCM)

**Status:** accepted  
**Date:** 2026-03-06  
**Decision makers:** Pavel (Vedoucí)  
**Context source:** Security requirements for regulated industries, NIST standards

## Context

Target customers (lawyers, insolvency administrators) handle extremely sensitive data. Current encryption standards (RSA, ECDSA) are vulnerable to future quantum computers. NIST has finalized post-quantum cryptography standards (FIPS 203/204/205).

We need encryption that will remain secure for 10+ years — the expected lifetime of data we protect.

## Decision

Implement **ML-KEM-768 (Kyber)** for key encapsulation + **AES-256-GCM** for symmetric data encryption, following NIST FIPS 203.

Additionally planned:
- **ML-DSA (Dilithium)** for digital signatures (FIPS 204) — implemented in v0.4.1
- **SLH-DSA (SPHINCS+)** for stateless hash-based signatures (FIPS 205) — future

Implementation uses pure Python with no external crypto dependencies beyond stdlib, ensuring certifiability. Clear upgrade path to C-level libraries when they mature.

## Consequences

### Positive
- **Quantum-resistant:** Data encrypted today remains safe against future quantum attacks
- **Standard compliance:** NIST FIPS 203 = internationally recognized standard
- **Competitive advantage:** Few AI memory systems offer PQC encryption
- **Customer confidence:** "Quantum-safe" is a strong selling point for regulated industries
- **Future-proof:** Won't need re-encryption when quantum computers arrive

### Negative
- **Larger key sizes:** ML-KEM-768 keys are ~1 KB vs ~32 bytes for X25519
- **Performance overhead:** KEM operations slower than classical ECDH
- **Library maturity:** PQC libraries still evolving, may need updates

### Risks
- NIST may update recommended parameters (mitigated by modular design)
- Pure Python implementation is slower than C (acceptable for our scale)

## Compliance Impact

- **GDPR Art. 32:** "State of the art" encryption — PQC exceeds this requirement
- **ISO 27001 A.8.24:** Encryption control fully satisfied
- **Certification:** NIST FIPS compliance = recognized by auditors worldwide
- **Legal sector:** Demonstrates due diligence in data protection

## References

- NIST FIPS 203: ML-KEM (Module-Lattice-Based Key-Encapsulation Mechanism)
- NIST FIPS 204: ML-DSA (Module-Lattice-Based Digital Signature Algorithm)
- NIST FIPS 205: SLH-DSA (Stateless Hash-Based Digital Signature Algorithm)
- Implementation: uaml/crypto/pqc.py, uaml/crypto/signatures.py

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

