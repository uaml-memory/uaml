# Security Configurator (CZ)

> Chybějící díl skládačky: GUI nástroj pro zabezpečení prostředí, kde váš AI agent běží.

## Přehled

UAML Security Configurator je **webový průvodce**, který uživatele provede zabezpečením operačního systému pro nasazení AI agenta. Není potřeba znát příkazový řádek — vše je na kliknutí.

**Klíčový princip:** Konfigurátor běží **pouze lokálně** (`127.0.0.1:8785`). Nikdy se nevystavuje do sítě. AI agent k němu nemá přístup — bezpečnostní rozhodnutí dělá vždy člověk.

## Funkce

### 🔥 Konfigurace firewallu
- **Linux:** UFW, iptables
- **Windows:** Windows Firewall (netsh)
- **macOS:** pf (packet filter)

Generuje a spouští pravidla firewallu pro ochranu UAML portů a datových adresářů.

### 🛡️ Výjimky antivirů
- **Windows Defender** — správa výjimek přes PowerShell
- **macOS Spotlight** — výjimky přes mdutil
- **Linux ClamAV** — konfigurace clamd

Vyloučí UAML datové adresáře (`~/.uaml`, `~/.openclaw`) ze skenování — předchází problémům s výkonem a falešně pozitivním detekcím.

### 🔐 BitLocker VHD šifrování
- Vytvoří šifrovaný virtuální disk (VHD) pro UAML data
- Šifrování XTS-AES-256
- Správa recovery klíčů
- Pouze Windows

### 🌐 Konfigurace WSL2
- Nastavení síťové izolace
- Pravidla firewallu pro komunikaci WSL2 ↔ host
- Konfigurace DNS

### 📁 Hardening souborového systému
- Nastavení restriktivních oprávnění na UAML adresáře
- Linux: `chmod 700` na datové adresáře
- Windows: konfigurace ACL

### 🔌 Síťový profil
- Konfigurace síťového rozhraní
- Vypnutí nepotřebných služeb
- Nastavení odpovídajících zón firewallu

## Rychlý start

```python
from uaml.security.configurator import SecurityConfigurator

# Spustit webové UI
cfg = SecurityConfigurator()
cfg.serve()  # → http://127.0.0.1:8785

# Nebo programaticky
commands = cfg.generate_commands()
for cmd in commands:
    print(f"{cmd.title}: {cmd.command}")
```

## Webový průvodce

Průvodce vás provede 6 kroky:

1. **Detekce platformy** — automaticky rozpozná váš OS
2. **Pravidla firewallu** — nastavení portů a přístupových pravidel
3. **Výjimky antivirů** — vyloučení UAML adresářů ze skenování
4. **Šifrování** — nastavení BitLocker VHD (Windows)
5. **WSL2 nastavení** — konfigurace síťování WSL2 (Windows)
6. **Kontrola & Spuštění** — přehled všech příkazů, spuštění jedním kliknutím

Každý příkaz zobrazuje:
- Úroveň rizika (🟢 Nízké / 🟠 Střední / 🔴 Vysoké)
- Zda vyžaduje administrátorská oprávnění
- Potvrzovací dialog pro střední/vysoké riziko

## Spuštění jedním kliknutím

Příkazy se spustí přímo na vašem stroji tlačítkem ▶️ **Spustit**. Žádné kopírování, žádné stahování skriptů. Výsledky se zobrazí inline:
- ✅ Úspěch — s výstupem příkazu
- ❌ Chyba — s detaily chyby a návrhy řešení

## Expert Mode (Expert na vyžádání)

Dočasně povolte AI agentovi **kontrolovaný, auditovaný přístup** k hostitelskému OS.

### Jak to funguje

1. **Spusťte session** — zvolte úroveň přístupu (DIAGNOSTIC nebo REPAIR)
2. **Nastavte časový limit** — maximálně 60 minut
3. **AI spouští příkazy** — pouze whitelistované příkazy povoleny
4. **Kompletní audit trail** — každý příkaz zalogován s časem, výsledkem, úrovní rizika
5. **Kill switch** — ukončete session kdykoli

### Úrovně přístupu

| Úroveň | Povolené příkazy | Použití |
|---------|-----------------|---------|
| DIAGNOSTIC | `ls`, `cat`, `grep`, `systemctl status`, `ufw status`, `df`, `free`, `ps`, `netstat`, `ip`, `ping`, `dig` | Pouze čtení — inspekce systému |
| REPAIR | Vše z diagnostic + `ufw allow/deny`, `chmod`, `chown`, `systemctl start/stop/restart`, `tee /etc/` | Oprava konfiguračních problémů |

### Blokované příkazy (vždy)

Tyto příkazy jsou **vždy blokované**, bez ohledu na úroveň přístupu:
- `rm -rf /`, `mkfs`, `dd if=`, `format`
- `passwd`, `useradd`, `userdel`, `usermod`
- `shutdown`, `reboot`, `init 0`, `halt`
- `curl | bash`, `wget | bash`

