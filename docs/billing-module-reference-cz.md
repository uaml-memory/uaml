# UAML Billing Module — Referenční dokumentace

**Verze:** 1.0 (2026-03-15)
**© 2026 GLG, a.s. Všechna práva vyhrazena.**

## Přehled

Balíček `uaml.billing` — generování faktur a e-mailové šablony pro licenční systém UAML. Pokrývá celý životní cyklus od potvrzení platby po doručení faktury.

## Komponenty

1. **`invoice.py`** — `Invoice`, `InvoiceStore`, `SupplierInfo`, `CustomerInfo`, `LineItem`
2. **`emails.py`** — e-mailové šablony pro nákup, upgrade, downgrade a obnovu

## Generátor faktur

- HTML faktury (dvojjazyčné CZ/EN na jedné faktuře)
- Sekvenční číslování: `UAML-YYYY-NNNN`
- Podpora reverse charge (článek 196, směrnice Rady 2006/112/ES)
- SQLite úložiště přes `InvoiceStore`
- CSV export pro import do účetního systému Premier

## Průběh fakturace

1. **ComGate webhook** → platba potvrzena
2. **`InvoiceStore.create_invoice()`** → vygeneruje číslo faktury + HTML
3. Faktura uložena do DB + HTML soubor na disk
4. E-mail odeslán s přílohou faktury + licenčním klíčem

## Dodavatel (pevně zadaný)

| Pole | Hodnota |
|------|---------|
| Společnost | GLG, a.s., Středisko SW |
| Adresa | Podnásepní 466/1d, Trnitá, 602 00 Brno |
| IČ | 26288087 |
| DIČ | CZ26288087 |

## E-mailové šablony

- 4 šablony: **nákup** (purchase), **upgrade**, **downgrade**, **obnova** (renewal)
- Každá vrací `{subject, body_html, body_text}`
- Dvojjazyčné (`lang="en"` nebo `lang="cs"`)
- Obsahuje licenční klíč, aktivační příkaz, patičku GLG

## Použití API

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

## Export pro účetnictví

```python
csv_data = store.export_batch("2026-03-01", "2026-03-31", format="csv")
```

Exportuje dávku faktur ve formátu CSV kompatibilním s účetním softwarem Premier System.

## Čeká na implementaci

- [ ] Generování PDF (reportlab nebo wkhtmltopdf)
- [ ] Přímá integrace s Premier API (čekáme na dokumentaci API)
- [ ] Implementace ComGate webhook triggeru
- [ ] Odesílání e-mailů (SMTP relay zatím nevyřešen)
