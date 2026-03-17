# UAML License Server — API Reference

**Verze:** 1.0  
**Base URL:** `https://license.uaml.ai`  
**© 2026 GLG, a.s. Všechna práva vyhrazena.**

---

## Přehled

UAML License Server spravuje validaci licencí, aktivaci zařízení, změny subscription tier a platební webhooky. Běží na testovacím serveru (`161.97.184.185`) na portu 8776, za nginx s SSL.

---

## Endpointy

### POST /v1/validate

Validace licenčního klíče a získání informací o tier.

**Request:**
```json
{"license_key": "UAML-P-A1B2C3D4-E5F6G7H8-I9J0K1L2"}
```

**Response:**
```json
{
  "valid": true,
  "tier": "professional",
  "organization": "Acme Corp",
  "max_agents": 10,
  "features": ["core", "cli", "python_api", "focus_engine", "security_configurator"],
  "expires_at": "2027-03-15T00:00:00+00:00",
  "expired": false
}
```

---

### POST /v1/activate

Aktivace licence na konkrétním zařízení. Počítá se proti aktivačnímu limitu daného tier.

**Request:**
```json
{
  "license_key": "UAML-P-A1B2C3D4-E5F6G7H8-I9J0K1L2",
  "device_id": "sha256-hostname-hash",
  "os": "Linux 6.6",
  "version": "1.0.0"
}
```

**Response (úspěch):**
```json
{"activated": true, "tier": "professional"}
```

**Response (dosažen limit):**
```json
{"activated": false, "error": "max activations reached (10)"}
```

Opakovaná aktivace na stejném zařízení nespotřebuje další slot.

---

### POST /v1/deactivate

Odebrání aktivace zařízení, uvolnění slotu.

**Request:**
```json
{
  "license_key": "UAML-P-A1B2C3D4-E5F6G7H8-I9J0K1L2",
  "device_id": "sha256-hostname-hash"
}
```

**Response:**
```json
{"deactivated": true, "remaining_activations": 7}
```

---

### GET /v1/status?key=UAML-P-...

Kontrola stavu předplatného pro daný licenční klíč.

**Response:**
```json
{
  "found": true,
  "tier": "professional",
  "active": true,
  "expires_at": "2027-03-15T00:00:00+00:00",
  "organization": "Acme Corp",
  "activations": 3,
  "max_agents": 10
}
```

---

### POST /v1/change-plan

Upgrade nebo downgrade subscription tier. Zaznamenává změnu v audit historii.

**Request:**
```json
{
  "license_key": "UAML-P-A1B2C3D4-E5F6G7H8-I9J0K1L2",
  "new_tier": "team",
  "reason": "user request",
  "changed_by": "portal",
  "payment_id": "comgate-txn-123"
}
```

**Response:**
```json
{
  "changed": true,
  "direction": "upgrade",
  "old_tier": "professional",
  "new_tier": "team",
  "max_agents": 50,
  "features": ["core", "cli", "python_api", "compliance", "gdpr", "focus_engine", "security_configurator", "expert_on_demand", "federation", "neo4j", "rbac", "approval_gates"],
  "warning": null
}
```

**Upozornění při downgrade** (pokud aktivní zařízení překračují nový limit):
```json
{"warning": "Active devices (8) exceed new limit (3). Deactivate excess devices."}
```

---

### POST /v1/plan-history

Získání audit trailu všech změn plánu pro daný licenční klíč.

**Request:**
```json
{"license_key": "UAML-P-A1B2C3D4-E5F6G7H8-I9J0K1L2"}
```

**Response:**
```json
{
  "license_key": "UAML-P-...",
  "changes": [
    {
      "changed_at": "2026-03-15T14:52:00+00:00",
      "old_tier": "professional",
      "new_tier": "team",
      "old_max_agents": 10,
      "new_max_agents": 50,
      "reason": "user request",
      "changed_by": "portal"
    }
  ]
}
```

---

### POST /v1/webhook

Příjem platebních notifikací z ComGate.

**Request:** Raw ComGate webhook payload  
**Response:** `{"status": "received"}`

---

## Definice tier

| Tier | Cena (€/měs.) | Max agentů | Klíčové funkce |
|------|---------------|------------|----------------|
| Community | Zdarma | 1 | Core, CLI, Python API |
| Starter | 8 € | 3 | + Compliance, GDPR toolkit |
| Professional | 29 € | 10 | + Focus Engine, Security Configurator, Expert on Demand, Federation |
| Team | 190 € | 50 | + Neo4j, RBAC, Approval gates |
| Enterprise | Individuální | Neomezeno | Všechny funkce |

## Formát licenčního klíče

```
UAML-{T}-{XXXXXXXX}-{XXXXXXXX}-{XXXXXXXX}
```

Kde `{T}` = C (Community), S (Starter), P (Professional), T (Team), E (Enterprise).

## Databázové schéma

### Tabulky

- **licenses** — licenční klíče, tier, organizace, expirace
- **activations** — registrace zařízení pro daný licenční klíč
- **plan_changes** — audit trail všech změn tier (kdo, kdy, co, proč)
- **payments** — platební záznamy z ComGate

## Integrace s klientem

```python
# V UAML CLI:
uaml license activate UAML-P-XXXX-YYYY-ZZZZ
uaml license deactivate
uaml license status
uaml license upgrade --tier team
```

## Upgrade / Downgrade — Fakturační logika

### Upgrade flow

1. Zákazník požádá o upgrade přes portál
2. Server spočítá **poměrný kredit** za zbývající dny na aktuálním tarifu
3. Server spočítá **poměrnou cenu** za zbývající dny na novém tarifu
4. **Rozdíl = částka k doplacení** → odeslán jako platební požadavek na ComGate
5. ComGate webhook potvrdí platbu → plán upgradován okamžitě
6. Datum příští platby zůstává stejné, ale za vyšší tarif

**Příklad:**
- Professional (€29/měs), zaplaceno 1.3., upgrade na Team (€190/měs) 15.3.
- Zbývá: 16 dní = kredit €15.47
- Nový tarif poměrně: 16 dní z €190 = €98.06
- **Doplatek: €98.06 - €15.47 = €82.59** → platba přes ComGate
- Příští platba: 1.4. za €190/měs

### Downgrade flow

1. Zákazník požádá o downgrade přes portál
2. Plán se změní **okamžitě** (nebo na konci období — konfigurovatelné)
3. Přeplatek se vypočítá jako **kredit** na další fakturační cyklus
4. **Žádná platba přes bránu** — pouze přepočet dalšího data platby
5. Kredit prodlouží datum příští platby nebo sníží její výši

**Příklad:**
- Team (€190/měs), zaplaceno 1.3., downgrade na Professional (€29/měs) 15.3.
- Zbývající kredit: 16 dní z €190 = €98.06
- Denní cena nového tarifu: €29/30 = €0.97/den
- **Kredit pokryje ~101 dní** → příští platba posunuta na ~24.6.
- Nebo: příští platba 1.4. se sníženou částkou

### Klíčová pravidla

- Platební požadavky vždy iniciuje **náš server**, ne brána
- ComGate řeší pouze výběr platby
- Veškeré poměrné výpočty probíhají na straně serveru
- Tabulka `plan_changes` loguje každou změnu s částkami a důvody

---

## Offline chování

- Licence je lokálně cachovaná v `~/.uaml/license.json`
- Grace period: 7 dní bez kontaktu se serverem
- Po uplynutí grace period: degradace na funkce Community tier
- Automatická revalidace při příštím připojení k internetu
