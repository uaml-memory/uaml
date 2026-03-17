# UAML v0.4.1 — Test Report

**Date:** 2026-03-08  
**Version:** 0.4.1  
**Source:** Private PyPI (127.0.0.1:8769)  
**Type:** Clean installation verification

## Summary

| Metric | Result |
|--------|--------|
| **Total tests** | 489 |
| **Passed** | 489 |
| **Failed** | 0 |
| **Errors** | 0 |
| **Status** | ✅ ALL PASSED |

## Test Environment

### Tester 1: Cyril (Notebook1)
- **OS:** Linux WSL2 (Ubuntu), kernel 6.6.87.2-microsoft-standard-WSL2
- **Hardware:** 24 cores, 125.5 GB RAM, RTX 5090 24GB
- **Python:** 3.12.3
- **Install method:** `pip install uaml==0.4.1` from private PyPI
- **Duration:** 31.6s
- **Result:** 489/489 PASSED ✅
- **Notes:** 465 passed without pqcrypto, +24 PQC tests after `pip install pqcrypto`

### Tester 2: Metod (VPS)
- **OS:** Ubuntu 24.04 LTS, kernel 6.8.0-101-generic
- **Hardware:** 4 vCPU, 8 GB RAM (Contabo VPS)
- **Python:** 3.12.3
- **Install method:** `pip install uaml==0.4.1` from private PyPI
- **Duration:** 54.13s
- **Result:** 489/489 PASSED ✅

## Test Categories

| Module | Tests | Status |
|--------|-------|--------|
| core (MemoryStore, schema, search) | ~120 | ✅ |
| compliance (GDPR, ISO 27001 audit) | ~45 | ✅ |
| crypto/pqc (ML-KEM-768 encryption) | ~24 | ✅ |
| crypto/signatures (ML-DSA, HMAC) | 32 | ✅ |
| reasoning/incidents (incident→lesson) | 26 | ✅ |
| graph (Neo4j sync engine) | ~30 | ✅ |
| api (REST API server) | ~40 | ✅ |
| web (dashboard, templates, static) | 23 | ✅ |
| io (export/import JSON) | ~20 | ✅ |
| cli (command-line interface) | ~30 | ✅ |
| embeddings (TF-IDF hybrid) | ~20 | ✅ |
| benchmark (LongMemEval) | ~15 | ✅ |

## Clean Installation Verification

Both testers performed a fresh install from private PyPI:

1. ✅ `pip install uaml==0.4.1` — installs without errors
2. ✅ Empty database creation — 13 tables created automatically
3. ✅ All CLI commands functional (`init`, `learn`, `search`, `stats`, `serve`, `web`, `api`)
4. ✅ REST API returns valid empty responses on fresh DB
5. ✅ Dashboard renders all 11 pages without errors on empty DB
6. ✅ Ethics engine: 13 rules loaded, check/rules commands work
7. ✅ Export/import cycle: data integrity preserved
8. ✅ PQC encryption: ML-KEM-768 key generation + encrypt/decrypt cycle

## Known Limitations

- `pqcrypto` is optional dependency — 24 PQC tests skip without it
- Neural embedding tests require `sentence-transformers` (optional)
- Neo4j sync tests use mock (no live Neo4j required)
- `__version__` was "0.1.0" in initial build (fixed in rebuild)

## Deployment Checklist

- [x] Build wheel from source (`python3 -m build`)
- [x] Upload to private PyPI (`/opt/pypi/packages/`)
- [x] Clean install on Notebook1 (Cyril)
- [x] Clean install on VPS (Metod)
- [x] Full test suite on both machines
- [x] Empty DB functionality verified
- [ ] Systemd service for dashboard (TODO)
- [ ] Production deployment documentation (TODO)
- [ ] Penetration test report (TODO)

## Conclusion

UAML v0.4.1 passes all 489 tests on two independent machines with clean installation from private PyPI. The package is ready for production deployment in federated architecture (ADR-007).

---
**Signed:** Metod (VPS) + Cyril (Notebook1)  
**Reviewed by:** Pavel (Vedoucí) — pending

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

