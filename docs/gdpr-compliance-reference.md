# UAML — GDPR Compliance Reference

> Reference for the `uaml.compliance` module. Covers consent management, DPIA generation, data inventory, breach tracking, and automated auditing.

---

## Consent Management (`compliance.consent`)

**Module:** `uaml/compliance/consent.py`
**GDPR Article:** Art. 7 — Conditions for consent

### ConsentManager

Manages consent records in a dedicated `consents` SQLite table. Every grant/revoke is automatically audited via `MemoryStore.learn()`.

**Constructor:**
```python
from uaml.compliance.consent import ConsentManager
cm = ConsentManager(store)
```

**Table schema (auto-created):**
| Column | Type | Description |
|--------|------|-------------|
| `client_ref` | TEXT | Data subject identifier |
| `purpose` | TEXT | Processing purpose (e.g. `"knowledge_storage"`) |
| `granted_at` | TEXT | ISO timestamp of grant |
| `revoked_at` | TEXT | ISO timestamp of revocation (NULL = active) |
| `granted_by` | TEXT | Who gave consent |
| `scope` | TEXT | Scope details |
| `evidence` | TEXT | Reference to consent document/email |

**Key methods:**

- `grant(client_ref, purpose, *, granted_by, scope="", evidence="") → int` — Record consent grant. Returns consent record ID.
- `revoke(client_ref, purpose) → int` — Revoke active consent. Returns number revoked.
- `check(client_ref, purpose) → bool` — Check if active consent exists.
- `list_consents(client_ref=None, *, include_revoked=False) → list[dict]` — List consent records with optional filters.
- `consent_summary(client_ref) → dict` — Summary with active/revoked counts and details.

**Example:**
```python
cm = ConsentManager(store)
cm.grant("client-42", purpose="knowledge_storage", granted_by="client-42")
cm.check("client-42", purpose="knowledge_storage")  # True
cm.revoke("client-42", purpose="knowledge_storage")
cm.check("client-42", purpose="knowledge_storage")  # False

summary = cm.consent_summary("client-42")
# {'client_ref': 'client-42', 'active_count': 0, 'revoked_count': 1, ...}
```

---

## DPIA & Breach Notification (`compliance.dpia`)

**Module:** `uaml/compliance/dpia.py`
**GDPR Articles:** Art. 35 (DPIA), Art. 33/34 (Breach notification)

### DPIAGenerator

Generates Data Protection Impact Assessments by analyzing the actual stored data.

```python
from uaml.compliance.dpia import DPIAGenerator
dpia = DPIAGenerator(store)
assessment = dpia.generate()
```

**`generate() → dict`** returns a structured DPIA with:
- `system_description` — UAML system name, purpose, data controller, processing basis
- `data_inventory` — total entries, entries by layer, client data count, legal basis coverage
- `risk_assessment` — list of risks with level (low/medium/high), GDPR article references
- `mitigations` — existing controls (PQC encryption, audit trail, ethics pipeline, 5-layer classification)
- `overall_risk` — aggregated risk level
- `recommendation` — action text based on risk level

**Risk checks performed:**
| Risk | GDPR Article | Trigger |
|------|-------------|---------|
| Identity data stored | Art. 5(1)(c) | identity layer entries > 0 |
| Client data without legal basis | Art. 6(1) | legal basis coverage < 100% |
| Large data volume | Art. 5(1)(e) | total entries > 10,000 |

### BreachRegister

Manages breach records with 72-hour DPA notification deadline tracking.

```python
from uaml.compliance.dpia import BreachRegister
register = BreachRegister(store)
breach_id = register.record_breach(description="Unauthorized access", severity="high")
```

**Table schema (auto-created):** `breach_register` with fields: `description`, `severity`, `detected_at`, `reported_at`, `affected_subjects`, `data_categories`, `consequences`, `measures_taken`, `dpa_notified`, `subjects_notified`, `status`.

**Key methods:**
- `record_breach(description, *, severity="medium", affected_subjects="", ...) → int` — Record a breach. Audited automatically.
- `update_breach(breach_id, *, measures_taken, dpa_notified, subjects_notified, status) → bool` — Update response actions.
- `list_breaches(*, status=None) → list[dict]` — List breach records.
- `breach_status(breach_id) → dict` — Status including `hours_elapsed`, `deadline_72h` (bool), and `dpa_notification_required`.

---

## Data Inventory (`compliance.inventory`)

**Module:** `uaml/compliance/inventory.py`
**GDPR Article:** Art. 30 — Records of processing activities

### ProcessingActivity (dataclass)

Fields: `id`, `name`, `purpose`, `legal_basis`, `data_categories` (list), `retention_days`, `recipients` (list), `transfers_outside_eu` (bool), `registered_at`.

