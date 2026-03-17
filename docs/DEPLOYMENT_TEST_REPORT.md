# UAML v0.4.1 — Deployment Test Report

**Date:** 2026-03-08  
**Tester:** Cyril (Notebook1, WSL2 Ubuntu)  
**Environment:** Python 3.12.3, clean venv, pip install from Private PyPI  
**UAML Version:** 0.4.1 (wheel: `uaml-0.4.1-py3-none-any.whl`)  
**PyPI Source:** Private PyPI server at VPS:8769 (pypiserver, auth: team)

---

## 1. Installation

### 1.1 Clean Virtual Environment
```bash
python3 -m venv /home/pavel/uaml-clean-test
source /home/pavel/uaml-clean-test/bin/activate
```

### 1.2 Install from Private PyPI
```bash
pip install --index-url http://team:<token>@127.0.0.1:18769/simple/ \
    --trusted-host 127.0.0.1 uaml
```
**Result:** ✅ `Successfully installed click-8.3.1 uaml-0.4.0` (then upgraded to 0.4.1)

### 1.3 Dependencies Installed
- `click>=8.0` (required) — ✅ auto-installed
- `pqcrypto` (optional, for PQC encryption) — installed separately
- `sentence-transformers` (optional, for neural embeddings) — not tested

---

## 2. CLI Command Tests (Empty Database)

| Command | Result | Notes |
|---------|--------|-------|
| `uaml init --db test.db` | ✅ PASS | Created 13 tables |
| `uaml stats --db test.db` | ✅ PASS | Empty stats, no crash |
| `uaml search --db test.db "query"` | ✅ PASS | "No results found" |
| `uaml learn --db test.db "test" --topic test` | ✅ PASS | Stored entry #1 |
| `uaml search --db test.db "test"` | ✅ PASS | Found 1 result |
| `uaml layers --db test.db` | ✅ PASS | Shows 5 layers, 1 entry |
| `uaml ethics check "safe text"` | ✅ PASS | Verdict: APPROVED |
| `uaml ethics rules` | ✅ PASS | 13 rules listed |
| `uaml task add --db test.db "task"` | ✅ PASS | Created task #1 |
| `uaml task list --db test.db` | ✅ PASS | Shows 1 task |
| `uaml io export --db test.db --output out.json` | ✅ PASS | Exported 1 entry |
| `uaml io import --db test2.db out.json` | ✅ PASS | Imported 1 entry, 0 dedup |
| `uaml web --db test.db --port 8790` | ✅ PASS | Dashboard serves on port |
| `uaml api --db test.db` | ✅ PASS | REST API available |
| `uaml serve` | ✅ PASS | MCP server starts |

**All 15 CLI commands work on empty database without errors.**

---

## 3. Full Test Suite (pytest)

### 3.1 Without Optional Dependencies
```
465 passed, 24 failed in 31.80s
```
All 24 failures: `ImportError: pqcrypto not installed` — expected for optional PQC dependency.

### 3.2 With All Dependencies
```bash
pip install pqcrypto
python3 -m pytest tests/ -v --tb=short
```
```
489 passed in 31.59s
```
**Result:** ✅ **489/489 PASSED, 0 FAILED**

### 3.3 Test Coverage by Module
| Module | Tests | Status |
|--------|-------|--------|
| `core/store.py` | Schema, CRUD, search, layers | ✅ |
| `core/associative.py` | Associative memory engine | ✅ |
| `core/reasoning.py` | Reasoning traces | ✅ |
| `core/embeddings.py` | TF-IDF + optional neural | ✅ |
| `ethics/checker.py` | 13 rules, Asimov hierarchy | ✅ |
| `mcp/server.py` | 8 tools, 2 resources | ✅ |
| `cli/main.py` | All CLI commands | ✅ |
| `api/server.py` | REST API endpoints | ✅ |
| `api/client.py` | SDK client | ✅ |
| `io/exporter.py` | JSON export | ✅ |
| `io/importer.py` | JSON import with dedup | ✅ |
| `io/backup.py` | Backup/restore | ✅ |
| `ingest/` | Chat, markdown, web ingestors | ✅ |
| `crypto/pqc.py` | ML-KEM-768 + AES-256-GCM | ✅ |
| `crypto/signatures.py` | ML-DSA agent signing | ✅ |
| `compliance/auditor.py` | GDPR + ISO 27001 checks | ✅ |
| `graph/sync.py` | Neo4j bidirectional sync | ✅ |
| `reasoning/incidents.py` | Incident→lesson pipeline | ✅ |
| `web/app.py` | Dashboard pages + API | ✅ |

---

## 4. API Endpoint Tests (Empty Database)

| Endpoint | Method | Result |
|----------|--------|--------|
| `/api/health` | GET | ✅ `{"status": "ok", "version": "0.4.1"}` |
| `/api/stats` | GET | ✅ Returns zero counts |
| `/api/knowledge` | GET | ✅ Returns empty list |
| `/api/knowledge` | POST | ✅ Creates entry |
| `/api/tasks` | GET | ✅ Returns empty/todo.db data |
| `/api/timeline` | GET | ✅ Returns empty list |
| `/api/layers` | GET | ✅ Returns layer breakdown |
| `/api/system` | GET | ✅ Returns machine info |
| `/api/projects` | GET | ✅ Returns todo.db groups |
| `/api/languages` | GET | ✅ Returns 6 language codes |

---

## 5. Dashboard Pages (Visual Check)

| Page | Status | Notes |
|------|--------|-------|
| Dashboard (📊) | ✅ | System info, stats, search |
| Knowledge (📚) | ✅ | Table with topic fallback |
| Tasks (✅) | ✅ | Kanban from todo.db |
| Graph (🔗) | ✅ | Placeholder (needs Neo4j) |
| Timeline (📅) | ✅ | Chronological entries |
| Projects (📂) | ✅ | todo.db groups with progress |
| Infrastructure (🖥️) | ✅ | Machine cards |
| Team (👥) | ✅ | Agent cards |
| Compliance (🔐) | ✅ | Audit status |
| Export (📦) | ✅ | Export controls |
| Settings (⚙️) | ✅ | API reference |

### i18n (6 languages)
| Language | Flag | Status |
|----------|------|--------|
| English | 🇬🇧 | ✅ Default |
| Čeština | 🇨🇿 | ✅ Nav + page headers |
| Slovenčina | 🇸🇰 | ✅ Nav + page headers |
| Polski | 🇵🇱 | ✅ Nav + page headers |
| Français | 🇫🇷 | ✅ Nav + page headers |
| Español | 🇪🇸 | ✅ Nav + page headers |

Language selection persists via localStorage across page refresh.

---

## 6. Known Issues

| # | Issue | Severity | Notes |
|---|-------|----------|-------|
| 1 | `__version__` returns "0.1.0" instead of "0.4.1" | Low | `__init__.py` not updated |
| 2 | PQC tests fail without `pqcrypto` (no skip) | Low | Should use `pytest.importorskip()` |
| 3 | `web` command missing in v0.4.0 wheel | Fixed | Present in v0.4.1 |
| 4 | `backup` CLI uses `--json-output` not `--output` | Low | Naming inconsistency |

---

## 7. Conclusion

**UAML v0.4.1 passes all 489 tests on a clean installation from Private PyPI.**

The package installs with zero external dependencies (only `click`), creates a functional database from scratch, and all CLI/API/Dashboard features work on an empty database.

Ready for Phase 2 deployment: federated architecture with per-machine instances.

---

**Signed:** Cyril (Notebook1)  
**Date:** 2026-03-08 20:47 CET

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

