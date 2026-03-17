# Průvodce certifikací UAML — Focus Engine a ochrana dat

**Verze:** 1.0  
**Datum:** 2026-03-14  
**Klasifikace:** Kat. A — Audit/Architektura  

© 2026 GLG, a.s.

---

## 1. Rozsah

Tento dokument pokrývá certifikovatelné aspekty UAML Focus Engine:
- Filtrování a klasifikace vstupních dat
- Filtrování výstupních dat a výběr kontextu
- Správa token budgetu
- Audit trail a logování změn
- Izolace agenta od konfigurace pravidel
- Detekce PII a vynucení kategorie dat

---

## 2. Přehled architektury

```
Datové zdroje → [Vstupní filtr] → Neo4j/Úložiště → [Focus Engine] → Kontext agenta
                      ↑                                    ↑
               Konfigurováno člověkem              Konfigurováno člověkem
               (pouze Web UI)                      (pouze Web UI)
                      ↓                                    ↓
               AI Agent: BEZ PŘÍSTUPU             AI Agent: BEZ PŘÍSTUPU
               ke konfiguraci                     ke konfiguraci
```

**Klíčový princip:** AI agenti operují POD pravidly, ne nad nimi.

---

## 3. Certifikačně relevantní parametry

Tyto parametry přímo ovlivňují ochranu dat, řízení přístupu a soulad s předpisy.
V systému označeny 🔒.

### 3.1 Vstupní filtr

| Parametr | Typ | Výchozí | Rozsah | Dopad na certifikaci |
|----------|-----|---------|--------|---------------------|
| `min_relevance_score` | float | 0,7 | 0,0–1,0 | Řídí práh kvality dat |
| `ttl_days` | int | 730 | 30–100000 | GDPR čl. 5(1)(e) — omezení ukládání |
| `require_classification` | bool | true | — | Zajišťuje kategorizaci všech dat |
| `pii_detection` | bool | true | — | GDPR čl. 25 — ochrana dat od návrhu |

### 3.2 Výstupní filtr

| Parametr | Typ | Výchozí | Rozsah | Dopad na certifikaci |
|----------|-----|---------|--------|---------------------|
| `token_budget_per_query` | int | 2000 | 200–32000 | Řídí objem exponovaných dat |
| `recall_tier` | int | 1 | 1–3 | Řídí granularitu dat v kontextu |
| `sensitivity_threshold` | int | 3 | 1–5 | Řídí přístup k citlivým datům |
| `max_context_percentage` | int | 30 | 5–80 | Omezuje expozici dat na požadavek |

### 3.3 Pravidla agenta

| Parametr | Typ | Výchozí | Dopad na certifikaci |
|----------|-----|---------|---------------------|
| `report_token_usage` | bool | true | Auditovatelnost přístupu k datům |
| `never_expose_rules` | bool | true | Důvěrnost konfigurace |
| `never_bypass_filter` | bool | true | Záruka integrity filtru |
| `log_all_recalls` | bool | true | Kompletní audit trail |

### 3.4 Programový přístup

```python
from uaml.core.focus_config import FocusEngineConfig

config = FocusEngineConfig()
cert_params = config.certification_params()
# Vrátí dict všech certifikačně relevantních parametrů s aktuálními hodnotami
```

CLI:
```bash
uaml focus params --cert-only
```

---

## 4. Matice řízení přístupu

| Aktér | Konfig vstupního filtru | Konfig výstupního filtru | Log změn pravidel | Pravidla agenta |
|-------|------------------------|--------------------------|-------------------|-----------------|
| Lidský vlastník | Čtení/Zápis | Čtení/Zápis | Čtení | Čtení/Zápis |
| Lidský admin | Čtení/Zápis | Čtení/Zápis | Čtení | Čtení |
| AI Agent | **BEZ PŘÍSTUPU** | **BEZ PŘÍSTUPU** | **BEZ PŘÍSTUPU** | **Pouze čtení** |
| Systém (UAML) | Aplikovat pravidla | Aplikovat pravidla | Zápis (auto) | Aplikovat pravidla |

### 4.1 Vynucení

- API endpointy pro změny konfigurace vyžadují lidské autentizační tokeny
- Tokeny agentů jsou odmítnuty na vrstvě API pro konfigurační endpointy
- MCP nástroj `memory_focus_recall` může pouze ČÍST výsledky, ne upravovat pravidla
- CLI příkazy vyžadují přístup k lokálnímu systému (žádné vzdálené spuštění agentem)

---

## 5. Audit trail

### 5.1 Log změn pravidel

Každá změna konfigurace je zaznamenána v `rules_changelog.db`:

| Pole | Popis |
|------|-------|
| `change_id` | Jedinečný identifikátor (RC-{uuid}) |
| `timestamp` | Časové razítko ISO-8601 UTC |
| `user` | Ověřený uživatel, který provedl změnu |
| `rule_path` | Kompletní cesta parametru (např. `output_filter.token_budget_per_query`) |
| `old_value` | Předchozí hodnota |
| `new_value` | Nová hodnota |
| `reason` | Odůvodnění poskytnuté uživatelem |
| `expected_impact` | Hypotéza uživatele o dopadu změny |
| `actual_impact` | Měřený dopad po hodnoticím období |

### 5.2 Audit recall

Každá operace `focus_recall` je zaznamenána v tabulce `audit_log` UAML:

```
action: focus_recall
details: budget=2000|used=1450|selected=5|rejected=3|tier=1|query=...
```

### 5.3 Audit rozhodnutí

Každé rozhodnutí recall (zahrnout/vyloučit) je vráceno s důvodem:

