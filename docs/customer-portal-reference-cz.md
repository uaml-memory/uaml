# UAML Zákaznický portál — Reference

**Verze:** 1.1 (2026-03-15)
**© 2026 GLG, a.s. Všechna práva vyhrazena.**

## Přehled

Portál na `uaml-memory.com/portal` pro zákaznickou samoobsluhu — registrace, správa licencí a fakturace.

## Stránky

1. **Registrace** (`/portal/register`) — email + heslo
2. **Přihlášení** (`/portal/login`)
3. **Dashboard** (`/portal/dashboard`) — přehled, odkazy na licence a fakturaci
4. **Moje licence** (`/portal/licenses`) — seznam licenčních klíčů zákazníka s tierem, daty, stavem, tlačítko kopírování
5. **Fakturace** (`/portal/billing`) — správa fakturačních údajů

## Fakturační flow

- **Soukromá osoba:** pouze výběr země, ceny včetně DPH
- **Firma:** IČO (reg_number), DIČ (vat_id), název firmy, kompletní fakturační adresa
- **VIES validace:** automatická kontrola EU DIČ přes SOAP službu
- Fakturační údaje se sbírají **před první platbou** (ne při registraci)

## Pravidla DPH

| Scénář | DPH |
|--------|-----|
| CZ → CZ firma | 21% DPH |
| CZ → EU firma (platné VIES DIČ) | Reverse charge, bez DPH |
| CZ → mimo EU | Bez DPH (export služby) |
| Kdokoli bez platného DIČ | S DPH |

## Databázové schéma

### `customers`

email, password_hash, name, company, phone, vat_id, reg_number, billing_address, billing_city, billing_zip, billing_country, is_business, vat_verified

### `customer_licenses`

customer_id, license_key, tier, purchased_at, expires_at, amount_eur, payment_ref, status

### `customer_audit`

Logování akcí (customer_id, action, timestamp, details)

## Fakturační údaje (dodavatel)

```
GLG, a.s.
Středisko SW
Podnásepní 466/1d, Trnitá
602 00 Brno, Czech Republic
IČ: 26288087
DIČ: CZ26288087
```

## Flow po platbě

1. ComGate webhook potvrdí platbu
2. Vygenerovat fakturu (PDF)
3. Vygenerovat/přiřadit licenční klíč
4. Email zákazníkovi: faktura + klíč + instrukce k aktivaci
5. Zalogovat do tabulek `plan_changes` + `payments`

## Účetnictví

- Export dávky do Premier System API (denně/týdně)
- Premier REST API s Basic auth
- API dokumentace od Pavla (čeká se)

## Čeká na dokončení

- [ ] ComGate integrace (API klíče čekají)
- [ ] Premier API integrace (dokumentace čeká)
- [ ] Modul generování faktur (PDF)
- [ ] Doručování emailů (relay čeká)
