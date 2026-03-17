# UAML — Reference licenčního systému

> © 2026 GLG, a.s. | UAML v1.0 | Stav: NÁVRH

## Přehled

Licenční systém zajišťuje generování klíčů, validaci, správu zkušebních verzí a řízení přístupu k funkcím. Nachází se v `uaml/licensing.py`, `uaml/feature_gate.py`.

## Licenční úrovně

| Úroveň | Funkce | Cena |
|--------|--------|------|
| `community` | Základní paměť, lokální úložiště | Zdarma |
| `starter` | + Focus Engine, základní přednastavení | 8 €/měs. |
| `professional` | + Plný Focus Engine, MCP, export/import | 29 €/měs. |
| `team` | + Federace, více uživatelů, RBAC | 190 €/měs. |
| `enterprise` | + Vlastní SLA, PQC šifrování, on-prem | Na vyžádání |

Roční fakturace: 10× měsíční cena (2 měsíce zdarma).

## Formát licenčního klíče

Klíče jsou generovány s kontrolním součtem HMAC-SHA256:

```
UAML-<TIER>-<PAYLOAD>-<CHECKSUM>
```

Příklad: `UAML-PRO-20260315-A1B2C3D4`

## Datová třída `LicenseKey`

Pole:
- `key: str` — celý řetězec licenčního klíče
- `tier: str` — normalizovaný název úrovně
- `issued_at: str` — časové razítko ISO 8601
- `expires_at: str` — datum vypršení ISO 8601
- `customer_id: Optional[int]`
- `features: list[str]` — názvy povolených funkcí
- `max_memories: int` — limit úložiště
- `max_users: int` — limit uživatelů

## `LicenseManager`

Hlavní třída pro životní cyklus licence:

```python
from uaml.licensing import LicenseManager

lm = LicenseManager(db_path="licenses.db")

# Generování klíče
key = lm.generate_key(tier="professional", customer_id=42, days=365)

# Validace klíče
result = lm.validate_key("UAML-PRO-...")
# Vrací: {valid: bool, tier: str, expires_at: str, features: [...]}

# Odvolání klíče
lm.revoke_key("UAML-PRO-...")

# Výpis aktivních licencí
licenses = lm.list_licenses(customer_id=42)
```

## `LicenseServer`

HTTP server pro validaci licencí (interní použití):

```python
from uaml.licensing import LicenseServer

server = LicenseServer(host="127.0.0.1", port=8792)
server.start()
```

## Feature Gate (`uaml/feature_gate.py`)

### `FeatureGate`

Řídí dostupnost funkcí na základě licenční úrovně:

```python
from uaml.feature_gate import FeatureGate

gate = FeatureGate(license_manager=lm)

# Kontrola funkce
if gate.is_available("focus_engine"):
    ...

# Vyžadování funkce (vyvolá FeatureNotAvailable)
gate.require("federation")

# Výpis dostupných funkcí
features = gate.available_features()
```

### `TrialManager`

Správa 7denní zkušební verze:

```python
from uaml.feature_gate import TrialManager

trial = TrialManager(db_path="trial.db")

# Spuštění zkušební verze
trial.start_trial(machine_id="abc123")

# Kontrola stavu zkušební verze
status = trial.get_status(machine_id="abc123")
# {active: bool, days_remaining: int, started_at: str, expires_at: str}

# Vypršela zkušební verze?
if trial.is_expired(machine_id="abc123"):
    ...
```

### Dekorátor `require_feature`

```python
from uaml.feature_gate import require_feature

@require_feature("focus_engine")
def advanced_recall(query):
    ...
```

## Matice funkcí podle úrovně

| Funkce | Community | Starter | Professional | Team | Enterprise |
|--------|-----------|---------|--------------|------|------------|
| Základní paměť | ✅ | ✅ | ✅ | ✅ | ✅ |
| Focus Engine | ❌ | ✅ | ✅ | ✅ | ✅ |
| MCP bridge | ❌ | ❌ | ✅ | ✅ | ✅ |
| Export/Import | ❌ | ❌ | ✅ | ✅ | ✅ |
| Federace | ❌ | ❌ | ❌ | ✅ | ✅ |
| PQC šifrování | ❌ | ❌ | ❌ | ❌ | ✅ |
| Vlastní SLA | ❌ | ❌ | ❌ | ❌ | ✅ |

## Pokrytí testy

- 30 licenčních testů (`tests/test_licensing.py`)
- 28 testů feature gate (`tests/test_feature_gate.py`)

## Soubory

| Soubor | Účel |
|--------|------|
| `uaml/licensing.py` | Generování klíčů, validace, LicenseManager, LicenseServer |
| `uaml/feature_gate.py` | FeatureGate, TrialManager, dekorátor require_feature |
| `tests/test_licensing.py` | 30 testů |
| `tests/test_feature_gate.py` | 28 testů |
