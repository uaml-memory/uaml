# UAML v0.4.1 — Zpráva o nasazovacích testech

**Datum:** 2026-03-08  
**Tester:** Cyril (Notebook1, WSL2 Ubuntu)  
**Prostředí:** Python 3.12.3, čisté venv, pip install z privátního PyPI  
**Verze UAML:** 0.4.1 (wheel: `uaml-0.4.1-py3-none-any.whl`)  
**Zdroj PyPI:** Privátní PyPI server na VPS:8769 (pypiserver, auth: team)

---

## 1. Instalace

### 1.1 Čisté virtuální prostředí
```bash
python3 -m venv /home/pavel/uaml-clean-test
source /home/pavel/uaml-clean-test/bin/activate
```

### 1.2 Instalace z privátního PyPI
```bash
pip install --index-url http://team:<token>@127.0.0.1:18769/simple/ \
    --trusted-host 127.0.0.1 uaml
```
**Výsledek:** ✅ `Successfully installed click-8.3.1 uaml-0.4.0` (poté upgrade na 0.4.1)

### 1.3 Nainstalované závislosti
- `click>=8.0` (povinné) — ✅ automaticky nainstalováno
- `pqcrypto` (volitelné, pro PQC šifrování) — nainstalováno zvlášť
- `sentence-transformers` (volitelné, pro neurální embeddingy) — netestováno

---

## 2. Testy CLI příkazů (prázdná databáze)

| Příkaz | Výsledek | Poznámky |
|--------|----------|----------|
| `uaml init --db test.db` | ✅ PASS | Vytvořeno 13 tabulek |
| `uaml stats --db test.db` | ✅ PASS | Prázdná statistika, bez pádu |
| `uaml search --db test.db "query"` | ✅ PASS | „No results found" |
| `uaml learn --db test.db "test" --topic test` | ✅ PASS | Uložen záznam č. 1 |
| `uaml search --db test.db "test"` | ✅ PASS | Nalezen 1 výsledek |
| `uaml layers --db test.db` | ✅ PASS | Zobrazí 5 vrstev, 1 záznam |
| `uaml ethics check "safe text"` | ✅ PASS | Verdikt: APPROVED |
| `uaml ethics rules` | ✅ PASS | Vypsáno 13 pravidel |
| `uaml task add --db test.db "task"` | ✅ PASS | Vytvořen úkol č. 1 |
| `uaml task list --db test.db` | ✅ PASS | Zobrazí 1 úkol |
| `uaml io export --db test.db --output out.json` | ✅ PASS | Exportován 1 záznam |
| `uaml io import --db test2.db out.json` | ✅ PASS | Importován 1 záznam, 0 deduplikací |
| `uaml web --db test.db --port 8790` | ✅ PASS | Dashboard naslouchá na portu |
| `uaml api --db test.db` | ✅ PASS | REST API dostupné |
| `uaml serve` | ✅ PASS | MCP server spuštěn |

**Všech 15 CLI příkazů funguje na prázdné databázi bez chyb.**

---

## 3. Kompletní testovací sada (pytest)

### 3.1 Bez volitelných závislostí
```
465 passed, 24 failed in 31.80s
```
Všech 24 selhání: `ImportError: pqcrypto not installed` — očekávané pro volitelnou PQC závislost.

### 3.2 Se všemi závislostmi
```bash
pip install pqcrypto
python3 -m pytest tests/ -v --tb=short
```
```
489 passed in 31.59s
```
**Výsledek:** ✅ **489/489 PROŠLO, 0 SELHALO**

### 3.3 Pokrytí testů podle modulu
| Modul | Testy | Stav |
|-------|-------|------|
| `core/store.py` | Schema, CRUD, vyhledávání, vrstvy | ✅ |
| `core/associative.py` | Asociativní paměťový engine | ✅ |
| `core/reasoning.py` | Stopy uvažování | ✅ |
| `core/embeddings.py` | TF-IDF + volitelné neurální | ✅ |
| `ethics/checker.py` | 13 pravidel, Asimovova hierarchie | ✅ |
| `mcp/server.py` | 8 nástrojů, 2 zdroje | ✅ |
| `cli/main.py` | Všechny CLI příkazy | ✅ |
| `api/server.py` | REST API endpointy | ✅ |
| `api/client.py` | SDK klient | ✅ |
| `io/exporter.py` | JSON export | ✅ |
| `io/importer.py` | JSON import s deduplikací | ✅ |
| `io/backup.py` | Záloha/obnova | ✅ |
| `ingest/` | Chat, markdown, web ingestory | ✅ |
| `crypto/pqc.py` | ML-KEM-768 + AES-256-GCM | ✅ |
| `crypto/signatures.py` | ML-DSA podepisování agentů | ✅ |
| `compliance/auditor.py` | Kontroly GDPR + ISO 27001 | ✅ |
| `graph/sync.py` | Obousměrná synchronizace Neo4j | ✅ |
| `reasoning/incidents.py` | Pipeline incidentu→lekce | ✅ |
| `web/app.py` | Stránky dashboardu + API | ✅ |

