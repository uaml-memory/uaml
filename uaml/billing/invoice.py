"""
UAML Invoice Generator
~~~~~~~~~~~~~~~~~~~~~~~

Generates bilingual (CZ/EN) HTML invoices and stores them in SQLite.
PDF conversion can be added later via weasyprint or wkhtmltopdf.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import html as html_mod
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Tier / plan definitions
# ---------------------------------------------------------------------------

TIER_FEATURES = {
    "community": {
        "price_eur": 0,
        "max_agents": 1,
        "features": ["Core Memory API", "CLI Interface", "Python API"],
    },
    "starter": {
        "price_eur": 8,
        "max_agents": 3,
        "features": ["Core Memory API", "CLI Interface", "Python API", "Compliance Module", "GDPR Tools"],
    },
    "professional": {
        "price_eur": 29,
        "max_agents": 10,
        "features": ["Core Memory API", "CLI Interface", "Python API", "Compliance Module", "GDPR Tools", "Focus Engine", "Security Configurator", "Expert on Demand", "Federation"],
    },
    "team": {
        "price_eur": 190,
        "max_agents": 50,
        "features": ["Core Memory API", "CLI Interface", "Python API", "Compliance Module", "GDPR Tools", "Focus Engine", "Security Configurator", "Expert on Demand", "Federation", "Neo4j Integration", "RBAC", "Approval Gates"],
    },
    "enterprise": {
        "price_eur": -1,  # custom
        "max_agents": -1,  # unlimited
        "features": ["All features"],
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class SupplierInfo:
    """Default supplier: GLG, a.s."""

    name: str = "GLG, a.s."
    department: str = "Středisko SW"
    address: str = "Podnásepní 466/1d"
    district: str = "Trnitá"
    city: str = "Brno"
    zip_code: str = "602 00"
    country: str = "Czech Republic"
    reg_number: str = "26288087"       # IČ
    vat_id: str = "CZ26288087"         # DIČ
    email: str = "sales@uaml.ai"
    web: str = "https://uaml-memory.com"


@dataclasses.dataclass
class CustomerInfo:
    """Customer / billing target."""

    name: str = ""
    company: str = ""
    address: str = ""
    city: str = ""
    zip_code: str = ""
    country: str = ""
    reg_number: str = ""   # IČO
    vat_id: str = ""       # DIČ
    email: str = ""


@dataclasses.dataclass
class LineItem:
    """Single invoice line."""

    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    description_cs: str = ""  # Czech translation (optional)

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

class Invoice:
    """Bilingual HTML invoice with VAT / reverse-charge support."""

    def __init__(
        self,
        invoice_number: str,
        issue_date: str,
        due_date: str,
        supplier: SupplierInfo,
        customer: CustomerInfo,
        items: List[LineItem],
        vat_rate: float = 21,
        reverse_charge: bool = False,
        duzp: str | None = None,
        currency: str = "EUR",
        payment_ref: str = "",
        status: str = "issued",
        license_key: str = "",
        tier: str = "",
        subscription_period: str = "",
    ):
        self.invoice_number = invoice_number
        self.issue_date = issue_date
        self.due_date = due_date
        self.supplier = supplier
        self.customer = customer
        self.items = list(items)
        self.vat_rate = vat_rate
        self.reverse_charge = reverse_charge
        self.duzp = duzp or issue_date  # datum uskutečnění zdanitelného plnění
        self.currency = currency
        self.payment_ref = payment_ref
        self.status = status
        self.license_key = license_key
        self.tier = tier
        self.subscription_period = subscription_period

    # -- computed fields -----------------------------------------------------

    @property
    def subtotal(self) -> float:
        return round(sum(it.total for it in self.items), 2)

    @property
    def vat_amount(self) -> float:
        if self.reverse_charge:
            return 0.0
        return round(self.subtotal * self.vat_rate / 100, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.vat_amount, 2)

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API / DB storage."""
        return {
            "invoice_number": self.invoice_number,
            "issue_date": self.issue_date,
            "due_date": self.due_date,
            "duzp": self.duzp,
            "supplier": dataclasses.asdict(self.supplier),
            "customer": dataclasses.asdict(self.customer),
            "items": [
                {
                    "description": it.description,
                    "description_cs": it.description_cs,
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                    "total": it.total,
                }
                for it in self.items
            ],
            "subtotal": self.subtotal,
            "vat_rate": self.vat_rate,
            "vat_amount": self.vat_amount,
            "total": self.total,
            "currency": self.currency,
            "reverse_charge": self.reverse_charge,
            "payment_ref": self.payment_ref,
            "status": self.status,
            "license_key": self.license_key,
            "tier": self.tier,
            "subscription_period": self.subscription_period,
        }

    # -- HTML generation -----------------------------------------------------

    def generate_html(self) -> str:
        """Generate a professional bilingual HTML invoice."""
        e = html_mod.escape
        s = self.supplier
        c = self.customer
        cur = e(self.currency)

        # Build line-item rows
        rows = []
        for idx, it in enumerate(self.items, 1):
            desc = e(it.description)
            if it.description_cs:
                desc += f'<br><span class="cs">{e(it.description_cs)}</span>'
            rows.append(
                f"<tr>"
                f"<td class='num'>{idx}</td>"
                f"<td>{desc}</td>"
                f"<td class='num'>{it.quantity:g}</td>"
                f"<td class='num'>{it.unit_price:,.2f} {cur}</td>"
                f"<td class='num'>{it.total:,.2f} {cur}</td>"
                f"</tr>"
            )
        item_rows = "\n".join(rows)

        # VAT / reverse-charge section
        if self.reverse_charge:
            vat_section = """
            <tr class="vat-row">
                <td colspan="4" class="label">VAT / DPH</td>
                <td class="num">—</td>
            </tr>
            <tr class="rc-note">
                <td colspan="5" class="small">
                    Reverse charge — Article 196 Council Directive 2006/112/EC<br>
                    Přenesená daňová povinnost — čl. 196 Směrnice Rady 2006/112/ES
                </td>
            </tr>
            """
        else:
            vat_section = f"""
            <tr class="vat-row">
                <td colspan="4" class="label">VAT {self.vat_rate:g}% / DPH {self.vat_rate:g}%</td>
                <td class="num">{self.vat_amount:,.2f} {cur}</td>
            </tr>
            """

        # Payment info
        payment_html = ""
        if self.payment_ref:
            payment_html = f"""
            <div class="payment-info">
                <h3>Payment Info / Platební údaje</h3>
                <p><strong>Payment reference / Variabilní symbol:</strong> {e(self.payment_ref)}</p>
                <p><strong>Payment gateway:</strong> ComGate</p>
            </div>
            """

        # License details section
        license_html = ""
        if self.license_key or self.tier:
            tier_info = TIER_FEATURES.get(self.tier.lower(), {})
            max_agents = tier_info.get("max_agents", "—")
            max_agents_str = "Unlimited / Neomezeno" if max_agents == -1 else str(max_agents)
            features = tier_info.get("features", [])
            features_li = "\n".join(
                f"            <li>✓ {e(f)}</li>" for f in features
            )
            license_html = f"""
<div class="license-details">
    <h3>License Details / Detaily licence</h3>
    <table>
        <tr><td><strong>License Key / Licenční klíč:</strong></td><td style="font-family: monospace; font-size: 14px;">{e(self.license_key)}</td></tr>
        <tr><td><strong>Plan / Plán:</strong></td><td>{e(self.tier.capitalize())}</td></tr>
        <tr><td><strong>Subscription Period / Období předplatného:</strong></td><td>{e(self.subscription_period)}</td></tr>
        <tr><td><strong>Max Agents / Max agentů:</strong></td><td>{max_agents_str}</td></tr>
    </table>
    <h4>Included Features / Zahrnuté funkce:</h4>
    <ul>
{features_li}
    </ul>
</div>
"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Invoice {e(self.invoice_number)}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        color: #1a1a2e; background: #fff; font-size: 14px; line-height: 1.5;
        padding: 40px; max-width: 800px; margin: 0 auto;
    }}
    .header {{
        display: flex; justify-content: space-between; align-items: flex-start;
        border-bottom: 3px solid #0f3460; padding-bottom: 20px; margin-bottom: 30px;
    }}
    .header h1 {{
        font-size: 28px; color: #0f3460; letter-spacing: 1px;
    }}
    .header .inv-number {{
        font-size: 16px; color: #555; margin-top: 4px;
    }}
    .logo {{ text-align: right; }}
    .logo .brand {{ font-size: 24px; font-weight: 700; color: #0f3460; }}
    .logo .sub {{ font-size: 12px; color: #888; }}
    .parties {{ display: flex; gap: 40px; margin-bottom: 30px; }}
    .party {{ flex: 1; }}
    .party h3 {{
        font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px;
        color: #888; margin-bottom: 8px; border-bottom: 1px solid #eee; padding-bottom: 4px;
    }}
    .party p {{ margin: 2px 0; font-size: 13px; }}
    .party .name {{ font-weight: 600; font-size: 15px; }}
    .dates {{
        display: flex; gap: 30px; margin-bottom: 30px;
        background: #f8f9fa; padding: 12px 16px; border-radius: 6px;
    }}
    .dates div {{ font-size: 13px; }}
    .dates .lbl {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
    table {{
        width: 100%; border-collapse: collapse; margin-bottom: 20px;
    }}
    thead th {{
        background: #0f3460; color: #fff; padding: 10px 12px;
        font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; text-align: left;
    }}
    thead th.num {{ text-align: right; }}
    tbody td {{
        padding: 10px 12px; border-bottom: 1px solid #eee; font-size: 13px;
    }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    td.label {{ text-align: right; font-weight: 600; }}
    .cs {{ color: #888; font-size: 12px; }}
    .small {{ font-size: 11px; color: #888; padding: 8px 12px; }}
    .subtotal-row td {{ border-top: 2px solid #ddd; }}
    .total-row td {{
        border-top: 2px solid #0f3460; font-size: 16px; font-weight: 700; color: #0f3460;
    }}
    .vat-row td {{ font-size: 13px; }}
    .rc-note td {{ border-bottom: none; }}
    .payment-info {{
        background: #f8f9fa; padding: 16px; border-radius: 6px; margin-bottom: 30px;
    }}
    .license-details {{
        background: #f0f4f8; padding: 16px; border-radius: 6px; margin-bottom: 30px;
        border-left: 4px solid #0f3460;
    }}
    .license-details h3 {{
        font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;
        color: #0f3460; margin-bottom: 10px;
    }}
    .license-details h4 {{
        font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;
        color: #0f3460; margin: 12px 0 6px 0;
    }}
    .license-details table {{ margin-bottom: 8px; }}
    .license-details td {{ padding: 4px 12px 4px 0; font-size: 13px; border: none; }}
    .license-details ul {{ list-style: none; padding-left: 4px; }}
    .license-details li {{ font-size: 13px; margin: 2px 0; }}
    .payment-info h3 {{
        font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;
        color: #0f3460; margin-bottom: 8px;
    }}
    .payment-info p {{ font-size: 13px; margin: 4px 0; }}
    .footer {{
        border-top: 1px solid #eee; padding-top: 16px; text-align: center;
        font-size: 11px; color: #aaa;
    }}
    @media print {{
        body {{ padding: 20px; }}
        .header {{ border-bottom-width: 2px; }}
    }}
</style>
</head>
<body>

<div class="header">
    <div>
        <h1>INVOICE / FAKTURA</h1>
        <div class="inv-number">{e(self.invoice_number)}</div>
    </div>
    <div class="logo">
        <div class="brand">UAML</div>
        <div class="sub">Universal Adaptive Memory Layer</div>
    </div>
</div>

<div class="parties">
    <div class="party">
        <h3>Supplier / Dodavatel</h3>
        <p class="name">{e(s.name)}</p>
        <p>{e(s.department)}</p>
        <p>{e(s.address)}</p>
        <p>{e(s.district)}, {e(s.city)} {e(s.zip_code)}</p>
        <p>{e(s.country)}</p>
        <p>IČ: {e(s.reg_number)} &nbsp;|&nbsp; DIČ: {e(s.vat_id)}</p>
        <p>{e(s.email)} &nbsp;|&nbsp; {e(s.web)}</p>
    </div>
    <div class="party">
        <h3>Customer / Odběratel</h3>
        <p class="name">{e(c.company) if c.company else e(c.name)}</p>
        {"<p>" + e(c.name) + "</p>" if c.company and c.name else ""}
        <p>{e(c.address)}</p>
        <p>{e(c.city)} {e(c.zip_code)}</p>
        <p>{e(c.country)}</p>
        {"<p>IČO: " + e(c.reg_number) + "</p>" if c.reg_number else ""}
        {"<p>DIČ: " + e(c.vat_id) + "</p>" if c.vat_id else ""}
        {"<p>" + e(c.email) + "</p>" if c.email else ""}
    </div>
</div>

<div class="dates">
    <div><span class="lbl">Issue date / Datum vystavení</span><br>{e(self.issue_date)}</div>
    <div><span class="lbl">Tax point / DUZP</span><br>{e(self.duzp)}</div>
    <div><span class="lbl">Due date / Datum splatnosti</span><br>{e(self.due_date)}</div>
</div>

<table>
<thead>
    <tr>
        <th class="num">#</th>
        <th>Description / Popis</th>
        <th class="num">Qty / Množství</th>
        <th class="num">Unit price / Cena za j.</th>
        <th class="num">Total / Celkem</th>
    </tr>
</thead>
<tbody>
    {item_rows}
    <tr class="subtotal-row">
        <td colspan="4" class="label">Subtotal / Mezisoučet</td>
        <td class="num">{self.subtotal:,.2f} {cur}</td>
    </tr>
    {vat_section}
    <tr class="total-row">
        <td colspan="4" class="label">Total / Celkem</td>
        <td class="num">{self.total:,.2f} {cur}</td>
    </tr>
</tbody>
</table>

{payment_html}

{license_html}

<div class="footer">
    <p>{e(s.name)} &nbsp;|&nbsp; {e(s.address)}, {e(s.city)} {e(s.zip_code)} &nbsp;|&nbsp; IČ: {e(s.reg_number)} &nbsp;|&nbsp; DIČ: {e(s.vat_id)}</p>
    <p>{e(s.email)} &nbsp;|&nbsp; {e(s.web)}</p>
</div>

</body>
</html>"""

    def save_html(self, path: str) -> None:
        """Save HTML invoice to file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.generate_html(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Invoice Store (SQLite)
# ---------------------------------------------------------------------------

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number  TEXT    NOT NULL UNIQUE,
    customer_id     INTEGER,
    license_key     TEXT,
    issue_date      TEXT    NOT NULL,
    due_date        TEXT    NOT NULL,
    duzp            TEXT    NOT NULL,
    items_json      TEXT    NOT NULL,
    subtotal        REAL    NOT NULL,
    vat_rate        REAL    NOT NULL,
    vat_amount      REAL    NOT NULL,
    total           REAL    NOT NULL,
    currency        TEXT    NOT NULL DEFAULT 'EUR',
    reverse_charge  INTEGER NOT NULL DEFAULT 0,
    payment_ref     TEXT    DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'issued',
    tier            TEXT    DEFAULT '',
    subscription_period TEXT DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


class InvoiceStore:
    """Persist invoices in a local SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CREATE_SQL)
        self._conn.commit()

    # -- helpers -------------------------------------------------------------

    def _next_number(self, year: int | None = None) -> str:
        year = year or date.today().year
        prefix = f"UAML-{year}-"
        row = self._conn.execute(
            "SELECT invoice_number FROM invoices "
            "WHERE invoice_number LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()
        if row:
            seq = int(row["invoice_number"].split("-")[-1]) + 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    @staticmethod
    def _default_items(tier: str, amount: float, currency: str) -> List[LineItem]:
        return [
            LineItem(
                description=f"UAML License — {tier} tier (annual)",
                description_cs=f"UAML Licence — úroveň {tier} (roční)",
                quantity=1,
                unit_price=amount,
            )
        ]

    # -- public API ----------------------------------------------------------

    def create_invoice(
        self,
        customer_id: int,
        license_key: str,
        tier: str,
        amount: float,
        currency: str = "EUR",
        vat_rate: float = 21,
        reverse_charge: bool = False,
        customer: CustomerInfo | None = None,
        supplier: SupplierInfo | None = None,
        payment_ref: str = "",
        items: List[LineItem] | None = None,
        subscription_start: str = "",
        subscription_end: str = "",
    ) -> Invoice:
        """Create and store a new invoice."""
        supplier = supplier or SupplierInfo()
        customer = customer or CustomerInfo()
        today = date.today()
        inv_number = self._next_number(today.year)
        issue = today.isoformat()
        due = (today + timedelta(days=14)).isoformat()
        line_items = items or self._default_items(tier, amount, currency)

        # Build subscription period string from start/end dates
        subscription_period = ""
        if subscription_start and subscription_end:
            try:
                s_date = date.fromisoformat(subscription_start)
                e_date = date.fromisoformat(subscription_end)
                subscription_period = (
                    f"{s_date.day}.{s_date.month}.{s_date.year} – "
                    f"{e_date.day}.{e_date.month}.{e_date.year}"
                )
            except ValueError:
                subscription_period = f"{subscription_start} – {subscription_end}"

        inv = Invoice(
            invoice_number=inv_number,
            issue_date=issue,
            due_date=due,
            supplier=supplier,
            customer=customer,
            items=line_items,
            vat_rate=vat_rate,
            reverse_charge=reverse_charge,
            currency=currency,
            payment_ref=payment_ref,
            license_key=license_key,
            tier=tier,
            subscription_period=subscription_period,
        )

        items_json = json.dumps(
            [
                {
                    "description": it.description,
                    "description_cs": it.description_cs,
                    "quantity": it.quantity,
                    "unit_price": it.unit_price,
                }
                for it in inv.items
            ],
            ensure_ascii=False,
        )

        self._conn.execute(
            """INSERT INTO invoices
               (invoice_number, customer_id, license_key, issue_date, due_date, duzp,
                items_json, subtotal, vat_rate, vat_amount, total, currency,
                reverse_charge, payment_ref, status, tier, subscription_period)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                inv.invoice_number,
                customer_id,
                license_key,
                inv.issue_date,
                inv.due_date,
                inv.duzp,
                items_json,
                inv.subtotal,
                inv.vat_rate,
                inv.vat_amount,
                inv.total,
                inv.currency,
                int(inv.reverse_charge),
                inv.payment_ref,
                inv.status,
                inv.tier,
                inv.subscription_period,
            ),
        )
        self._conn.commit()
        return inv

    def _row_to_invoice(self, row: sqlite3.Row) -> Invoice:
        items_data = json.loads(row["items_json"])
        line_items = [
            LineItem(
                description=d["description"],
                description_cs=d.get("description_cs", ""),
                quantity=d["quantity"],
                unit_price=d["unit_price"],
            )
            for d in items_data
        ]
        # license_key, tier, subscription_period may not exist in older DB schemas
        keys = row.keys()
        lk = row["license_key"] if "license_key" in keys else ""
        tier = row["tier"] if "tier" in keys else ""
        sp = row["subscription_period"] if "subscription_period" in keys else ""
        return Invoice(
            invoice_number=row["invoice_number"],
            issue_date=row["issue_date"],
            due_date=row["due_date"],
            supplier=SupplierInfo(),
            customer=CustomerInfo(),  # customer detail not stored in DB row
            items=line_items,
            vat_rate=row["vat_rate"],
            reverse_charge=bool(row["reverse_charge"]),
            duzp=row["duzp"],
            currency=row["currency"],
            payment_ref=row["payment_ref"],
            status=row["status"],
            license_key=lk or "",
            tier=tier or "",
            subscription_period=sp or "",
        )

    def get_invoice(self, invoice_number: str) -> Optional[Invoice]:
        """Retrieve a single invoice by number."""
        row = self._conn.execute(
            "SELECT * FROM invoices WHERE invoice_number = ?",
            (invoice_number,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_invoice(row)

    def list_invoices(
        self,
        customer_id: int | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> List[Invoice]:
        """List invoices with optional filters."""
        clauses: List[str] = []
        params: List[Any] = []
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if from_date:
            clauses.append("issue_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("issue_date <= ?")
            params.append(to_date)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM invoices{where} ORDER BY id", params
        ).fetchall()
        return [self._row_to_invoice(r) for r in rows]

    def export_batch(
        self,
        from_date: str,
        to_date: str,
        format: str = "csv",
    ) -> str:
        """Export invoices for accounting (Premier System import)."""
        rows = self._conn.execute(
            "SELECT * FROM invoices WHERE issue_date >= ? AND issue_date <= ? ORDER BY id",
            (from_date, to_date),
        ).fetchall()

        if format == "csv":
            import csv
            import io

            buf = io.StringIO()
            writer = csv.writer(buf, delimiter=";")
            writer.writerow([
                "invoice_number", "customer_id", "license_key",
                "issue_date", "due_date", "duzp",
                "subtotal", "vat_rate", "vat_amount", "total",
                "currency", "reverse_charge", "payment_ref", "status",
            ])
            for r in rows:
                writer.writerow([
                    r["invoice_number"], r["customer_id"], r["license_key"],
                    r["issue_date"], r["due_date"], r["duzp"],
                    r["subtotal"], r["vat_rate"], r["vat_amount"], r["total"],
                    r["currency"], r["reverse_charge"], r["payment_ref"], r["status"],
                ])
            return buf.getvalue()

        elif format == "json":
            return json.dumps(
                [dict(r) for r in rows], ensure_ascii=False, indent=2
            )

        raise ValueError(f"Unsupported export format: {format}")

    def close(self) -> None:
        self._conn.close()
