# UAML — Reference GDPR Compliance

> Reference pro modul `uaml.compliance`. Pokrývá správu souhlasů, generování DPIA, inventář dat, evidenci porušení a automatizovaný audit.

---

## Správa souhlasů (`compliance.consent`)

**Modul:** `uaml/compliance/consent.py`
**Článek GDPR:** Čl. 7 — Podmínky souhlasu

### ConsentManager

Spravuje záznamy o souhlasech v dedikované SQLite tabulce `consents`. Každé udělení/odvolání je automaticky auditováno přes `MemoryStore.learn()`.

**Konstruktor:**
```python
from uaml.compliance.consent import ConsentManager
cm = ConsentManager(store)
```

**Schéma tabulky (vytvořeno automaticky):**
| Sloupec | Typ | Popis |
|---------|-----|-------|
| `client_ref` | TEXT | Identifikátor subjektu údajů |
| `purpose` | TEXT | Účel zpracování (např. `"knowledge_storage"`) |
| `granted_at` | TEXT | ISO časové razítko udělení |
| `revoked_at` | TEXT | ISO časové razítko odvolání (NULL = aktivní) |
| `granted_by` | TEXT | Kdo souhlas udělil |
| `scope` | TEXT | Detaily rozsahu |
| `evidence` | TEXT | Odkaz na dokument/email se souhlasem |

**Klíčové metody:**

- `grant(client_ref, purpose, *, granted_by, scope="", evidence="") → int` — Zaznamenat udělení souhlasu. Vrací ID záznamu.
- `revoke(client_ref, purpose) → int` — Odvolat aktivní souhlas. Vrací počet odvolaných.
- `check(client_ref, purpose) → bool` — Ověřit, zda existuje aktivní souhlas.
- `list_consents(client_ref=None, *, include_revoked=False) → list[dict]` — Seznam záznamů s volitelnými filtry.
- `consent_summary(client_ref) → dict` — Přehled s počty aktivních/odvolaných a detaily.

**Příklad:**
```python
cm = ConsentManager(store)
cm.grant("client-42", purpose="knowledge_storage", granted_by="client-42")
cm.check("client-42", purpose="knowledge_storage")  # True
cm.revoke("client-42", purpose="knowledge_storage")
cm.check("client-42", purpose="knowledge_storage")  # False
```

---

## DPIA a oznámení porušení (`compliance.dpia`)

**Modul:** `uaml/compliance/dpia.py`
**Články GDPR:** Čl. 35 (DPIA), Čl. 33/34 (Oznámení porušení)

### DPIAGenerator

Generuje posouzení vlivu na ochranu osobních údajů analýzou skutečně uložených dat.

```python
from uaml.compliance.dpia import DPIAGenerator
dpia = DPIAGenerator(store)
assessment = dpia.generate()
```

**`generate() → dict`** vrací strukturované DPIA s:
- `system_description` — název systému, účel, správce dat, právní základ zpracování
- `data_inventory` — celkový počet záznamů, záznamy podle vrstev, pokrytí právním základem
- `risk_assessment` — seznam rizik s úrovní (low/medium/high) a odkazy na články GDPR
- `mitigations` — existující kontroly (PQC šifrování, audit trail, etický pipeline, 5vrstvá klasifikace)
- `overall_risk` — agregovaná úroveň rizika
- `recommendation` — doporučení podle úrovně rizika

**Kontrolovaná rizika:**
| Riziko | Článek GDPR | Spouštěč |
|--------|-------------|----------|
| Uložena identitní data | Čl. 5(1)(c) | záznamy ve vrstvě identity > 0 |
| Klientská data bez právního základu | Čl. 6(1) | pokrytí právním základem < 100 % |
| Velký objem dat | Čl. 5(1)(e) | celkový počet záznamů > 10 000 |

### BreachRegister

Spravuje záznamy o porušení s trackingem 72hodinové lhůty pro oznámení DPA.

```python
from uaml.compliance.dpia import BreachRegister
register = BreachRegister(store)
breach_id = register.record_breach(description="Neoprávněný přístup", severity="high")
```

**Klíčové metody:**
- `record_breach(description, *, severity="medium", ...) → int` — Zaznamenat porušení. Automaticky auditováno.
- `update_breach(breach_id, *, measures_taken, dpa_notified, subjects_notified, status) → bool` — Aktualizovat opatření.
- `list_breaches(*, status=None) → list[dict]` — Seznam porušení.
- `breach_status(breach_id) → dict` — Stav včetně `hours_elapsed`, `deadline_72h` (bool), `dpa_notification_required`.

---

## Inventář dat (`compliance.inventory`)

**Modul:** `uaml/compliance/inventory.py`
**Článek GDPR:** Čl. 30 — Záznamy o činnostech zpracování

### ProcessingActivity (dataclass)

Pole: `id`, `name`, `purpose`, `legal_basis`, `data_categories` (list), `retention_days`, `recipients` (list), `transfers_outside_eu` (bool), `registered_at`.

### DataInventory

Udržuje registr zpracovatelských činností v tabulce `data_inventory`.