### DataInventory

Maintains a registry of processing activities in a `data_inventory` table.

```python
from uaml.compliance.inventory import DataInventory
inv = DataInventory(store)
inv.register_activity("knowledge_storage", purpose="AI memory",
                      legal_basis="legitimate_interest", retention_days=365)
```

**Key methods:**
- `register_activity(name, purpose, legal_basis, *, data_categories, retention_days=365, recipients, transfers_outside_eu=False) → int` — Register/update activity (INSERT OR REPLACE).
- `list_activities() → list[ProcessingActivity]` — All registered activities.
- `remove_activity(name) → bool` — Remove by name.
- `generate_report() → dict` — Art. 30 compliance report with totals, legal bases breakdown, EU transfer count.
- `check_compliance() → list[str]` — Returns list of compliance issues (missing purpose, legal basis, etc.).

---

## Compliance Auditor (`compliance.auditor`)

**Module:** `uaml/compliance/auditor.py`
**Standards:** GDPR, ISO 27001, Internal policies

### Data Models

**`Severity`** enum: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`

**`ComplianceStandard`** enum: `GDPR`, `ISO27001`, `INTERNAL`

**`Finding`** dataclass — a single check result with `check_id`, `title`, `description`, `severity`, `standard`, `article`, `control`, `passed`, `details`, `recommendation`.

**`AuditReport`** dataclass — complete report with `findings`, `summary`, plus computed properties: `passed`, `failed`, `critical_findings`, `score` (0–100).

### ComplianceAuditor

Runs automated checks across all standards. Produces actionable findings.

```python
from uaml.compliance import ComplianceAuditor
auditor = ComplianceAuditor(store)
report = auditor.full_audit()
print(f"Score: {report.score}/100, Critical: {len(report.critical_findings)}")
```

**Audit methods:**
- `full_audit() → AuditReport` — All checks (GDPR + ISO 27001 + Internal).
- `gdpr_check() → AuditReport` — GDPR checks only.
- `retention_check(max_age_days=365) → AuditReport` — Storage limitation check.
- `access_report(subject_ref, *, include_audit=True) → dict` — GDPR Art. 15 subject access report.
- `erasure_report(subject_ref) → dict` — Art. 17 erasure preview.
- `execute_erasure(subject_ref) → dict` — **DESTRUCTIVE** — Art. 17 erasure execution.

**Checks performed:**

| Check ID | Standard | Article/Control | What it checks |
|----------|----------|----------------|----------------|
| GDPR-001 | GDPR | Art. 6(1) | Legal basis for client data |
| GDPR-002 | GDPR | Art. 5(1)(b) | Purpose limitation (topic/project coverage) |
| GDPR-003 | GDPR | Art. 5(1)(c) | Data minimization (duplicates) |
| GDPR-004 | GDPR | Art. 5(1)(e) | Storage limitation (old entries) |
| GDPR-005 | GDPR | Art. 7 | Consent tracking for clients |
| GDPR-006 | GDPR | Art. 15 | Subject access request capability |
| GDPR-007 | GDPR | Art. 25 | Data protection by design (ethics pipeline) |
| ISO-001 | ISO 27001 | A.8.15 | Audit trail completeness |
| ISO-002 | ISO 27001 | A.8.3 | Data layer distribution |
| ISO-003 | ISO 27001 | A.8.2 | Access level classification |
| ISO-004 | ISO 27001 | A.8.13 | Backup operations |
| ISO-005 | ISO 27001 | A.8.24 | PQC encryption availability |
| INT-001 | Internal | — | Client data isolation |
| INT-002 | Internal | — | Ethics pipeline activity |
| INT-003 | Internal | — | Content hash integrity |

**Subject access report** (`access_report`) returns:
- All knowledge entries for the subject
- Task entries (if tasks table exists)
- Audit trail mentions
- Processing purposes
- Retention info (oldest/newest entry)
- Data subject rights reminder (Art. 16–21)

---

## GDPR Articles Covered

| Article | Coverage |
|---------|----------|
| Art. 5 | Purpose limitation, data minimization, storage limitation, accountability |
| Art. 6 | Lawfulness — legal basis tracking |
| Art. 7 | Consent management (grant, revoke, check) |
| Art. 15 | Right of access (subject access report) |
| Art. 17 | Right to erasure (preview + execute) |
| Art. 25 | Data protection by design (ethics pipeline check) |
| Art. 30 | Records of processing activities (DataInventory) |
| Art. 32 | Security of processing (PQC encryption) |
| Art. 33/34 | Breach notification (BreachRegister with 72h tracking) |
| Art. 35 | DPIA generation |

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

