# UAML REST API — Reference

> © 2026 GLG, a.s. | UAML v1.0 | Stav: NÁVRH

## Přehled

UAML dashboard vystavuje REST API na portu 8780 (výchozí). Všechny endpointy vrací JSON. Pro lokální přístup není vyžadována autentizace.

## Systém a zdraví

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/system` | Systémové informace (verze, uptime, Python, OS) |
| GET | `/api/health` | Kontrola zdraví |
| GET | `/api/stats` | Statistiky databáze (vzpomínky, zdroje, vrstvy) |

## Graf znalostí

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/knowledge` | Všechny vzpomínky (se stránkováním: `?limit=&offset=`) |
| GET | `/api/knowledge/<id>` | Jeden záznam vzpomínky |
| POST | `/api/knowledge` | Uložit novou vzpomínku (tělo: `{content, source, ...}`) |

## Focus Engine (v1 API)

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/v1/focus-config` | Aktuální konfigurace focus |
| PUT | `/api/v1/focus-config` | Aktualizovat konfiguraci focus |
| GET | `/api/v1/focus-config/presets` | Seznam vestavěných přednastavení |
| POST | `/api/v1/focus-recall` | Spustit focus recall (tělo: `{query, budget, tier}`) |

### Uložené konfigurace

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/v1/saved-configs?filter_type=input\|output` | Výpis uložených konfigurací |
| GET | `/api/v1/saved-configs/<name>` | Získat konfiguraci podle názvu |
| POST | `/api/v1/saved-configs` | Uložit konfiguraci (tělo: `{name, config, filter_type, description}`) |
| POST | `/api/v1/saved-configs/load` | Načíst konfiguraci (tělo: `{name, filter_type}`) |
| POST | `/api/v1/saved-configs/delete` | Smazat konfiguraci (tělo: `{name, filter_type}`) |
| POST | `/api/v1/saved-configs/activate` | Nastavit aktivní konfiguraci (tělo: `{name, filter_type}`) |
| GET | `/api/v1/active-config?filter_type=input\|output` | Získat název aktivní konfigurace |

### Protokol změn pravidel

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/v1/rules-log?limit=50&offset=0` | Záznamy auditního protokolu |
| GET | `/api/v1/rules-log/stats` | Statistiky protokolu změn |

## Data a uvažování

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/tasks` | Úkoly z grafu znalostí |
| GET | `/api/timeline` | Události na časové ose |
| GET | `/api/layers` | Rozpad datových vrstev |
| GET | `/api/reasoning` | Záznamy stop uvažování |
| GET | `/api/compliance` | Stav souladu |

## Projekty a tým

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/projects` | Všechny projekty |
| GET | `/api/projects/<id>` | Detail jednoho projektu |
| GET | `/api/infrastructure` | Záznamy infrastruktury |
| GET | `/api/team` | Členové týmu |
| GET | `/api/languages` | Dostupné jazyky |

## Konfigurace a shrnutí

| Metoda | Endpoint | Popis |
|--------|----------|-------|
| GET | `/api/config` | Aktuální konfigurace UAML |
| GET | `/api/summaries?kind=daily\|weekly&limit=10` | Index shrnutí |

## Formát odpovědí

Všechny endpointy vrací JSON:

```json
{
  "field": "value",
  ...
}
```

Chybové odpovědi:
```json
{
  "error": "popis"
}
```

HTTP stavové kódy: `200` OK, `400` Špatný požadavek, `404` Nenalezeno, `500` Interní chyba.

## MCP nástroje (přes MCP bridge)

9 nástrojů dostupných přes protokol MCP:

| Nástroj | Popis |
|---------|-------|
| `memory_store` | Uložit záznam vzpomínky |
| `memory_recall` | Vybavit vzpomínky podle dotazu |
| `memory_focus_recall` | Vybavení s tokenovým rozpočtem a Focus Engine |
| `memory_search` | Fulltextové vyhledávání |
| `memory_forget` | Soft-delete vzpomínky |
| `memory_stats` | Statistiky databáze |
| `memory_health` | Kontrola zdraví |
| `memory_export` | Export vzpomínek |
| `memory_import` | Import vzpomínek |

## Stránky dashboardu

| Trasa | Šablona | Popis |
|-------|---------|-------|
| `/` | `index.html` | Hlavní dashboard |
| `/input-filter` | `input-filter.html` | Konfigurace vstupního filtru |
| `/output-filter` | `output-filter.html` | Konfigurace výstupního filtru / Focus Engine |
| `/rules-log` | `rules-log.html` | Auditní protokol změn pravidel |
