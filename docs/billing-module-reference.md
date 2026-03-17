# UAML Billing Module — Reference

**Version:** 1.0 (2026-03-15)
**© 2026 GLG, a.s. All rights reserved.**

## Overview

`uaml.billing` package — invoice generation and email templates for the UAML licensing system. Handles the full lifecycle from payment confirmation to invoice delivery.

## Components

1. **`invoice.py`** — `Invoice`, `InvoiceStore`, `SupplierInfo`, `CustomerInfo`, `LineItem`
2. **`emails.py`** — purchase, upgrade, downgrade, renewal email templates

## Invoice Generator

- HTML invoices (bilingual CZ/EN on the same invoice)
- Sequential numbering: `UAML-YYYY-NNNN`
- Reverse charge support (Article 196, Council Directive 2006/112/EC)
- SQLite storage via `InvoiceStore`
- CSV export for Premier System accounting import

## Invoice Flow

1. **ComGate webhook** → payment confirmed
2. **`InvoiceStore.create_invoice()`** → generates invoice number + HTML
3. Invoice saved to DB + HTML file on disk
4. Email sent with invoice attachment + license key

## Supplier (hardcoded)

| Field | Value |
|-------|-------|
| Company | GLG, a.s., Středisko SW |
| Address | Podnásepní 466/1d, Trnitá, 602 00 Brno |
| IČ | 26288087 |
| DIČ | CZ26288087 |

## Email Templates

- 4 templates: **purchase**, **upgrade**, **downgrade**, **renewal**
- Each returns `{subject, body_html, body_text}`
- Bilingual (`lang="en"` or `lang="cs"`)
- Includes license key, activation command, GLG footer

## API Usage

```python
from uaml.billing import InvoiceStore, SupplierInfo, CustomerInfo, LineItem, Invoice
from uaml.billing import purchase_email

store = InvoiceStore("invoices.db")
invoice = store.create_invoice(
    customer_id=1, license_key="UAML-P-...",
    tier="professional", amount=29.0
)
email = purchase_email("John", "UAML-P-...", "professional", invoice.generate_html())
```

## Accounting Export

```python
csv_data = store.export_batch("2026-03-01", "2026-03-31", format="csv")
```

Exports invoice batch in CSV format compatible with Premier System accounting software.

## Pending

- [ ] PDF generation (reportlab or wkhtmltopdf)
- [ ] Premier API direct integration (waiting for API docs)
- [ ] ComGate webhook trigger implementation
- [ ] Email sending (SMTP relay pending)