```json
{
  "entry_id": 42,
  "included": false,
  "reason": "Sensitivity 5 > threshold 3",
  "final_score": 0.0,
  "tokens_used": 0
}
```

---

## 6. Kategorie dat a mapování na GDPR

| Kategorie | Článek GDPR | Výchozí akce | Zdůvodnění |
|-----------|------------|--------------|------------|
| Osobní data | Čl. 6 (zákonný základ) | Vyžadovat souhlas | Zpracování vyžaduje právní základ |
| Finanční data | Čl. 6 + Čl. 32 | Šifrovat | Bezpečnost zpracování |
| Zdravotní data | Čl. 9 (zvláštní kategorie) | Odmítnout | Vyžaduje výslovný souhlas + dodatečné záruky |
| Firemní data | Čl. 6 | Povolit | Oprávněný zájem |
| Veřejná data | Čl. 6(1)(f) | Povolit | Veřejně dostupné |
| Komunikace | Čl. 6 + ePrivacy | Šifrovat | Důvěrnost komunikace |

### 6.1 Detekce PII

Vestavěné vzory PII:
- Emailové adresy
- Telefonní čísla (mezinárodní + český formát)
- Česká rodná čísla
- Čísla kreditních karet
- Čísla IBAN
- IP adresy
- Česká IČO / DIČ

Auto-detekce označuje záznamy s `pii_detected=true` a úrovní `sensitivity`.

---

## 7. Token budget a transparentnost nákladů

### 7.1 Tabulka dopadu tokenů

| Změna nastavení | Dopad tokenů | Dopad na náklady | Dopad na kvalitu |
|----------------|-------------|-----------------|-----------------|
| Budget 500→2000 | +1500 tok/dotaz | +€0,03/dotaz | +40 % přesnosti |
| Budget 2000→4000 | +2000 tok/dotaz | +€0,04/dotaz | +20 % přesnosti |
| Relevance 0,3→0,5 | -800 tok/dotaz | -€0,02/dotaz | -10 % pokrytí |
| Tier 1→3 | +3000 tok/dotaz | +€0,06/dotaz | +25 % detailů |

### 7.2 Zpráva o využití tokenů

Každý recall vrátí `TokenUsageReport`:

```json
{
  "budget": 2000,
  "used": 1450,
  "remaining": 550,
  "records_selected": 5,
  "records_rejected": 3,
  "avg_tokens_per_record": 290.0,
  "estimated_cost_usd": 0.00435,
  "recall_tier": 1
}
```

---

## 8. Výchozí přednastavení

| Přednastavení | Budget | Min. relevance | Tier | Max. záznamů | Případ použití |
|--------------|--------|----------------|------|-------------|----------------|
| Konzervativní | 1500 | 0,5 | 1 (souhrny) | 5 | Privacy-first, minimální expozice |
| Standardní | 3000 | 0,3 | 2 (detaily) | 10 | Vyvážená kvalita/náklady |
| Výzkumné | 8000 | 0,2 | 3 (raw) | 25 | Maximální kontext, výzkum |

---

## 9. Chování při zmrazení (po zkušební době)

Po vypršení zkušební doby:
1. Vlastní pravidla **zůstávají aktivní** — ochrana dat pokračuje
2. Pravidla nelze upravovat, přidávat ani odebírat
3. Dashboard zobrazuje zobrazení jen pro čtení
4. Vynuceno výchozí přednastavení
5. Žádná data nejsou ohrožena — zmrazení je licenční omezení, ne bezpečnostní mezera

---

## 10. Kontrolní seznam souladu

| # | Požadavek | Implementace | Stav |
|---|-----------|--------------|------|
| 1 | Klasifikace dat | Systém kategorií s mapováním na GDPR | ✅ |
| 2 | Detekce PII | Automatická detekce Regex/NER | ✅ |
| 3 | Řízení přístupu | Konfigurace pouze pro lidi, izolace agentů | ✅ |
| 4 | Audit trail | Log změn pravidel + audit recall | ✅ |
| 5 | Transparentnost tokenů | Reportování budgetu v reálném čase | ✅ |
| 6 | Minimalizace dat | Konfigurovatelné prahy relevance | ✅ |
| 7 | Omezení ukládání | TTL s konfigurovatelnou retencí | ✅ |
| 8 | Právo na výmaz | Delete API s audit logem | ✅ |
| 9 | Přenositelnost dat | Export (JSON/YAML) | ✅ |
| 10 | Rollback konfigurace | Log změn pravidel s rollbackem | ✅ |

---

## 11. Referenční příručka API

### Endpointy Focus Engine

| Metoda | Cesta | Popis |
|--------|-------|-------|
| `GET` | `/api/v1/focus-config` | Aktuální konfigurace |
| `PUT` | `/api/v1/focus-config` | Aktualizovat konfiguraci (pouze lidé) |
| `GET` | `/api/v1/focus-config/presets` | Seznam dostupných přednastavení |
| `GET` | `/api/v1/focus-config/params` | Specifikace parametrů |
| `POST` | `/api/v1/focus-recall` | Inteligentní recall |
| `GET` | `/api/v1/rules-log` | Historie změn pravidel |
| `GET` | `/api/v1/rules-log/stats` | Statistiky změn |

### MCP nástroje

| Nástroj | Popis |
|---------|-------|
| `memory_focus_recall` | Inteligentní recall s přednastavením/budgetem |

### CLI příkazy

| Příkaz | Popis |
|--------|-------|
| `uaml focus recall "dotaz"` | Recall s token reportem |
| `uaml focus config` | Zobrazit/uložit konfiguraci |
| `uaml focus params --cert-only` | Certifikační parametry |

---

*Dokument vygenerován: 2026-03-14*  
*Příští přezkum: Před vydáním v1.0*
