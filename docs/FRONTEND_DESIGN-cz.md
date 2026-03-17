# UAML Dashboard — Dokument návrhu frontendu

**Verze:** 1.0  
**Datum:** 2026-03-08  
**Autoři:** Pepa2 (Nastavení, Úkoly, Compliance, Export) + Cyril (Dashboard, Knowledge, Graf, Časová osa)

## Architektura

```
┌─────────────────────────────────────────────────────────┐
│                    UAML Dashboard                        │
│  ┌──────────┐  ┌──────────────────────────────────────┐ │
│  │ Sidebar  │  │           Obsahová oblast             │ │
│  │          │  │                                       │ │
│  │ 🏠 Home  │  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐   │ │
│  │ 🧠 Know  │  │  │Karta│ │Karta│ │Karta│ │Karta│   │ │
│  │ ✅ Tasks │  │  └─────┘ └─────┘ └─────┘ └─────┘   │ │
│  │ 🔗 Graph │  │                                       │ │
│  │ 📊 Time  │  │  ┌─────────────────────────────────┐ │ │
│  │ 🔐 Audit │  │  │     Hlavní blok obsahu          │ │ │
│  │ 📦 Export│  │  │                                  │ │ │
│  │ ⚙️ Set   │  │  └─────────────────────────────────┘ │ │
│  └──────────┘  └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Stránky

### 1. 🏠 Dashboard (Domovská stránka)
- **Souhrnné karty**: Počet znalostí, statistiky úkolů, skóre compliance, počty uzlů/relací Neo4j
- **Nedávná aktivita**: Posledních 10 znalostních záznamů + změny úkolů
- **Rychlé akce**: Nová znalost, nový úkol, spustit zálohu, export
- **Zdraví systému**: Stav API, velikost DB, čas poslední zálohy
- **Odkazy**: Rychlá navigace do všech sekcí

### 2. 🧠 Prohlížeč znalostí
- **Vyhledávací lišta** s fulltextovým vyhledáváním
- **Filtry**: Vrstva (identity/knowledge/team/operational/project), téma, projekt, klient, spolehlivost
- **Výsledky**: Mřížka karet nebo tabulkový pohled (přepínatelné)
- **Panel detailu**: Celý záznam s metadaty, relacemi, zdrojovými odkazy, úpravou/smazáním
- **Vytvoření**: Modální okno pro přidání nových znalostních záznamů

### 3. ✅ Úkoly (Kanban)
- **Kanban se 3 sloupci**: Čekající → Probíhající → Hotovo
- **Přetahování** mezi sloupci
- **Filtry**: Projekt, přiřazený agent, priorita, klient
- **Karta úkolu**: Název, stav, přiřazení, datum splnění, odznak projektu
- **Rychlé vytvoření**: Inline vytváření úkolů
- **Hromadné operace**: Výběr více položek → přesun/smazání/export

### 4. 🔗 Průzkumník grafu
- **Vizualizace Neo4j** přes neovis.js
- **Vyhledávání entit**: Najít uzel podle jména/typu
- **Interaktivní**: Klik na uzel → zobrazit detail + sousedy
- **Filtry**: Typ uzlu, typ relace, hloubka
- **Rozvržení**: Silově řízené, hierarchické nebo radiální

### 5. 📊 Časová osa
- **Chronologický přehled**: Všechny události (znalosti, úkoly, audit) na jedné časové ose
- **Filtry**: Typ události, časový rozsah, projekt, agent
- **Přiblížení**: Pohled den / týden / měsíc
- **Barevné kódování**: Zelená=znalosti, Modrá=úkoly, Červená=audit, Šedá=systém

### 6. 🔐 Compliance a audit
- **Skóre compliance**: Celkové + dle kategorie (GDPR, ISO 27001)
- **Tabulka nálezů**: Problém, závažnost, doporučení, stav
- **Auditní protokol**: Kdo co kdy udělal (filtrovatelné)
- **Zprávy**: Generovat PDF/JSON zprávu o souladu
- **Uchovávání dat**: Expirované záznamy, stav zásad uchovávání

### 7. 📦 Export / Import
- **Průvodce exportem**: Výběr typu dat → filtry → formát (JSON/CSV/SQLite)
- **Import**: Nahrát JSON/CSV → náhled → potvrdit
- **Správa záloh**: Seznam záloh, vytvoření nové, obnova, plánování
- **PQC šifrování**: Přepínač šifrování exportů, správa klíčů

### 8. ⚙️ Nastavení
- **Konfigurace API**: Host, port, ověřování
- **Správa agentů**: Registrovaní agenti, klíče
- **Databáze**: Cesta k DB, velikost, vakuum, kontrola integrity
- **Téma**: Tmavé / Světlé / Automatické
- **O aplikaci**: Verze, licence, odkazy

## Designový systém

### Barvy (Tmavé téma — primární)
- Pozadí: `#0f1117` (hluboká tma)
- Povrch: `#1a1d27` (karty, panely)
- Povrch při najetí: `#252836`
- Ohraničení: `#2d3148`
- Primární: `#6366f1` (indigo)
- Primární při najetí: `#818cf8`
- Úspěch: `#22c55e`
- Varování: `#f59e0b`
- Nebezpečí: `#ef4444`
- Text: `#e2e8f0`
- Text tlumený: `#94a3b8`

### Typografie
- Písmo: `Inter, -apple-system, sans-serif`
- Nadpisy: tloušťka 600
- Tělo textu: tloušťka 400
- Monospace: `JetBrains Mono, monospace`

### Komponenty
- Karty s jemným ohraničením + stínem
- Zaoblené rohy (8px karty, 6px tlačítka, 4px vstupy)
- Postranní panel: Pevný, šířka 240px, sbalitelný na 60px (pouze ikony)
- Modální okna pro formuláře vytvoření/úpravy
- Toast notifikace pro akce
- Načítací skeletony

### Responzivita
- Desktop: Postranní panel + plný obsah
- Tablet: Sbalený postranní panel + plný obsah
- Mobil: Spodní navigace + skládané karty

## Struktura souborů

```
frontend/
├── index.html          # Shell + router
├── css/
│   ├── variables.css   # Designové tokeny
│   ├── layout.css      # Mřížka, postranní panel, obsah
│   ├── components.css  # Karty, tlačítka, modály, formuláře
│   └── pages.css       # Styly specifické pro stránky
├── js/
│   ├── app.js          # Router + inicializace
│   ├── api.js          # REST API klient
│   ├── components.js   # Sdílené UI komponenty
│   ├── pages/
│   │   ├── dashboard.js
│   │   ├── knowledge.js
│   │   ├── tasks.js
│   │   ├── graph.js
│   │   ├── timeline.js
│   │   ├── compliance.js
│   │   ├── export.js
│   │   └── settings.js
│   └── utils.js        # Pomocné funkce, formátovače
└── assets/
    └── logo.svg
```

## Závislosti na API

Všechny stránky využívají endpointy `/api/v1/*` z `uaml.api.server`.
Frontend je servírován jako statické soubory stejným serverem (nebo odděleně).

## Rozdělení implementace

| Stránka | Vlastník | Priorita |
|---------|----------|----------|
| Rozvržení + Router | Pepa2 (kostra) | P0 |
| Domovský dashboard | Cyril | P0 |
| Knowledge | Cyril | P0 |
| Kanban úkolů | Pepa2 | P0 |
| Graf | Cyril | P1 |
| Časová osa | Cyril | P1 |
| Compliance | Pepa2 | P1 |
| Export/Import | Pepa2 | P1 |
| Nastavení | Pepa2 | P2 |

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.
