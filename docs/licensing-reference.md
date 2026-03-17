# UAML Licensing System Reference

> © 2026 GLG, a.s. | UAML v1.0 | Status: DRAFT

## Overview

The licensing system provides key generation, validation, trial management, and feature gating. Located in `uaml/licensing.py`, `uaml/feature_gate.py`.

## License Tiers

| Tier | Features | Price |
|------|----------|-------|
| `community` | Basic memory, local storage | Free |
| `starter` | + Focus Engine, basic presets | €8/mo |
| `professional` | + Full Focus Engine, MCP, export/import | €29/mo |
| `team` | + Federation, multi-user, RBAC | €190/mo |
| `enterprise` | + Custom SLA, PQC encryption, on-prem | Custom |

Annual billing: 10× monthly (2 months free).

## License Key Format

Keys are generated with HMAC-SHA256 checksum:

```
UAML-<TIER>-<PAYLOAD>-<CHECKSUM>
```

Example: `UAML-PRO-20260315-A1B2C3D4`

## `LicenseKey` dataclass

Fields:
- `key: str` — full license key string
- `tier: str` — normalized tier name
- `issued_at: str` — ISO 8601 timestamp
- `expires_at: str` — ISO 8601 expiry
- `customer_id: Optional[int]`
- `features: list[str]` — enabled feature names
- `max_memories: int` — storage limit
- `max_users: int` — user limit

## `LicenseManager`

Main class for license lifecycle:

```python
from uaml.licensing import LicenseManager

lm = LicenseManager(db_path="licenses.db")

# Generate key
key = lm.generate_key(tier="professional", customer_id=42, days=365)

# Validate key
result = lm.validate_key("UAML-PRO-...")
# Returns: {valid: bool, tier: str, expires_at: str, features: [...]}

# Revoke key
lm.revoke_key("UAML-PRO-...")

# List active licenses
licenses = lm.list_licenses(customer_id=42)
```

## `LicenseServer`

HTTP server for license validation (internal use):

```python
from uaml.licensing import LicenseServer

server = LicenseServer(host="127.0.0.1", port=8792)
server.start()
```

## Feature Gate (`uaml/feature_gate.py`)

### `FeatureGate`

Controls feature availability based on license tier:

```python
from uaml.feature_gate import FeatureGate

gate = FeatureGate(license_manager=lm)

# Check feature
if gate.is_available("focus_engine"):
    ...

# Require feature (raises FeatureNotAvailable)
gate.require("federation")

# List available features
features = gate.available_features()
```

### `TrialManager`

7-day trial management:

```python
from uaml.feature_gate import TrialManager

trial = TrialManager(db_path="trial.db")

# Start trial
trial.start_trial(machine_id="abc123")

# Check trial status
status = trial.get_status(machine_id="abc123")
# {active: bool, days_remaining: int, started_at: str, expires_at: str}

# Trial expired?
if trial.is_expired(machine_id="abc123"):
    ...
```

### `require_feature` decorator

```python
from uaml.feature_gate import require_feature

@require_feature("focus_engine")
def advanced_recall(query):
    ...
```

## Feature Matrix by Tier

| Feature | Community | Starter | Professional | Team | Enterprise |
|---------|-----------|---------|--------------|------|------------|
| Basic memory | ✅ | ✅ | ✅ | ✅ | ✅ |
| Focus Engine | ❌ | ✅ | ✅ | ✅ | ✅ |
| MCP bridge | ❌ | ❌ | ✅ | ✅ | ✅ |
| Export/Import | ❌ | ❌ | ✅ | ✅ | ✅ |
| Federation | ❌ | ❌ | ❌ | ✅ | ✅ |
| PQC encryption | ❌ | ❌ | ❌ | ❌ | ✅ |
| Custom SLA | ❌ | ❌ | ❌ | ❌ | ✅ |

## Test Coverage

- 30 licensing tests (`tests/test_licensing.py`)
- 28 feature gate tests (`tests/test_feature_gate.py`)

## Files

| File | Purpose |
|------|---------|
| `uaml/licensing.py` | Key generation, validation, LicenseManager, LicenseServer |
| `uaml/feature_gate.py` | FeatureGate, TrialManager, require_feature decorator |
| `tests/test_licensing.py` | 30 tests |
| `tests/test_feature_gate.py` | 28 tests |