### Bezpečnostní záruky

- **Časově omezené** — session automaticky expirují (max 60 minut)
- **Whitelist příkazů** — spustí se pouze předschválené příkazy
- **Schválení uživatelem** — každý příkaz vyžaduje callback schválení
- **Kill switch** — okamžité ukončení session
- **Kompletní audit trail** — exportovatelný jako HTML/JSON report

## Audit reporty

Každý spuštěný příkaz je zalogován. Generujte reporty pro:
- IT oddělení (audity)
- Vedení firmy (dokumentace)
- Compliance (ISO 27001, GDPR)
- Osobní záznamy

### Formáty reportů

- **HTML** — tisknutelný, profesionální layout se souhrnnými statistikami
- **JSON** — strojově čitelný pro integraci s dalšími nástroji

### Obsah reportu

| Pole | Popis |
|------|-------|
| Časové razítko | Kdy byl příkaz spuštěn |
| Název | Lidsky čitelný název akce |
| Příkaz | Přesný příkaz, který byl spuštěn |
| Úroveň rizika | 🟢 Nízké / 🟠 Střední / 🔴 Vysoké |
| Výsledek | Úspěch/selhání + návratový kód |
| Výstup | stdout/stderr příkazu (zkráceno na 5 KB) |
| Spustil | Vždy „user" (nebo „expert" pro Expert Mode) |
| Platforma | Detekovaný OS |

### Přístup k reportům

```
# Přes Web UI
Klikněte „📄 Otevřít HTML report" nebo „💾 Stáhnout report"

# Přes API
GET http://127.0.0.1:8785/api/report        → HTML report
GET http://127.0.0.1:8785/api/report.json    → JSON report
GET http://127.0.0.1:8785/api/history        → Surový log příkazů
```

## API endpointy

| Endpoint | Metoda | Popis |
|----------|--------|-------|
| `/` | GET | Webové UI |
| `/api/platform` | GET | Info o detekované platformě |
| `/api/generate` | GET | Vygenerované příkazy pro aktuální platformu |
| `/api/execute` | POST | Spuštění příkazu |
| `/api/history` | GET | Historie spuštěných příkazů |
| `/api/report` | GET | HTML audit report |
| `/api/report.json` | GET | JSON audit report |
| `/api/expert/start` | POST | Start Expert Mode session |
| `/api/expert/stop` | POST | Stop Expert Mode session |
| `/api/expert/execute` | POST | Spuštění příkazu v Expert Mode |
| `/api/expert/status` | GET | Stav aktuální Expert Mode session |
| `/api/expert/audit` | GET | Expert Mode audit trail |

## Architektura

```
┌─────────────────────────────────────────┐
│          Webový prohlížeč (localhost)     │
│  ┌─────────────────────────────────────┐ │
│  │    6kroký průvodce (tmavý motiv)    │ │
│  │  ┌──────┬──────┬──────┬──────────┐  │ │
│  │  │ FW   │ AV   │ Šifr │ Expert   │  │ │
│  │  └──────┴──────┴──────┴──────────┘  │ │
│  │     ▶️ Spustit  │  📄 Report        │ │
│  └─────────────────────────────────────┘ │
└──────────────────┬──────────────────────┘
                   │ HTTP (127.0.0.1:8785)
┌──────────────────┴──────────────────────┐
│         SecurityConfigurator             │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Generátor  │  │   ExpertMode      │  │
│  │ příkazů    │  │  ┌─────────────┐  │  │
│  │            │  │  │ Whitelist   │  │  │
│  │ Detekce    │  │  │ Blacklist   │  │  │
│  │ platformy  │  │  │ Kill Switch │  │  │
│  └────────────┘  │  │ Audit Trail │  │  │
│                  │  └─────────────┘  │  │
│  ┌────────────┐  └───────────────────┘  │
│  │ Logger     │                         │
│  │ exekucí    │  → HTML/JSON Reporty    │
│  └────────────┘                         │
└──────────────────────────────────────────┘
                   │
        subprocess.run() (lokální OS)
```

## USP (Unique Selling Point)

> **Od nastavení firewallu po kvantové šifrování — jeden produkt pro celý bezpečnostní životní cyklus AI agenta.**

Na rozdíl od tradičních bezpečnostních nástrojů, které nabízejí přístup „vše nebo nic", UAML poskytuje:
- **Kontrolovaná transparentnost** — každá akce viditelná, logovaná, exportovatelná
- **Stupňovaný přístup** — diagnostická vs. opravná úroveň
- **Časově omezené session** — žádný trvalý zvýšený přístup
- **Člověk v rozhodovací smyčce** — schválení vyžadováno pro každou akci

## Požadavky

- Python 3.10+
- Žádné externí závislosti (používá `http.server` ze stdlib)
- Admin/root oprávnění pro některé operace (označeno v UI)

---

*© 2026 GLG, a.s. — UAML Security Configurator v1.0*
