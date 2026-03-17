# UAML Recall Pipeline — Průvodce nasazením

> Nasazeno: 2026-03-15 | Stav: Produkce | Uzly: Cyril (Notebook1), Metod (VPS)

## Přehled architektury

```
OpenClaw Session Logy (*.jsonl)
        │
        ▼
┌─────────────────────────┐
│  Bridge                 │  tools/uaml_openclaw_bridge.py
│  ├─ Filtr šumu          │  přeskakuje OK / NO_REPLY / HEARTBEAT_OK
│  ├─ Detekce PII         │  >3 PII = zamítnutí, ≤3 = označení
│  └─ Klasifikátor        │  9 kategorií (klíčová slova)
└─────────┬───────────────┘
          ▼
    data/memory.db (SQLite, FTS5)
          │
    ┌─────┴─────┐
    ▼           ▼
┌────────┐  ┌──────────────┐
│ MCP    │  │ Focus Engine  │  uaml/core/focus_engine.py
│ Server │  │ (filtr výstupu)│
│ :8770  │  └──────────────┘
└────────┘
    │
    ▼
┌────────────────┐
│ SyncEngine     │  uaml/sync.py
│ JSONL přes git │
└────────────────┘
```

### Komponenty

| Komponenta | Soubor | Účel |
|------------|--------|------|
| **Bridge** | `tools/uaml_openclaw_bridge.py` | Ingestuje zprávy asistenta ze session logů do `data/memory.db` |
| **MCP Server** | `tools/uaml_mcp_server.py` | Zpřístupňuje `memory_search` přes MCP protokol (SSE, port 8770) |
| **Focus Engine** | `uaml/core/focus_engine.py` | Filtruje výsledky dle citlivosti, relevance, časového rozpadu, deduplikace, token budgetu |
| **SyncEngine** | `uaml/sync.py` | Synchronizace znalostí mezi uzly přes JSONL a git |
| **Fallback** | `tools/uaml_recall.sh` | Přímé FTS hledání když MCP není dostupný |

### Vstupní filtry (Bridge)

1. **Filtr šumu** — přeskakuje zprávy `OK`, `NO_REPLY`, `HEARTBEAT_OK`
2. **Detekce PII** — skenuje osobní údaje; >3 nálezy = zamítnutí celé zprávy, ≤3 = označení a ingestování
3. **Klasifikátor kategorií** — na bázi klíčových slov, přiřazuje jednu z 9 kategorií:
   `decision`, `infrastructure`, `code`, `security`, `research`, `product`, `legal`, `communication`, `process`

## Nastavení na každém uzlu

Každý uzel agenta provozuje tři služby:

1. **Lokální bridge** (watch režim) — sleduje vlastní session logy, plní lokální `data/memory.db`
2. **Lokální MCP server** — poskytuje recall nástroje agentovi přes MCP
3. **SyncEngine** — exportuje/importuje faktické znalosti jako JSONL changelogy přes git

## Systemd služby (user-level)

### uaml-bridge.service

```ini
[Unit]
Description=UAML Bridge — ingestování session logů
After=network.target

[Service]
Type=simple
Environment=UAML_DB=%h/.openclaw/workspace/data/memory.db
Environment=UAML_AGENT=Cyril
ExecStart=/usr/bin/python3 %h/.openclaw/workspace/tools/uaml_openclaw_bridge.py --watch
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### uaml-mcp.service

```ini
[Unit]
Description=UAML MCP Server — recall hledání přes SSE
After=network.target uaml-bridge.service

[Service]
Type=simple
Environment=UAML_DB=%h/.openclaw/workspace/data/memory.db
Environment=UAML_AGENT=Cyril
ExecStart=/usr/bin/python3 %h/.openclaw/workspace/tools/uaml_mcp_server.py --port 8770
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

### Správa

```bash
systemctl --user enable uaml-bridge.service uaml-mcp.service
systemctl --user start uaml-bridge.service uaml-mcp.service
systemctl --user status uaml-bridge.service uaml-mcp.service
journalctl --user -u uaml-mcp.service -f   # živé logy
```

## Proměnné prostředí

| Proměnná | Povinná | Popis | Příklad |
|----------|---------|-------|---------|
| `UAML_DB` | Ano | Cesta k `memory.db` | `~/.openclaw/workspace/data/memory.db` |
| `UAML_AGENT` | Ano | Jméno agenta pro atribuci záznamů | `Cyril`, `Metod` |
| `UAML_NODE_ID` | Pro sync | Identifikátor uzlu pro SyncEngine | `notebook1`, `vps` |

## Integrace do SOUL.md — Recall protokol

Agenti dodržují třístupňový recall mechanismus (definovaný v SOUL.md):

1. **Zkusit `memory_search`** (vestavěný v OpenClaw) — prohledává markdown soubory
2. **Dotaz na `data/memory.db` přes MCP** — strukturované znalosti s kategoriemi a konfidencí
   ```bash
   curl -s -X POST http://localhost:8770/message \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_search","arguments":{"query":"DOTAZ","limit":5}}}'
   ```
3. **Fallback skript** (pokud MCP selže) — přímé FTS hledání + nahlášení problému
   ```bash
   tools/uaml_recall.sh "DOTAZ" 5
   ```

**Pravidlo:** Nikdy neříkej „nevím" dříve, než prohledáš všechny tři úrovně.

## Datové schéma

Tabulka `knowledge` v `memory.db`:

| Sloupec | Typ | Popis |
|---------|-----|-------|
| `id` | INTEGER | Primární klíč (autoincrement) |
| `ts` | TEXT | Časové razítko ISO 8601 |
| `agent` | TEXT | Jméno zdrojového agenta |
| `topic` | TEXT | Extrahované téma |
| `summary` | TEXT | Jednořádkové shrnutí |
| `content` | TEXT | Plný obsah zprávy (FTS-indexovaný) |
| `category` | TEXT | Jedna z 9 kategorií |
| `tags` | TEXT | Tagy oddělené čárkou |
| `confidence` | REAL | Skóre konfidence 0.0–1.0 |
| `source_type` | TEXT | Typ zdroje (`session`, `sync`, `manual`) |
| `source_ref` | TEXT | Cesta ke zdrojovému souboru nebo reference |

## Známá omezení

| Omezení | Dopad | Řešení |
|---------|-------|--------|
| Bridge zpracovává jen zprávy asistenta | Uživatelské zprávy nejsou indexovány | Ruční ingestování v případě potřeby |
| Klasifikátor na bázi klíčových slov | Žádné sémantické porozumění | Dostačující pro současnou 9-kategoriální taxonomii |
| FTS hledání je pouze lexikální | Žádné sémantické/vektorové hledání | Více přeformulování dotazů |
| PQC podepisování neaktivní | Chybí knihovna `pqcrypto` | Plánováno pro budoucí verzi |
| SyncEngine plný export ~177MB | Velký počáteční přenos | Použít `scp` pro první sync, git jen pro delty |
