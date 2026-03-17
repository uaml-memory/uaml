# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Customer Portal — customer management, authentication, and web UI.

Provides a SQLite-backed customer database with PBKDF2-HMAC-SHA256 password
hashing, HMAC session tokens, newsletter management, and a dark-themed
web portal with bilingual (CZ/EN) support.

Usage:
    from uaml.customer import CustomerDB, CustomerPortal

    db = CustomerDB("customers.db")
    result = db.register("user@example.com", "password123", name="John")

    portal = CustomerPortal(db)
    portal.serve()

© 2026 GLG, a.s.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

__all__ = ["CustomerDB", "CustomerPortal"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOKEN_SECRET = secrets.token_hex(32)
_TOKEN_EXPIRY_SECONDS = 86400  # 24 hours
_PBKDF2_ITERATIONS = 260_000
_SALT_LENGTH = 32

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CUSTOMER_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    UNIQUE NOT NULL,
    password_hash   TEXT    NOT NULL,
    name            TEXT    DEFAULT '',
    company         TEXT    DEFAULT '',
    phone           TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    last_login      TEXT,
    status          TEXT    DEFAULT 'active',
    vat_id          TEXT    DEFAULT '',
    reg_number      TEXT    DEFAULT '',
    billing_address TEXT    DEFAULT '',
    billing_city    TEXT    DEFAULT '',
    billing_zip     TEXT    DEFAULT '',
    billing_country TEXT    DEFAULT '',
    is_business     INTEGER DEFAULT 0,
    vat_verified    INTEGER DEFAULT 0,
    surname         TEXT    DEFAULT '',
    billing_street2 TEXT    DEFAULT '',
    billing_state   TEXT    DEFAULT '',
    billing_email   TEXT    DEFAULT '',
    website         TEXT    DEFAULT '',
    preferred_lang  TEXT    DEFAULT 'en'
);

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    UNIQUE NOT NULL,
    subscribed_at   TEXT    NOT NULL,
    unsubscribed_at TEXT,
    status          TEXT    DEFAULT 'active',
    source          TEXT    DEFAULT 'web'
);

