# UAML Customer Portal — Reference

**Version:** 1.1 (2026-03-15)
**© 2026 GLG, a.s. All rights reserved.**

## Overview

Portal at `uaml-memory.com/portal` for customer self-service — registration, license management, and billing.

## Pages

1. **Registration** (`/portal/register`) — email + password
2. **Login** (`/portal/login`)
3. **Dashboard** (`/portal/dashboard`) — overview, links to licenses and billing
4. **My Licenses** (`/portal/licenses`) — list of customer's license keys with tier, dates, status, copy button
5. **Billing** (`/portal/billing`) — billing info management

## Billing Flow

- **Private person:** just country selection, prices include DPH
- **Business:** IČO (reg_number), DIČ (vat_id), company name, full billing address
- **VIES validation:** automatic EU VAT ID check via SOAP service
- Billing info collected **before first payment** (not at registration)

## DPH/VAT Rules

| Scenario | DPH |
|----------|-----|
| CZ → CZ business | 21% DPH |
| CZ → EU business (valid VIES VAT ID) | Reverse charge, no DPH |
| CZ → non-EU | No DPH (service export) |
| Anyone without valid VAT ID | With DPH |

## Database Schema

### `customers`

email, password_hash, name, company, phone, vat_id, reg_number, billing_address, billing_city, billing_zip, billing_country, is_business, vat_verified

### `customer_licenses`

customer_id, license_key, tier, purchased_at, expires_at, amount_eur, payment_ref, status

### `customer_audit`

Action logging (customer_id, action, timestamp, details)

## Invoice Details (Supplier)

```
GLG, a.s.
Středisko SW
Podnásepní 466/1d, Trnitá
602 00 Brno, Czech Republic
IČ: 26288087
DIČ: CZ26288087
```

## After Payment Flow

1. ComGate webhook confirms payment
2. Generate invoice (PDF)
3. Generate/assign license key
4. Email customer: invoice + key + activation instructions
5. Log in `plan_changes` + `payments` tables

## Accounting

- Export batch to Premier System API (daily/weekly)
- Premier REST API with Basic auth
- API docs from Pavel (pending)

## Pending

- [ ] ComGate integration (API keys pending)
- [ ] Premier API integration (docs pending)
- [ ] Invoice PDF generation module
- [ ] Email delivery (relay pending)