---

## 4. Testy API endpointů (prázdná databáze)

| Endpoint | Metoda | Výsledek |
|----------|--------|----------|
| `/api/health` | GET | ✅ `{"status": "ok", "version": "0.4.1"}` |
| `/api/stats` | GET | ✅ Vrací nulové počty |
| `/api/knowledge` | GET | ✅ Vrací prázdný seznam |
| `/api/knowledge` | POST | ✅ Vytvoří záznam |
| `/api/tasks` | GET | ✅ Vrací prázdná/todo.db data |
| `/api/timeline` | GET | ✅ Vrací prázdný seznam |
| `/api/layers` | GET | ✅ Vrací rozpad podle vrstev |
| `/api/system` | GET | ✅ Vrací informace o stroji |
| `/api/projects` | GET | ✅ Vrací skupiny z todo.db |
| `/api/languages` | GET | ✅ Vrací 6 jazykových kódů |

---

## 5. Stránky dashboardu (vizuální kontrola)

| Stránka | Stav | Poznámky |
|---------|------|----------|
| Dashboard (📊) | ✅ | Systémové info, statistiky, vyhledávání |
| Knowledge (📚) | ✅ | Tabulka se záložním tématem |
| Tasks (✅) | ✅ | Kanban z todo.db |
| Graph (🔗) | ✅ | Zástupné místo (vyžaduje Neo4j) |
| Timeline (📅) | ✅ | Chronologické záznamy |
| Projects (📂) | ✅ | Skupiny todo.db s průběhem |
| Infrastructure (🖥️) | ✅ | Karty strojů |
| Team (👥) | ✅ | Karty agentů |
| Compliance (🔐) | ✅ | Stav auditu |
| Export (📦) | ✅ | Ovládání exportu |
| Settings (⚙️) | ✅ | Reference API |

### i18n (6 jazyků)
| Jazyk | Vlajka | Stav |
|-------|--------|------|
| English | 🇬🇧 | ✅ Výchozí |
| Čeština | 🇨🇿 | ✅ Navigace + záhlaví stránek |
| Slovenčina | 🇸🇰 | ✅ Navigace + záhlaví stránek |
| Polski | 🇵🇱 | ✅ Navigace + záhlaví stránek |
| Français | 🇫🇷 | ✅ Navigace + záhlaví stránek |
| Español | 🇪🇸 | ✅ Navigace + záhlaví stránek |

Výběr jazyka přetrvává přes localStorage po obnovení stránky.

---

## 6. Známé problémy

| # | Problém | Závažnost | Poznámky |
|---|---------|-----------|----------|
| 1 | `__version__` vrací „0.1.0" místo „0.4.1" | Nízká | `__init__.py` neaktualizováno |
| 2 | PQC testy selhávají bez `pqcrypto` (bez přeskočení) | Nízká | Mělo by používat `pytest.importorskip()` |
| 3 | Příkaz `web` chybí v wheelu v0.4.0 | Opraveno | Přítomno ve v0.4.1 |
| 4 | CLI `backup` používá `--json-output` místo `--output` | Nízká | Nekonzistence pojmenování |

---

## 7. Závěr

**UAML v0.4.1 projde všemi 489 testy při čisté instalaci z privátního PyPI.**

Balíček se instaluje bez externích závislostí (pouze `click`), vytváří funkční databázi od nuly a všechny funkce CLI/API/Dashboardu pracují na prázdné databázi.

Připraveno pro nasazení ve fázi 2: federovaná architektura s instancemi na každém stroji.

---

**Podpis:** Cyril (Notebook1)  
**Datum:** 2026-03-08 20:47 CET

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.