CREATE TABLE IF NOT EXISTS customer_licenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    license_key     TEXT    NOT NULL,
    tier            TEXT    NOT NULL,
    purchased_at    TEXT    NOT NULL,
    expires_at      TEXT,
    amount_eur      REAL    DEFAULT 0,
    payment_ref     TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS customer_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER,
    action          TEXT    NOT NULL,
    details         TEXT    DEFAULT '',
    ip_address      TEXT    DEFAULT '',
    timestamp       TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 and random salt."""
    salt = os.urandom(_SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    try:
        salt_hex, dk_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(dk_hex)
        actual_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(actual_dk, expected_dk)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------


def _generate_token(customer_id: int, secret: str = _TOKEN_SECRET) -> str:
    """Generate HMAC-based session token: customer_id:timestamp:signature."""
    ts = str(int(time.time()))
    payload = f"{customer_id}:{ts}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{customer_id}:{ts}:{sig}"


def _verify_token(token: str, secret: str = _TOKEN_SECRET) -> Optional[dict]:
    """Verify HMAC session token. Returns {customer_id, timestamp} or None."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        customer_id_str, ts_str, sig = parts
        customer_id = int(customer_id_str)
        ts = int(ts_str)

        # Check expiry
        if time.time() - ts > _TOKEN_EXPIRY_SECONDS:
            return None

        # Verify HMAC
        payload = f"{customer_id}:{ts_str}"
        expected_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None

        return {"customer_id": customer_id, "timestamp": ts}
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_vat_vies(vat_id: str) -> bool:
    """Validate VAT number via EU VIES SOAP service. Returns True if valid."""
    import urllib.request
    vat_id = vat_id.strip().replace(" ", "")
    if len(vat_id) < 4:
        return False
    country_code = vat_id[:2].upper()
    vat_number = vat_id[2:]
    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
  xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
  <soapenv:Body>
    <urn:checkVat>
      <urn:countryCode>{country_code}</urn:countryCode>
      <urn:vatNumber>{vat_number}</urn:vatNumber>
    </urn:checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""
    try:
        req = urllib.request.Request(
            "https://ec.europa.eu/taxation_customs/vies/services/checkVatService",
            data=soap_body.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
        # VIES response may use namespace prefix (e.g. <ns2:valid>true</ns2:valid>)
        return ">true<" in body.lower() and "valid" in body.lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CustomerDB
# ---------------------------------------------------------------------------


class CustomerDB:
    """SQLite-backed customer management with authentication and newsletter.

    Thread-safe: each public method acquires its own connection.
    """

    def __init__(self, db_path: str = "customers.db"):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_CUSTOMER_SCHEMA)
            conn.commit()
            # Migrations for existing databases
            _migrations = [
                "ALTER TABLE customers ADD COLUMN vat_id TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN reg_number TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_address TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_city TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_zip TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_country TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN is_business INTEGER DEFAULT 0",
                "ALTER TABLE customers ADD COLUMN vat_verified INTEGER DEFAULT 0",
                "ALTER TABLE customers ADD COLUMN surname TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_street2 TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_state TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN billing_email TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN website TEXT DEFAULT ''",
                "ALTER TABLE customers ADD COLUMN preferred_lang TEXT DEFAULT 'en'",
            ]
            for sql in _migrations:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists
            conn.commit()
        finally:
            conn.close()

    def _audit(self, conn: sqlite3.Connection, customer_id: Optional[int],
               action: str, details: str = "", ip_address: str = "") -> None:
        conn.execute(
            "INSERT INTO customer_audit (customer_id, action, details, ip_address, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (customer_id, action, details, ip_address, _now_iso()),
        )

    # -- Authentication -----------------------------------------------------

    def register(self, email: str, password: str, name: str = "", company: str = "",
                 surname: str = "") -> dict:
        """Register a new customer account."""
        email = email.strip().lower()
        if not email or not password:
            return {"success": False, "error": "Email and password are required"}

        now = _now_iso()
        password_hash = _hash_password(password)

        conn = self._connect()
        try:
            try:
                cur = conn.execute(
                    "INSERT INTO customers (email, password_hash, name, company, surname, created_at, updated_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'active')",
                    (email, password_hash, name, company, surname, now, now),
                )
                cid = cur.lastrowid
                self._audit(conn, cid, "register", f"Registered: {email}")
                conn.commit()
                return {"success": True, "customer_id": cid, "email": email}
            except sqlite3.IntegrityError:
                return {"success": False, "error": "Email already registered"}
        finally:
            conn.close()

    def login(self, email: str, password: str, ip_address: str = "") -> dict:
        """Authenticate customer and return session token."""
        email = email.strip().lower()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM customers WHERE email = ?", (email,)).fetchone()
            if not row:
                return {"success": False, "error": "Invalid email or password"}

            if row["status"] != "active":
                return {"success": False, "error": "Account is not active"}

            if not _verify_password(password, row["password_hash"]):
                self._audit(conn, row["id"], "login_failed", "Wrong password", ip_address)
                conn.commit()
                return {"success": False, "error": "Invalid email or password"}

            now = _now_iso()
            token = _generate_token(row["id"])
            conn.execute("UPDATE customers SET last_login = ? WHERE id = ?", (now, row["id"]))
            self._audit(conn, row["id"], "login", "Successful login", ip_address)
            conn.commit()
            return {"success": True, "customer_id": row["id"], "token": token}
        finally:
            conn.close()

    def verify_token(self, token: str) -> Optional[dict]:
        """Verify session token and return customer info or None."""
        result = _verify_token(token)
        if result is None:
            return None

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, email, name, company, status FROM customers WHERE id = ?",
                (result["customer_id"],),
            ).fetchone()
            if not row or row["status"] != "active":
                return None
            return dict(row)
        finally:
            conn.close()

    # -- Customer management ------------------------------------------------

    def get_customer(self, customer_id: int) -> Optional[dict]:
        """Get customer by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, email, name, company, phone, created_at, updated_at, last_login, status, "
                "vat_id, reg_number, billing_address, billing_city, billing_zip, billing_country, "
                "is_business, vat_verified, surname, billing_street2, billing_state, "
                "billing_email, website, preferred_lang "
                "FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_customer(self, customer_id: int, **fields) -> dict:
        """Update customer fields (name, company, phone, status)."""
        allowed = {"name", "company", "phone", "status", "surname", "website", "preferred_lang"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return {"success": False, "error": "No valid fields to update"}

        updates["updated_at"] = _now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [customer_id]

        conn = self._connect()
        try:
            conn.execute(f"UPDATE customers SET {set_clause} WHERE id = ?", values)
            self._audit(conn, customer_id, "update", f"Updated: {', '.join(updates.keys())}")
            conn.commit()
            return {"success": True, "updated": list(updates.keys())}
        finally:
            conn.close()

    def update_billing(self, customer_id: int, vat_id: str = "", reg_number: str = "",
                       billing_address: str = "", billing_city: str = "",
                       billing_zip: str = "", billing_country: str = "",
                       is_business: int = 0, surname: str = "",
                       billing_street2: str = "", billing_state: str = "",
                       billing_email: str = "", website: str = "",
                       preferred_lang: str = "en") -> dict:
        """Update billing fields for a customer. Triggers VIES validation if vat_id provided."""
        vat_verified = 0
        if vat_id and vat_id.strip():
            vat_verified = 1 if _validate_vat_vies(vat_id) else 0

        conn = self._connect()
        try:
            conn.execute(
                "UPDATE customers SET vat_id=?, reg_number=?, billing_address=?, "
                "billing_city=?, billing_zip=?, billing_country=?, is_business=?, "
                "vat_verified=?, surname=?, billing_street2=?, billing_state=?, "
                "billing_email=?, website=?, preferred_lang=?, updated_at=? WHERE id=?",
                (vat_id, reg_number, billing_address, billing_city, billing_zip,
                 billing_country, is_business, vat_verified, surname, billing_street2,
                 billing_state, billing_email, website, preferred_lang,
                 _now_iso(), customer_id),
            )
            self._audit(conn, customer_id, "update_billing",
                        f"Business={is_business}, VAT={vat_id}, verified={vat_verified}")
            conn.commit()
            return {"success": True, "vat_verified": bool(vat_verified)}
        finally:
            conn.close()

    def list_customers(self, status: str = None) -> list:
        """List customers, optionally filtered by status."""
        conn = self._connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT id, email, name, company, created_at, last_login, status "
                    "FROM customers WHERE status = ? ORDER BY id DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, email, name, company, created_at, last_login, status "
                    "FROM customers ORDER BY id DESC"
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def customer_licenses(self, customer_id: int) -> list:
        """List licenses linked to a customer."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM customer_licenses WHERE customer_id = ? ORDER BY purchased_at DESC",
                (customer_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def link_license(self, customer_id: int, license_key: str, tier: str,
                     amount_eur: float = 0, payment_ref: str = "") -> dict:
        """Link a license key to a customer."""
        now = _now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO customer_licenses (customer_id, license_key, tier, purchased_at, "
                "amount_eur, payment_ref, status) VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (customer_id, license_key, tier, now, amount_eur, payment_ref),
            )
            lid = cur.lastrowid
            self._audit(conn, customer_id, "link_license",
                        f"Linked {tier} license: {license_key}, €{amount_eur}")
            conn.commit()
            return {"success": True, "license_id": lid}
        finally:
            conn.close()

    # -- Newsletter ---------------------------------------------------------

    def subscribe(self, email: str, source: str = "web") -> dict:
        """Subscribe email to newsletter. Idempotent — reactivates if unsubscribed."""
        email = email.strip().lower()
        now = _now_iso()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id, status FROM newsletter_subscribers WHERE email = ?", (email,)
            ).fetchone()

            if existing:
                if existing["status"] == "active":
                    return {"success": True, "message": "Already subscribed"}
                # Reactivate
                conn.execute(
                    "UPDATE newsletter_subscribers SET status = 'active', subscribed_at = ?, "
                    "unsubscribed_at = NULL, source = ? WHERE id = ?",
                    (now, source, existing["id"]),
                )
                conn.commit()
                return {"success": True, "message": "Resubscribed"}

            conn.execute(
                "INSERT INTO newsletter_subscribers (email, subscribed_at, status, source) "
                "VALUES (?, ?, 'active', ?)",
                (email, now, source),
            )
            conn.commit()
            return {"success": True, "message": "Subscribed"}
        finally:
            conn.close()

    def unsubscribe(self, email: str) -> dict:
        """Unsubscribe email from newsletter."""
        email = email.strip().lower()
        now = _now_iso()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT id, status FROM newsletter_subscribers WHERE email = ?", (email,)
            ).fetchone()
            if not row:
                return {"success": False, "error": "Email not found"}
            if row["status"] == "unsubscribed":
                return {"success": True, "message": "Already unsubscribed"}

            conn.execute(
                "UPDATE newsletter_subscribers SET status = 'unsubscribed', unsubscribed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            conn.commit()
            return {"success": True, "message": "Unsubscribed"}
        finally:
            conn.close()

    def list_subscribers(self, status: str = "active") -> list:
        """List newsletter subscribers by status."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, email, subscribed_at, status, source FROM newsletter_subscribers "
                "WHERE status = ? ORDER BY subscribed_at DESC", (status,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def subscriber_count(self) -> dict:
        """Get newsletter subscriber counts."""
        conn = self._connect()
        try:
            active = conn.execute(
                "SELECT COUNT(*) FROM newsletter_subscribers WHERE status = 'active'"
            ).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM newsletter_subscribers").fetchone()[0]
            return {"active": active, "total": total}
        finally:
            conn.close()

    # -- Stats --------------------------------------------------------------

    def stats(self) -> dict:
        """Summary statistics for admin dashboard."""
        conn = self._connect()
        try:
            total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM customers WHERE status = 'active'"
            ).fetchone()[0]
            revenue_total = conn.execute(
                "SELECT COALESCE(SUM(amount_eur), 0) FROM customer_licenses"
            ).fetchone()[0]
            subscribers = conn.execute(
                "SELECT COUNT(*) FROM newsletter_subscribers WHERE status = 'active'"
            ).fetchone()[0]

            by_tier = {}
            for row in conn.execute(
                "SELECT tier, COUNT(*) as cnt FROM customer_licenses GROUP BY tier"
            ):
                by_tier[row["tier"]] = row["cnt"]

            return {
                "total_customers": total_customers,
                "active": active,
                "revenue_total": round(revenue_total, 2),
                "subscribers": subscribers,
                "by_tier": by_tier,
            }
        finally:
            conn.close()

    # -- Audit access -------------------------------------------------------

    def get_audit(self, customer_id: int = None, limit: int = 50) -> list:
        """Get audit trail entries."""
        conn = self._connect()
        try:
            if customer_id:
                rows = conn.execute(
                    "SELECT * FROM customer_audit WHERE customer_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (customer_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM customer_audit ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Bilingual strings
# ---------------------------------------------------------------------------

_STRINGS = {
    "en": {
        "login_title": "UAML — Customer Login",
        "register_title": "UAML — Create Account",
        "dashboard_title": "UAML — Dashboard",
        "admin_title": "UAML — Admin Panel",
        "email": "Email",
        "password": "Password",
        "name": "Name",
        "company": "Company",
        "login": "Log In",
        "register": "Create Account",
        "logout": "Log Out",
        "no_account": "Don't have an account?",
        "have_account": "Already have an account?",
        "welcome": "Welcome",
        "licenses": "Your Licenses",
        "key": "License Key",
        "tier": "Tier",
        "purchased": "Purchased",
        "expires": "Expires",
        "status": "Status",
        "amount": "Amount",
        "account": "Account Details",
        "save": "Save",
        "newsletter": "Newsletter",
        "subscribed": "Subscribed",
        "subscribe": "Subscribe",
        "unsubscribe": "Unsubscribe",
        "customers": "Customers",
        "search": "Search...",
        "revenue": "Revenue",
        "subscribers": "Subscribers",
        "overview": "Overview",
        "total": "Total",
        "active": "Active",
        "error_login": "Invalid email or password",
        "error_register": "Registration failed",
        "success_register": "Account created! Please log in.",
        "no_licenses": "No licenses yet.",
        "my_licenses": "My Licenses",
        "copy_key": "Copy",
        "upgrade": "Upgrade / Downgrade",
        "billing": "Billing Info",
        "billing_title": "UAML — Billing",
        "licenses_title": "UAML — My Licenses",
        "private_person": "Private person",
        "business": "Business",
        "vat_id": "VAT ID (DIČ)",
        "reg_number": "Reg. Number (IČO)",
        "billing_address": "Billing Address",
        "billing_city": "City",
        "billing_zip": "ZIP Code",
        "billing_country": "Country",
        "vat_verified": "VAT Verified",
        "vat_not_verified": "VAT Not Verified",
        "billing_saved": "Billing info saved.",
        "dashboard": "Dashboard",
        "back": "Back",
    },
    "cs": {
        "login_title": "UAML — Přihlášení",
        "register_title": "UAML — Registrace",
        "dashboard_title": "UAML — Přehled",
        "admin_title": "UAML — Administrace",
        "email": "E-mail",
        "password": "Heslo",
        "name": "Jméno",
        "company": "Firma",
        "login": "Přihlásit se",
        "register": "Vytvořit účet",
        "logout": "Odhlásit se",
        "no_account": "Nemáte účet?",
        "have_account": "Již máte účet?",
        "welcome": "Vítejte",
        "licenses": "Vaše licence",
        "key": "Licenční klíč",
        "tier": "Úroveň",
        "purchased": "Zakoupeno",
        "expires": "Vyprší",
        "status": "Stav",
        "amount": "Částka",
        "account": "Údaje účtu",
        "save": "Uložit",
        "newsletter": "Newsletter",
        "subscribed": "Odebíráte",
        "subscribe": "Odebírat",
        "unsubscribe": "Odhlásit odběr",
        "customers": "Zákazníci",
        "search": "Hledat...",
        "revenue": "Tržby",
        "subscribers": "Odběratelé",
        "overview": "Přehled",
        "total": "Celkem",
        "active": "Aktivní",
        "error_login": "Neplatný e-mail nebo heslo",
        "error_register": "Registrace se nezdařila",
        "success_register": "Účet vytvořen! Přihlaste se.",
        "no_licenses": "Zatím žádné licence.",
        "my_licenses": "Moje licence",
        "copy_key": "Kopírovat",
        "upgrade": "Upgrade / Downgrade",
        "billing": "Fakturační údaje",
        "billing_title": "UAML — Fakturace",
        "licenses_title": "UAML — Moje licence",
        "private_person": "Soukromá osoba",
        "business": "Firma",
        "vat_id": "DIČ",
        "reg_number": "IČO",
        "billing_address": "Fakturační adresa",
        "billing_city": "Město",
        "billing_zip": "PSČ",
        "billing_country": "Země",
        "vat_verified": "DIČ ověřeno",
        "vat_not_verified": "DIČ neověřeno",
        "billing_saved": "Fakturační údaje uloženy.",
        "dashboard": "Přehled",
        "back": "Zpět",
    },
}


_PORTAL_PREFIX = "/portal"

def _detect_lang(accept_language: str) -> str:
    """Detect CZ/EN from Accept-Language header."""
    if not accept_language:
        return "en"
    al = accept_language.lower()
    if "cs" in al or "cz" in al:
        return "cs"
    return "en"


def _t(lang: str, key: str) -> str:
    """Get translated string."""
    return _STRINGS.get(lang, _STRINGS["en"]).get(key, key)


# ---------------------------------------------------------------------------
# HTML templates (dark theme)
# ---------------------------------------------------------------------------

_CSS = """
:root {
    --bg: #0d1117;
    --bg-card: #161b22;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --success: #3fb950;
    --danger: #f85149;
    --warning: #d29922;
    --input-bg: #0d1117;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    min-height: 100vh;
}
.container { max-width: 960px; margin: 0 auto; padding: 2rem 1rem; }
.card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem;
}
h1, h2, h3 { color: var(--text); margin-bottom: 1rem; }
h1 { font-size: 1.5rem; }
h2 { font-size: 1.25rem; }
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); text-decoration: underline; }
.form-group { margin-bottom: 1rem; }
label { display: block; margin-bottom: 0.25rem; color: var(--text-muted); font-size: 0.875rem; }
input[type="text"], input[type="email"], input[type="password"] {
    width: 100%; padding: 0.5rem 0.75rem; background: var(--input-bg);
    border: 1px solid var(--border); border-radius: 6px; color: var(--text);
    font-size: 1rem;
}
input:focus { outline: none; border-color: var(--accent); }
button, .btn {
    display: inline-block; padding: 0.5rem 1rem; background: var(--accent);
    color: #fff; border: none; border-radius: 6px; cursor: pointer;
    font-size: 0.875rem; font-weight: 500;
}
button:hover, .btn:hover { background: var(--accent-hover); }
.btn-danger { background: var(--danger); }
.btn-danger:hover { background: #da3633; }
.btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; }
table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
th, td {
    text-align: left; padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border);
}
th { color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.badge {
    display: inline-block; padding: 0.125rem 0.5rem; border-radius: 1rem;
    font-size: 0.75rem; font-weight: 500;
}
.badge-active { background: #0d4429; color: var(--success); }
.badge-expired { background: #3d1e14; color: var(--danger); }
.badge-pending { background: #2d2000; color: var(--warning); }
.header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border);
}
.logo { font-weight: 700; font-size: 1.25rem; color: var(--accent); }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
.stat-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.25rem; text-align: center;
}
.stat-value { font-size: 2rem; font-weight: 700; color: var(--accent); }
.stat-label { color: var(--text-muted); font-size: 0.875rem; }
.alert { padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1rem; }
.alert-success { background: #0d4429; color: var(--success); border: 1px solid #196c2e; }
.alert-error { background: #3d1e14; color: var(--danger); border: 1px solid #6e2d22; }
.nav-links { display: flex; gap: 1rem; align-items: center; }
.center-form { max-width: 400px; margin: 4rem auto; }
.toggle-switch { position: relative; display: inline-block; width: 44px; height: 24px; }
.toggle-switch input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
    position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
    background: var(--border); border-radius: 24px; transition: 0.3s;
}
.toggle-slider:before {
    content: ""; position: absolute; height: 18px; width: 18px; left: 3px; bottom: 3px;
    background: var(--text); border-radius: 50%; transition: 0.3s;
}
input:checked + .toggle-slider { background: var(--success); }
input:checked + .toggle-slider:before { transform: translateX(20px); }
"""


def _page(title: str, body: str, nav: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
{nav}
{body}
<footer style="text-align:center;color:var(--text-muted);margin-top:3rem;padding-top:1rem;border-top:1px solid var(--border);font-size:0.75rem">
© 2026 GLG, a.s. — UAML Customer Portal
</footer>
</div>
</body>
</html>"""


def _login_page(lang: str, error: str = "", message: str = "", csrf: str = "") -> str:
    t = lambda k: _t(lang, k)
    alert = ""
    if error:
        alert = f'<div class="alert alert-error">{error}</div>'
    if message:
        alert = f'<div class="alert alert-success">{message}</div>'
    body = f"""
<div class="center-form">
<div class="card">
<h1>{t("login_title")}</h1>
{alert}
<form method="POST" action="/portal/api/login">
<input type="hidden" name="csrf_token" value="{csrf}">
<input type="hidden" name="lang" value="{lang}">
<div class="form-group"><label>{t("email")}</label>
<input type="email" name="email" required autofocus></div>
<div class="form-group"><label>{t("password")}</label>
<input type="password" name="password" required></div>
<button type="submit">{t("login")}</button>
</form>
<p style="margin-top:1rem;color:var(--text-muted)">{t("no_account")}
<a href="/portal/register?lang={lang}">{t("register")}</a></p>
</div></div>"""
    return _page(t("login_title"), body)


def _register_page(lang: str, error: str = "", csrf: str = "") -> str:
    t = lambda k: _t(lang, k)
    alert = f'<div class="alert alert-error">{error}</div>' if error else ""
    body = f"""
<div class="center-form">
<div class="card">
<h1>{t("register_title")}</h1>
{alert}
<form method="POST" action="/portal/api/register">
<input type="hidden" name="csrf_token" value="{csrf}">
<input type="hidden" name="lang" value="{lang}">
<div class="form-group"><label>{t("email")}</label>
<input type="email" name="email" required autofocus></div>
<div class="form-group"><label>{t("password")}</label>
<input type="password" name="password" required minlength="6"></div>
<div class="form-group"><label>{t("name")}</label>
<input type="text" name="name"></div>
<div class="form-group"><label>{"Surname" if lang == "en" else "Příjmení"}</label>
<input type="text" name="surname"></div>
<div class="form-group"><label>{t("company")}</label>
<input type="text" name="company"></div>
<button type="submit">{t("register")}</button>
</form>
<p style="margin-top:1rem;color:var(--text-muted)">{t("have_account")}
<a href="/portal?lang={lang}">{t("login")}</a></p>
</div></div>"""
    return _page(t("register_title"), body)


def _dashboard_page(lang: str, customer: dict, licenses: list, is_subscribed: bool, csrf: str = "") -> str:
    t = lambda k: _t(lang, k)
    nav = f"""<div class="header">
<span class="logo">UAML</span>
<div class="nav-links">
<a href="/portal/licenses?lang={lang}">{t("my_licenses")}</a>
<a href="/portal/billing?lang={lang}">{t("billing")}</a>
<span>{customer.get('email', '')}</span>
<a href="/portal/api/logout">{t("logout")}</a>
</div></div>"""

    # Licenses table
    if licenses:
        rows = ""
        for lic in licenses:
            status_cls = "badge-active" if lic.get("status") == "active" else "badge-expired"
            rows += f"""<tr>
<td><code>{lic.get('license_key', '')}</code></td>
<td>{lic.get('tier', '')}</td>
<td>{lic.get('purchased_at', '')[:10]}</td>
<td>{(lic.get('expires_at') or '-')[:10] if lic.get('expires_at') else '-'}</td>
<td><span class="badge {status_cls}">{lic.get('status', '')}</span></td>
<td>€{lic.get('amount_eur', 0):.2f}</td>
</tr>"""
        lic_table = f"""<table>
<thead><tr><th>{t("key")}</th><th>{t("tier")}</th><th>{t("purchased")}</th>
<th>{t("expires")}</th><th>{t("status")}</th><th>{t("amount")}</th></tr></thead>
<tbody>{rows}</tbody></table>"""
    else:
        lic_table = f'<p style="color:var(--text-muted)">{t("no_licenses")}</p>'

    checked = "checked" if is_subscribed else ""
    newsletter_action = "/api/unsubscribe" if is_subscribed else "/api/subscribe"
    newsletter_label = t("subscribed") if is_subscribed else t("subscribe")

    body = f"""
<h1>{t("welcome")}, {customer.get('name') or customer.get('email', '')}!</h1>

<div class="card">
<h2>{t("licenses")}</h2>
{lic_table}
</div>

<div class="card">
<h2>{t("account")}</h2>
<form method="POST" action="/portal/api/update-profile">
<input type="hidden" name="csrf_token" value="{csrf}">
<div class="form-group"><label>{t("name")}</label>
<input type="text" name="name" value="{customer.get('name', '')}"></div>
<div class="form-group"><label>{t("company")}</label>
<input type="text" name="company" value="{customer.get('company', '')}"></div>
<button type="submit">{t("save")}</button>
</form>
</div>

<div class="card">
<h2>{t("newsletter")}</h2>
<form method="POST" action="{newsletter_action}">
<input type="hidden" name="csrf_token" value="{csrf}">
<input type="hidden" name="email" value="{customer.get('email', '')}">
<p>{newsletter_label}
<button type="submit" class="btn-sm">
{'✓ ' + t("subscribed") if is_subscribed else t("subscribe")}
</button></p>
</form>
</div>"""
    return _page(t("dashboard_title"), body, nav)


def _admin_page(lang: str, stats: dict, customers: list, subscribers: list) -> str:
    t = lambda k: _t(lang, k)
    nav = f"""<div class="header">
<span class="logo">UAML Admin</span>
<div class="nav-links"><a href="/portal/">{t("login")}</a></div></div>"""

    # Stats cards
    stats_html = f"""<div class="stats-grid">
<div class="stat-card"><div class="stat-value">{stats.get('total_customers', 0)}</div>
<div class="stat-label">{t("customers")} ({t("total")})</div></div>
<div class="stat-card"><div class="stat-value">{stats.get('active', 0)}</div>
<div class="stat-label">{t("customers")} ({t("active")})</div></div>
<div class="stat-card"><div class="stat-value">€{stats.get('revenue_total', 0):,.2f}</div>
<div class="stat-label">{t("revenue")}</div></div>
<div class="stat-card"><div class="stat-value">{stats.get('subscribers', 0)}</div>
<div class="stat-label">{t("subscribers")}</div></div>
</div>"""

    # Customer table
    cust_rows = ""
    for c in customers:
        status_cls = "badge-active" if c.get("status") == "active" else "badge-expired"
        cust_rows += f"""<tr>
<td>{c.get('id', '')}</td><td>{c.get('email', '')}</td><td>{c.get('name', '')}</td>
<td>{c.get('company', '')}</td><td><span class="badge {status_cls}">{c.get('status', '')}</span></td>
<td>{(c.get('last_login') or '-')[:10] if c.get('last_login') else '-'}</td>
</tr>"""

    cust_table = f"""<div class="card"><h2>{t("customers")}</h2>
<table><thead><tr><th>ID</th><th>{t("email")}</th><th>{t("name")}</th>
<th>{t("company")}</th><th>{t("status")}</th><th>Last Login</th></tr></thead>
<tbody>{cust_rows}</tbody></table></div>"""

    # Subscribers
    sub_rows = ""
    for s in subscribers:
        sub_rows += f"<tr><td>{s.get('email','')}</td><td>{s.get('source','')}</td><td>{s.get('subscribed_at','')[:10]}</td></tr>"

    sub_table = f"""<div class="card"><h2>{t("subscribers")}</h2>
<table><thead><tr><th>{t("email")}</th><th>Source</th><th>Since</th></tr></thead>
<tbody>{sub_rows}</tbody></table></div>"""

    # Tier breakdown
    by_tier = stats.get("by_tier", {})
    tier_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in by_tier.items())
    tier_table = f"""<div class="card"><h2>Licenses by Tier</h2>
<table><thead><tr><th>{t("tier")}</th><th>Count</th></tr></thead>
<tbody>{tier_rows}</tbody></table></div>""" if by_tier else ""

    body = f"""<h1>{t("admin_title")}</h1>
{stats_html}
{cust_table}
{sub_table}
{tier_table}"""
    return _page(t("admin_title"), body, nav)


def _licenses_page(lang: str, customer: dict, licenses: list, csrf: str = "") -> str:
    t = lambda k: _t(lang, k)
    nav = f"""<div class="header">
<span class="logo">UAML</span>
<div class="nav-links">
<a href="/portal/dashboard?lang={lang}">{t("dashboard")}</a>
<a href="/portal/billing?lang={lang}">{t("billing")}</a>
<span>{customer.get('email', '')}</span>
<a href="/portal/api/logout">{t("logout")}</a>
</div></div>"""

    if licenses:
        rows = ""
        for lic in licenses:
            status_cls = "badge-active" if lic.get("status") == "active" else "badge-expired"
            exp = (lic.get('expires_at') or '-')[:10] if lic.get('expires_at') else '-'
            key = lic.get('license_key', '')
            rows += f"""<tr>
<td><code id="lk-{lic.get('id','')}">{key}</code>
<button class="btn-sm" onclick="navigator.clipboard.writeText('{key}')" title="{t('copy_key')}">📋</button></td>
<td>{lic.get('tier', '')}</td>
<td>{lic.get('purchased_at', '')[:10]}</td>
<td>{exp}</td>
<td><span class="badge {status_cls}">{lic.get('status', '')}</span></td>
<td><a href="#" class="btn-sm" style="pointer-events:none;opacity:0.5">{t('upgrade')}</a></td>
</tr>"""
        lic_table = f"""<table>
<thead><tr><th>{t("key")}</th><th>{t("tier")}</th><th>{t("purchased")}</th>
<th>{t("expires")}</th><th>{t("status")}</th><th></th></tr></thead>
<tbody>{rows}</tbody></table>"""
    else:
        lic_table = f'<p style="color:var(--text-muted)">{t("no_licenses")}</p>'

    body = f"""<h1>{t("my_licenses")}</h1>
<div class="card">
{lic_table}
</div>"""
    return _page(t("licenses_title"), body, nav)


def _billing_page(lang: str, customer: dict, csrf: str = "", message: str = "") -> str:
    t = lambda k: _t(lang, k)
    nav = f"""<div class="header">
<span class="logo">UAML</span>
<div class="nav-links">
<a href="/portal/dashboard?lang={lang}">{t("dashboard")}</a>
<a href="/portal/licenses?lang={lang}">{t("my_licenses")}</a>
<span>{customer.get('email', '')}</span>
<a href="/portal/api/logout">{t("logout")}</a>
</div></div>"""

    alert = f'<div class="alert alert-success">{message}</div>' if message else ""
    is_biz = customer.get("is_business", 0)
    vat_ver = customer.get("vat_verified", 0)
    vat_badge = (f'<span class="badge badge-active">{t("vat_verified")} ✓</span>'
                 if vat_ver else
                 f'<span class="badge badge-expired">{t("vat_not_verified")}</span>')
    vat_info = vat_badge if customer.get("vat_id") else ""

    countries = [
        ("CZ", "Česká republika / Czech Republic"), ("SK", "Slovensko / Slovakia"),
        ("DE", "Německo / Germany"), ("AT", "Rakousko / Austria"),
        ("PL", "Polsko / Poland"), ("HU", "Maďarsko / Hungary"),
        ("US", "USA"), ("GB", "Velká Británie / United Kingdom"),
        ("OTHER", "Other / Jiná"),
    ]
    country_options = ""
    cur_country = customer.get("billing_country", "")
    for code, label in countries:
        sel = "selected" if code == cur_country else ""
        country_options += f'<option value="{code}" {sel}>{label}</option>'

    # Labels for new fields
    lbl_firstname = "First Name" if lang == "en" else "Jméno"
    lbl_surname = "Surname" if lang == "en" else "Příjmení"
    lbl_phone = "Phone" if lang == "en" else "Telefon"
    lbl_website = "Website" if lang == "en" else "Web"
    lbl_billing_email = "Billing Email" if lang == "en" else "Fakturační email"
    lbl_billing_email_ph = "If different from account email" if lang == "en" else "Pokud se liší od e-mailu účtu"
    lbl_inv_lang = "Invoice Language" if lang == "en" else "Jazyk faktury"
    lbl_street2 = "Address Line 2" if lang == "en" else "Adresa řádek 2"
    lbl_state = "State/Region" if lang == "en" else "Kraj"

    sel_style = ("width:100%;padding:0.5rem;background:var(--input-bg);"
                 "border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:1rem")
    cur_plang = customer.get("preferred_lang", "en")
    plang_en_sel = "selected" if cur_plang == "en" else ""
    plang_cs_sel = "selected" if cur_plang == "cs" else ""

    body = f"""<h1>{t("billing")}</h1>
{alert}
<div class="card">
<form method="POST" action="/portal/api/update-billing">
<input type="hidden" name="csrf_token" value="{csrf}">
<input type="hidden" name="lang" value="{lang}">

<h2>{"Personal Info" if lang == "en" else "Osobní údaje"}</h2>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
<div class="form-group"><label>{lbl_firstname}</label>
<input type="text" name="name" value="{customer.get('name', '')}"></div>
<div class="form-group"><label>{lbl_surname}</label>
<input type="text" name="surname" value="{customer.get('surname', '')}"></div>
</div>
<div class="form-group"><label>{lbl_phone}</label>
<input type="text" name="phone" value="{customer.get('phone', '')}"></div>
<div class="form-group"><label>{lbl_website}</label>
<input type="text" name="website" value="{customer.get('website', '')}" placeholder="https://"></div>
<div class="form-group"><label>{lbl_billing_email}</label>
<input type="email" name="billing_email" value="{customer.get('billing_email', '')}" placeholder="{lbl_billing_email_ph}"></div>
<div class="form-group"><label>{lbl_inv_lang}</label>
<select name="preferred_lang" style="{sel_style}">
<option value="en" {plang_en_sel}>English</option>
<option value="cs" {plang_cs_sel}>Čeština</option>
</select></div>

<hr style="border-color:var(--border);margin:1.5rem 0">

<div class="form-group">
<label><input type="radio" name="is_business" value="0" {"checked" if not is_biz else ""}
  onchange="document.getElementById('biz-fields').style.display='none'"> {t("private_person")}</label>
<label style="margin-left:1.5rem"><input type="radio" name="is_business" value="1" {"checked" if is_biz else ""}
  onchange="document.getElementById('biz-fields').style.display='block'"> {t("business")}</label>
</div>

<div id="biz-fields" style="display:{"block" if is_biz else "none"}">
<div class="form-group"><label>{t("company")}</label>
<input type="text" name="company" value="{customer.get('company', '')}"></div>
<div class="form-group"><label>{t("reg_number")}</label>
<input type="text" name="reg_number" value="{customer.get('reg_number', '')}"></div>
<div class="form-group"><label>{t("vat_id")} {vat_info}</label>
<input type="text" name="vat_id" value="{customer.get('vat_id', '')}" placeholder="CZ12345678"></div>
</div>

<hr style="border-color:var(--border);margin:1.5rem 0">

<h2>{"Address" if lang == "en" else "Adresa"}</h2>
<div class="form-group"><label>{t("billing_address")}</label>
<input type="text" name="billing_address" value="{customer.get('billing_address', '')}"></div>
<div class="form-group"><label>{lbl_street2}</label>
<input type="text" name="billing_street2" value="{customer.get('billing_street2', '')}"></div>
<div style="display:grid;grid-template-columns:2fr 1fr;gap:1rem">
<div class="form-group"><label>{t("billing_city")}</label>
<input type="text" name="billing_city" value="{customer.get('billing_city', '')}"></div>
<div class="form-group"><label>{lbl_state}</label>
<input type="text" name="billing_state" value="{customer.get('billing_state', '')}"></div>
</div>
<div style="display:grid;grid-template-columns:1fr 2fr;gap:1rem">
<div class="form-group"><label>{t("billing_zip")}</label>
<input type="text" name="billing_zip" value="{customer.get('billing_zip', '')}"></div>
<div class="form-group"><label>{t("billing_country")}</label>
<select name="billing_country" style="{sel_style}">
{country_options}
</select></div>
</div>

<button type="submit">{t("save")}</button>
</form>
</div>"""
    return _page(t("billing_title"), body, nav)


# ---------------------------------------------------------------------------
# CSRF tokens
# ---------------------------------------------------------------------------

_csrf_tokens: dict = {}
_csrf_lock = threading.Lock()


def _generate_csrf() -> str:
    token = secrets.token_hex(32)
    with _csrf_lock:
        # Clean old tokens (keep last 1000)
        if len(_csrf_tokens) > 1000:
            oldest = sorted(_csrf_tokens, key=_csrf_tokens.get)[:500]
            for k in oldest:
                del _csrf_tokens[k]
        _csrf_tokens[token] = time.time()
    return token


def _validate_csrf(token: str) -> bool:
    if not token:
        return False
    with _csrf_lock:
        ts = _csrf_tokens.pop(token, None)
    if ts is None:
        return False
    # Valid for 1 hour
    return (time.time() - ts) < 3600


# ---------------------------------------------------------------------------
# CustomerPortal — HTTP server
# ---------------------------------------------------------------------------


class CustomerPortal:
    """Dark-themed bilingual customer portal with admin panel.

    Listens on localhost only. Admin endpoints restricted to local requests.
    """

    def __init__(self, customer_db: CustomerDB, license_manager=None,
                 host: str = "127.0.0.1", port: int = 8791):
        self.customer_db = customer_db
        self.license_manager = license_manager
        self.host = host
        self.port = port

    def serve(self) -> None:
        """Start the HTTP server (blocking)."""
        db = self.customer_db
        lm = self.license_manager

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def _send_html(self, html: str, status: int = 200) -> None:
                body = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.end_headers()
                self.wfile.write(body)

            def _json_response(self, data: dict, status: int = 200) -> None:
                body = json.dumps(data, indent=2).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, location: str, cookie: str = None) -> None:
                self.send_response(302)
                self.send_header("Location", location)
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    return {}
                raw = self.rfile.read(length).decode("utf-8")
                ct = self.headers.get("Content-Type", "")
                if "json" in ct:
                    return json.loads(raw)
                # Parse form data
                result = {}
                for pair in raw.split("&"):
                    if "=" in pair:
                        from urllib.parse import unquote_plus
                        k, v = pair.split("=", 1)
                        result[unquote_plus(k)] = unquote_plus(v)
                return result

            def _get_token(self) -> Optional[str]:
                cookie_header = self.headers.get("Cookie", "")
                sc = SimpleCookie(cookie_header)
                if "session" in sc:
                    return sc["session"].value
                return None

            def _get_customer(self) -> Optional[dict]:
                token = self._get_token()
                if not token:
                    return None
                return db.verify_token(token)

            def _lang(self) -> str:
                # Explicit ?lang= parameter takes priority
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                if "lang" in params:
                    forced = params["lang"][0].lower()
                    if forced in ("cs", "cz"):
                        return "cs"
                    if forced == "en":
                        return "en"
                return _detect_lang(self.headers.get("Accept-Language", ""))


            def _portal_url(self, path, lang_override=None, **extra_params):
                """Build portal URL preserving lang parameter."""
                from urllib.parse import urlparse, parse_qs, urlencode
                parsed = urlparse(path)
                existing = parse_qs(parsed.query)
                params = {}
                for k, v in existing.items():
                    params[k] = v[0] if v else ""
                if "lang" not in params:
                    params["lang"] = lang_override or self._lang()
                params.update(extra_params)
                qs = urlencode(params)
                base = parsed.path
                return f"{base}?{qs}"

            def _is_local(self) -> bool:
                addr = self.client_address[0]
                return addr in ("127.0.0.1", "::1", "localhost")

            def _ip(self) -> str:
                return self.client_address[0]

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                # Strip /portal prefix for reverse proxy
                if path.startswith("/portal"):
                    path = path[len("/portal"):] or "/"
                params = parse_qs(parsed.query)
                lang = self._lang()

                if path == "/":
                    customer = self._get_customer()
                    if customer:
                        self._redirect(self._portal_url("/portal/dashboard", lang_override=lang))
                        return
                    msg = params.get("message", [""])[0]
                    err = params.get("error", [""])[0]
                    csrf = _generate_csrf()
                    self._send_html(_login_page(lang, error=err, message=msg, csrf=csrf))

                elif path == "/register":
                    err = params.get("error", [""])[0]
                    csrf = _generate_csrf()
                    self._send_html(_register_page(lang, error=err, csrf=csrf))

                elif path == "/dashboard":
                    customer = self._get_customer()
                    if not customer:
                        self._redirect(self._portal_url("/portal/", lang_override=lang))
                        return
                    full = db.get_customer(customer["id"])
                    licenses = db.customer_licenses(customer["id"])
                    # Check newsletter
                    subs = db.list_subscribers("active")
                    is_sub = any(s["email"] == customer["email"] for s in subs)
                    csrf = _generate_csrf()
                    self._send_html(_dashboard_page(lang, full or customer, licenses, is_sub, csrf))

                elif path == "/licenses":
                    customer = self._get_customer()
                    if not customer:
                        self._redirect(self._portal_url("/portal/", lang_override=lang))
                        return
                    full = db.get_customer(customer["id"])
                    licenses = db.customer_licenses(customer["id"])
                    csrf = _generate_csrf()
                    self._send_html(_licenses_page(lang, full or customer, licenses, csrf))

                elif path == "/billing":
                    customer = self._get_customer()
                    if not customer:
                        self._redirect(self._portal_url("/portal/", lang_override=lang))
                        return
                    full = db.get_customer(customer["id"])
                    msg = params.get("message", [""])[0]
                    csrf = _generate_csrf()
                    self._send_html(_billing_page(lang, full or customer, csrf, message=msg))

                elif path == "/admin":
                    if not self._is_local():
                        self._json_response({"error": "Admin panel is localhost only"}, 403)
                        return
                    s = db.stats()
                    customers_list = db.list_customers()
                    subs = db.list_subscribers("active")
                    self._send_html(_admin_page(lang, s, customers_list, subs))

                elif path == "/api/me":
                    customer = self._get_customer()
                    if not customer:
                        self._json_response({"error": "Not authenticated"}, 401)
                        return
                    full = db.get_customer(customer["id"])
                    licenses = db.customer_licenses(customer["id"])
                    self._json_response({"customer": full, "licenses": licenses})

                elif path == "/api/admin/customers":
                    if not self._is_local():
                        self._json_response({"error": "Admin endpoints are localhost only"}, 403)
                        return
                    self._json_response({"customers": db.list_customers()})

                elif path == "/api/admin/stats":
                    if not self._is_local():
                        self._json_response({"error": "Admin endpoints are localhost only"}, 403)
                        return
                    self._json_response(db.stats())

                elif path == "/api/logout":
                    self._redirect(
                        self._portal_url("/portal/"),
                        "session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                    )

                else:
                    self._send_html("<h1>404 Not Found</h1>", 404)

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path
                # Strip /portal prefix for reverse proxy
                if path.startswith("/portal"):
                    path = path[len("/portal"):] or "/"
                data = self._read_body()
                ct = self.headers.get("Content-Type", "")
                is_json = "json" in ct
                # Override lang from POST data if present (preserves language through form submissions)
                _post_lang = data.get("lang", "")
                if _post_lang and _post_lang.lower() in ("en", "cs", "cz"):
                    lang = "cs" if _post_lang.lower() in ("cs", "cz") else "en"
                else:
                    lang = self._lang()

                if path == "/api/register":
                    if not is_json:
                        if not _validate_csrf(data.get("csrf_token", "")):
                            self._redirect(self._portal_url("/portal/register", lang_override=lang, error="Invalid session"))
                            return

                    email = data.get("email", "")
                    password = data.get("password", "")
                    name = data.get("name", "")
                    company = data.get("company", "")
                    surname = data.get("surname", "")

                    result = db.register(email, password, name, company, surname=surname)
                    if is_json:
                        self._json_response(result, 200 if result["success"] else 400)
                    else:
                        if result["success"]:
                            self._redirect(self._portal_url("/portal/", message="Account created"))
                        else:
                            from urllib.parse import quote_plus
                            self._redirect(self._portal_url("/portal/register", lang_override=lang, error=quote_plus(result["error"])))

                elif path == "/api/login":
                    if not is_json:
                        if not _validate_csrf(data.get("csrf_token", "")):
                            self._redirect(self._portal_url("/portal/", lang_override=lang, error="Invalid session"))
                            return

                    email = data.get("email", "")
                    password = data.get("password", "")
                    result = db.login(email, password, self._ip())

                    if is_json:
                        self._json_response(result, 200 if result["success"] else 401)
                    else:
                        if result["success"]:
                            cookie = (
                                f"session={result['token']}; Path=/; HttpOnly; "
                                f"SameSite=Strict; Max-Age={_TOKEN_EXPIRY_SECONDS}"
                            )
                            self._redirect(self._portal_url("/portal/dashboard", lang_override=lang), cookie)
                        else:
                            from urllib.parse import quote_plus
                            self._redirect(self._portal_url("/portal/", lang_override=lang, error=quote_plus(result.get("error", "Login failed"))))

                elif path == "/api/logout":
                    self._redirect(
                        self._portal_url("/portal/"),
                        "session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0",
                    )

                elif path == "/api/subscribe":
                    email = data.get("email", "")
                    if email:
                        result = db.subscribe(email)
                        if is_json:
                            self._json_response(result)
                        else:
                            self._redirect(self._portal_url("/portal/dashboard", lang_override=lang))
                    else:
                        if is_json:
                            self._json_response({"success": False, "error": "Email required"}, 400)
                        else:
                            self._redirect(self._portal_url("/portal/dashboard", lang_override=lang))

                elif path == "/api/unsubscribe":
                    email = data.get("email", "")
                    if email:
                        result = db.unsubscribe(email)
                        if is_json:
                            self._json_response(result)
                        else:
                            self._redirect(self._portal_url("/portal/dashboard", lang_override=lang))
                    else:
                        if is_json:
                            self._json_response({"success": False, "error": "Email required"}, 400)
                        else:
                            self._redirect(self._portal_url("/portal/dashboard", lang_override=lang))

                elif path == "/api/update-billing":
                    customer = self._get_customer()
                    if not customer:
                        if is_json:
                            self._json_response({"error": "Not authenticated"}, 401)
                        else:
                            self._redirect(self._portal_url("/portal/", lang_override=lang))
                        return
                    if not is_json:
                        if not _validate_csrf(data.get("csrf_token", "")):
                            self._redirect(self._portal_url("/portal/billing", lang_override=lang))
                            return
                    # Also update name/phone/surname/website/preferred_lang via update_customer
                    profile_fields = {}
                    for fld in ("name", "phone", "surname", "website", "preferred_lang"):
                        if fld in data:
                            profile_fields[fld] = data[fld]
                    if profile_fields:
                        db.update_customer(customer["id"], **profile_fields)
                    result = db.update_billing(
                        customer_id=customer["id"],
                        vat_id=data.get("vat_id", ""),
                        reg_number=data.get("reg_number", ""),
                        billing_address=data.get("billing_address", ""),
                        billing_city=data.get("billing_city", ""),
                        billing_zip=data.get("billing_zip", ""),
                        billing_country=data.get("billing_country", ""),
                        is_business=int(data.get("is_business", 0)),
                        surname=data.get("surname", ""),
                        billing_street2=data.get("billing_street2", ""),
                        billing_state=data.get("billing_state", ""),
                        billing_email=data.get("billing_email", ""),
                        website=data.get("website", ""),
                        preferred_lang=data.get("preferred_lang", "en"),
                    )
                    if is_json:
                        self._json_response(result)
                    else:
                        from urllib.parse import quote_plus
                        self._redirect(self._portal_url("/portal/billing", lang_override=lang,
                                                         message=quote_plus(_t(lang, "billing_saved"))))

                elif path == "/api/update-profile":
                    customer = self._get_customer()
                    if not customer:
                        if is_json:
                            self._json_response({"error": "Not authenticated"}, 401)
                        else:
                            self._redirect(self._portal_url("/portal/", lang_override=lang))
                        return
                    fields = {}
                    if "name" in data:
                        fields["name"] = data["name"]
                    if "company" in data:
                        fields["company"] = data["company"]
                    if fields:
                        db.update_customer(customer["id"], **fields)
                    if is_json:
                        self._json_response({"success": True})
                    else:
                        self._redirect(self._portal_url("/portal/dashboard", lang_override=lang))

                else:
                    if is_json:
                        self._json_response({"error": "Not found"}, 404)
                    else:
                        self._send_html("<h1>404 Not Found</h1>", 404)

        server = HTTPServer((self.host, self.port), Handler)
        print(f"UAML Customer Portal running on http://{self.host}:{self.port}")
        server.serve_forever()