```python
from uaml.compliance.inventory import DataInventory
inv = DataInventory(store)
inv.register_activity("knowledge_storage", purpose="AI paměť",
                      legal_basis="legitimate_interest", retention_days=365)
```

**Klíčové metody:**
- `register_activity(name, purpose, legal_basis, *, data_categories, retention_days=365, recipients, transfers_outside_eu=False) → int` — Registrovat/aktualizovat činnost.
- `list_activities() → list[ProcessingActivity]` — Všechny registrované činnosti.
- `remove_activity(name) → bool` — Odebrat podle názvu.
- `generate_report() → dict` — Zpráva o souladu s Čl. 30 s celkovými počty a přehledem právních základů.
- `check_compliance() → list[str]` — Seznam problémů s dodržováním předpisů.

---

## Auditor souladu (`compliance.auditor`)

**Modul:** `uaml/compliance/auditor.py`
**Standardy:** GDPR, ISO 27001, Interní politiky

### Datové modely

**`Severity`** enum: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`

**`ComplianceStandard`** enum: `GDPR`, `ISO27001`, `INTERNAL`

**`Finding`** dataclass — jednotlivý nález s `check_id`, `title`, `description`, `severity`, `standard`, `article`, `control`, `passed`, `details`, `recommendation`.

**`AuditReport`** dataclass — kompletní zpráva s `findings`, `summary` a vlastnostmi: `passed`, `failed`, `critical_findings`, `score` (0–100).

### ComplianceAuditor

Spouští automatizované kontroly napříč všemi standardy.

```python
from uaml.compliance import ComplianceAuditor
auditor = ComplianceAuditor(store)
report = auditor.full_audit()
print(f"Skóre: {report.score}/100, Kritické: {len(report.critical_findings)}")
```

**Metody auditu:**
- `full_audit() → AuditReport` — Všechny kontroly (GDPR + ISO 27001 + Interní).
- `gdpr_check() → AuditReport` — Pouze GDPR kontroly.
- `retention_check(max_age_days=365) → AuditReport` — Kontrola omezení uložení.
- `access_report(subject_ref, *, include_audit=True) → dict` — GDPR Čl. 15 zpráva o přístupu subjektu.
- `erasure_report(subject_ref) → dict` — Čl. 17 náhled výmazu.
- `execute_erasure(subject_ref) → dict` — **DESTRUKTIVNÍ** — Čl. 17 provedení výmazu.

**Prováděné kontroly:**

| ID kontroly | Standard | Článek/Kontrola | Co kontroluje |
|-------------|----------|-----------------|---------------|
| GDPR-001 | GDPR | Čl. 6(1) | Právní základ pro klientská data |
| GDPR-002 | GDPR | Čl. 5(1)(b) | Omezení účelu (pokrytí topic/project) |
| GDPR-003 | GDPR | Čl. 5(1)(c) | Minimalizace dat (duplikáty) |
| GDPR-004 | GDPR | Čl. 5(1)(e) | Omezení uložení (staré záznamy) |
| GDPR-005 | GDPR | Čl. 7 | Sledování souhlasů klientů |
| GDPR-006 | GDPR | Čl. 15 | Schopnost zpracovat žádost o přístup |
| GDPR-007 | GDPR | Čl. 25 | Ochrana dat od návrhu (etický pipeline) |
| ISO-001 | ISO 27001 | A.8.15 | Úplnost audit trailu |
| ISO-002 | ISO 27001 | A.8.3 | Distribuce datových vrstev |
| ISO-003 | ISO 27001 | A.8.2 | Klasifikace úrovní přístupu |
| ISO-004 | ISO 27001 | A.8.13 | Operace zálohování |
| ISO-005 | ISO 27001 | A.8.24 | Dostupnost PQC šifrování |
| INT-001 | Interní | — | Izolace klientských dat |
| INT-002 | Interní | — | Aktivita etického pipeline |
| INT-003 | Interní | — | Integrita content hash |

**Zpráva o přístupu subjektu** (`access_report`) vrací:
- Všechny znalostní záznamy pro daný subjekt
- Záznamy úkolů (pokud existuje tabulka tasks)
- Zmínky v audit trailu
- Účely zpracování
- Informace o retenci (nejstarší/nejnovější záznam)
- Připomínka práv subjektu údajů (Čl. 16–21)

---

## Pokryté články GDPR

| Článek | Pokrytí |
|--------|---------|
| Čl. 5 | Omezení účelu, minimalizace dat, omezení uložení, odpovědnost |
| Čl. 6 | Zákonnost — sledování právního základu |
| Čl. 7 | Správa souhlasů (udělení, odvolání, ověření) |
| Čl. 15 | Právo na přístup (zpráva o přístupu subjektu) |
| Čl. 17 | Právo na výmaz (náhled + provedení) |
| Čl. 25 | Ochrana dat od návrhu (kontrola etického pipeline) |
| Čl. 30 | Záznamy o činnostech zpracování (DataInventory) |
| Čl. 32 | Zabezpečení zpracování (PQC šifrování) |
| Čl. 33/34 | Oznámení porušení (BreachRegister s 72h sledováním) |
| Čl. 35 | Generování DPIA |

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

