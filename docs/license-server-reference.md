# UAML License Server — API Reference

**Version:** 1.0  
**Base URL:** `https://license.uaml.ai`  
**© 2026 GLG, a.s. All rights reserved.**

---

## Overview

The UAML License Server manages license validation, device activation, subscription tier changes, and payment webhooks. It runs on the test server (`161.97.184.185`) port 8776, behind nginx with SSL.

---

## Endpoints

### POST /v1/validate

Validate a license key and retrieve tier information.

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

Activate a license on a specific device. Counts against the tier's activation limit.

**Request:**
```json
{
  "license_key": "UAML-P-A1B2C3D4-E5F6G7H8-I9J0K1L2",
  "device_id": "sha256-hostname-hash",
  "os": "Linux 6.6",
  "version": "1.0.0"
}
```

**Response (success):**
```json
{"activated": true, "tier": "professional"}
```

**Response (limit reached):**
```json
{"activated": false, "error": "max activations reached (10)"}
```

Re-activation on the same device does not consume an additional slot.

---

### POST /v1/deactivate

Remove a device activation, freeing up a slot.

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

Check subscription status for a license key.

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

Upgrade or downgrade a subscription tier. Logs the change in audit history.

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

**Downgrade warning** (if active devices exceed new limit):
```json
{"warning": "Active devices (8) exceed new limit (3). Deactivate excess devices."}
```

---

### POST /v1/plan-history

Get the audit trail of all plan changes for a license key.

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

Receive payment notifications from ComGate.

**Request:** Raw ComGate webhook payload  
**Response:** `{"status": "received"}`

---

## Tier Definitions

| Tier | Price (€/mo) | Max Agents | Key Features |
|------|-------------|------------|--------------|
| Community | Free | 1 | Core, CLI, Python API |
| Starter | €8 | 3 | + Compliance, GDPR toolkit |
| Professional | €29 | 10 | + Focus Engine, Security Configurator, Expert on Demand, Federation |
| Team | €190 | 50 | + Neo4j, RBAC, Approval gates |
| Enterprise | Custom | Unlimited | All features |

## License Key Format

```
UAML-{T}-{XXXXXXXX}-{XXXXXXXX}-{XXXXXXXX}
```

Where `{T}` = C (Community), S (Starter), P (Professional), T (Team), E (Enterprise).

## Database Schema

### Tables

- **licenses** — license keys, tiers, organizations, expiration
- **activations** — device registrations per license key
- **plan_changes** — audit trail of all tier changes (who, when, what, why)
- **payments** — ComGate payment records

## Client Integration

```python
# In UAML CLI:
uaml license activate UAML-P-XXXX-YYYY-ZZZZ
uaml license deactivate
uaml license status
uaml license upgrade --tier team
```

## Upgrade / Downgrade — Billing Logic

### Upgrade Flow

1. Customer requests upgrade via portal
2. Server calculates **prorated credit** for remaining days on current tier
3. Server calculates **prorated cost** for remaining days on new tier
4. **Difference = amount to charge** → sent to ComGate as payment request
5. ComGate webhook confirms payment → plan upgraded immediately
6. Next billing date stays the same, but at higher tier price

**Example:**
- Professional (€29/mo), paid March 1, upgrade to Team (€190/mo) on March 15
- Remaining: 16 days = credit €15.47
- New tier prorated: 16 days of €190 = €98.06
- **Charge: €98.06 - €15.47 = €82.59** → ComGate payment
- Next payment: April 1 at €190/mo

### Downgrade Flow

1. Customer requests downgrade via portal
2. Plan changes **immediately** (or at end of period — configurable)
3. Overpayment calculated as **credit** toward next billing cycle
4. **No payment via gateway** — only recalculation of next payment date
5. Credit extends the next billing date or reduces next payment amount

**Example:**
- Team (€190/mo), paid March 1, downgrade to Professional (€29/mo) on March 15
- Remaining credit: 16 days of €190 = €98.06
- New tier daily cost: €29/30 = €0.97/day
- **Credit covers ~101 days** → next payment pushed to ~June 24
- Or: next payment April 1 at reduced amount

### Key Rules

- Payment requests always initiated by **our server**, not the gateway
- ComGate handles payment collection only
- All proration calculations done server-side
- `plan_changes` table logs every change with amounts and reasoning

---

## Offline Behavior

- License cached locally in `~/.uaml/license.json`
- Grace period: 7 days without server contact
- After grace period: degrades to Community tier features
- Re-validates automatically on next internet connection
