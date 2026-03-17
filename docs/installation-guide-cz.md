# UAML v1.0 — Instalační průvodce pro testery

> Krok za krokem pro první testery. Aktuální stav, březen 2026.

## Požadavky

- **Python 3.10+** (testováno na 3.12)
- **pip** (správce balíčků)
- **OS:** Linux, Windows (doporučen WSL2), macOS
- **Disk:** ~50 MB pro UAML + SQLite databázi
- **RAM:** ~100 MB za běhu (více pro hlasový pipeline)

## Krok 1: Instalace UAML

```bash
# Instalace ze zdrojového kódu (aktuální metoda)
git clone https://github.com/uaml/uaml.git
cd uaml
pip install -e .

# Nebo po publikaci na PyPI:
# pip install uaml
```

## Krok 2: Inicializace databáze

```bash
# Vytvoření UAML databáze
python3 -c "from uaml.core.store import MemoryStore; MemoryStore(); print('✅ Databáze vytvořena')"
```

Vytvoří `~/.uaml/uaml.db` (SQLite).

## Krok 3: Ověření instalace

```bash
# Spustit všechny testy
python3 -m pytest tests/ -q

# Očekávaný výsledek: 1117 passed

# Rychlý test
python3 -c "
from uaml.facade import UAML
uaml = UAML()
uaml.learn('Testovací záznam — instalace UAML úspěšná')
results = uaml.search('instalace')
print('✅ UAML funguje!' if results else '❌ Něco je špatně')
"
```

## Krok 4: Spuštění služeb

### UAML API Server (port 8780)
```bash
python3 -c "from uaml.api.server import serve; serve()" &
# → http://127.0.0.1:8780
```

### UAML Web Dashboard (port 8781)
```bash
python3 -c "from uaml.web.app import serve; serve()" &
# → http://127.0.0.1:8781
```

### Security Configurator (port 8785)
```bash
python3 -c "from uaml.security.configurator import SecurityConfigurator; SecurityConfigurator().serve()" &
# → http://127.0.0.1:8785
```

Otevřete v prohlížeči: `http://127.0.0.1:8785`

## Krok 5: Security Configurator (doporučeno)

1. Otevřete `http://127.0.0.1:8785` v prohlížeči
2. Průvodce automaticky detekuje váš OS
3. Projděte 6 kroků:
   - **Firewall** — pravidla pro UAML porty
   - **AV výjimky** — vyloučení `~/.uaml` ze skenování
   - **Šifrování** — BitLocker VHD (jen Windows)
   - **WSL2** — síťová konfigurace (jen Windows)
   - **Souborový systém** — restriktivní oprávnění
   - **Kontrola** — přehled příkazů, klikněte ▶️ Spustit
4. Každý příkaz ukazuje úroveň rizika (🟢/🟠/🔴)
5. Stáhněte audit report pro dokumentaci

## Použití Facade API

```python
from uaml.facade import UAML

uaml = UAML()

# Uložení znalosti
uaml.learn("Python 3.13 odstranil GIL", topic="python")

# Vyhledávání
results = uaml.search("Python vlákna")
for r in results:
    print(f"[{r.score:.2f}] {r.entry.content}")

# Audit
report = uaml.audit_report()

# Statistiky
stats = uaml.stats()
print(f"Celkem záznamů: {stats['knowledge']}")
```

## Dostupné moduly podle tarifu

### Komunita (zdarma)
- `uaml.core.store` — MemoryStore (SQLite)
- `uaml.core.schema` — 5vrstvá architektura
- `uaml.core.policy` — Klasifikace dotazů
- `uaml.core.config` — Správa konfigurace
- `uaml.crypto.pqc` — Post-kvantové šifrování
- `uaml.facade` — Jednotné API
- `uaml.cli` — Příkazový řádek

### Starter (€8/měs)
- Vše z Komunity, plus:
- `uaml.compliance.*` — Auditor, Souhlas, DPIA, Inventář
- `uaml.api.*` — REST API server + klient
- `uaml.security.configurator` — Security Configurator

### Professional (€29/měs)
- Vše ze Starteru, plus:
- `uaml.voice.*` — TTS + STT pipeline
- `uaml.security.configurator.ExpertMode` — Expert na vyžádání
- `uaml.graph.*` — Knowledge graf
- `uaml.federation.*` — Multi-agent sdílení
- `uaml.reasoning.*` — Temporální, kontext, skóring, clustering

### Tým (€190/měs)
- Vše z Professional, plus:
- Až 5 AI agentů
- `uaml.graph.sync` — Neo4j synchronizace
- `uaml.security.rbac` — Řízení přístupu na základě rolí
- `uaml.audit.*` — Kompletní audit trail + provenance

### Enterprise (na míru)
- Vše z Tým, neomezený počet agentů
- Úschova klíčů, FIDO2, DPIA nástroje
- On-premise nasazení, SLA

## Přehled portů

| Služba | Port | URL |
|--------|------|-----|
| UAML API | 8780 | http://127.0.0.1:8780 |
| UAML Dashboard | 8781 | http://127.0.0.1:8781 |
| Security Configurator | 8785 | http://127.0.0.1:8785 |

## Řešení problémů

### Port je obsazený
```bash
# Zjistit co port používá
ss -tlnp | grep 8785
# Ukončit proces
kill <PID>
```

### Databáze zamknutá
```bash
# Najednou smí zapisovat jen jeden proces
ps aux | grep uaml
```

### Windows / WSL2
- Porty se automaticky forwardují z WSL2 do Windows
- Otevřete `http://localhost:8785` ve Windows prohlížeči
- Pokud nefunguje: `wsl --list --verbose`

### Raspberry Pi
- Testováno na Pi 4 (4 GB RAM)
- Hlasový pipeline: Piper TTS + Whisper.cpp (lehké)
- SQLite funguje skvěle na ARM

## Hlášení chyb

Email: support@uaml.ai

Uveďte:
- OS a verzi Pythonu
- Chybovou hlášku / traceback
- Kroky k reprodukci

---

*© 2026 GLG, a.s. — UAML v1.0*
