# Focus Engine — Implementační reference

> © 2026 GLG, a.s. | UAML v1.0 | Status: DRAFT

## Přehled

Focus Engine řídí, jaká data vstupují a opouštějí znalostní graf UAML:

1. **Vstupní filtr** (`uaml.ingest.filters`) — 6 filtračních stupňů před uložením
2. **Výstupní filtr / Focus Engine** (`uaml.core.focus_engine`) — recall s token budgetem
3. **Konfigurace** (`uaml.core.focus_config`) — YAML/JSON s validací a presety
4. **Historie změn** (`uaml.core.rules_changelog`) — SQLite audit trail
5. **Uložené konfigurace** (`uaml.core.focus_config.SavedConfigStore`) — pojmenované snapshoty

## Architektura

```
Data → [Vstupní filtr] → Neo4j/SQLite
                              ↓
Dotaz agenta → [Focus Engine] → Filtrovaný kontext → Agent
                    ↑
             FocusEngineConfig (YAML)
                    ↑
             Rules Changelog (SQLite audit)
```

## Vstupní filtr

6 sekvenčních stupňů:

| Stupeň | Funkce | Účel |
|--------|--------|------|
| 1 | Délka | Odmítne záznamy pod `min_entry_length` znaků |
| 2 | Tokeny | Odmítne nad `max_entry_tokens` tokenů |
| 3 | PII detektor | Detekce osobních údajů (email, telefon, RČ, kreditní karta) |
| 4 | Kategorie | Pravidla per kategorie (allow/deny/encrypt/require_consent) |
| 5 | Rate limit | Token-bucket omezení (`rate_limit_per_min`) |
| 6 | Relevance | Odmítne pod `min_relevance_score` |

## Výstupní filtr (Focus Engine)

Zpracování:
1. Filtr dle `min_relevance_score`
2. Časový úpadek (temporal decay)
3. Řazení dle upraveného skóre
4. Limit na `max_records`
5. Výběr obsahu dle recall tieru (1=summary, 2=mix, 3=full)
6. Deduplikace dle `dedup_similarity`
7. Naplnění token budgetu

## Presety

| Preset | Token budget | Max záznamů | Relevance | Tier | Použití |
|--------|-------------|-------------|-----------|------|---------|
| `conservative` | 1500 | 5 | 0.5 | 1 | Produkce, šetření tokenů |
| `standard` | 2000 | 10 | 0.3 | 1 | Obecné použití |
| `research` | 8000 | 25 | 0.2 | 3 | Hloubková analýza |

## Přístupové rozhraní

Dostupné přes 4 rozhraní:
- **Python API**: `from uaml.facade import UAML` → `uaml.focus_recall(query, budget)`
- **REST API**: `GET/PUT /api/v1/focus-config`, `POST /api/v1/focus-recall`
- **MCP**: nástroj `memory_focus_recall`
- **CLI**: `uaml focus recall "dotaz" --budget 2000`

## Testy

- 62 unit testů + 14 integračních + 12 SavedConfigStore + 27 MCP
- Celkem: 1347+ testů

## Soubory

| Soubor | Řádků | Účel |
|--------|-------|------|
| `uaml/core/focus_config.py` | 844 | Konfigurace, validace, presety, SavedConfigStore |
| `uaml/core/focus_engine.py` | 385 | Výstupní filtr, token budgeting |
| `uaml/ingest/filters.py` | 293 | 6 vstupních filtrů |
| `uaml/core/rules_changelog.py` | 316 | Audit trail |

Detailní API reference viz anglická verze (`focus-engine-reference.md`).
