# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Licensing — key generation, validation, and license management.

Provides offline license key validation (HMAC-SHA256) and a SQLite-backed
license management system with activation tracking and audit logging.

Usage:
    from uaml.licensing import LicenseKey, LicenseManager

    # Offline key operations
    key = LicenseKey.generate("Professional")
    result = LicenseKey.validate(key)

    # Full license management
    mgr = LicenseManager("licenses.db")
    license = mgr.issue("Professional", "user@example.com", max_nodes=3)
    mgr.activate(license["key"], node_id="node-1")

© 2026 Ladislav Zamazal / GLG, a.s.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import string
import threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

__all__ = ["LicenseKey", "LicenseManager", "LicenseServer"]

# ---------------------------------------------------------------------------
# Tier mapping
# ---------------------------------------------------------------------------

TIER_CODES = {
    "Community": "CM",
    "Starter": "ST",
    "Professional": "PR",
    "Team": "TM",
    "Enterprise": "EN",
}

CODE_TO_TIER = {v: k for k, v in TIER_CODES.items()}

_ALPHANUM = string.ascii_uppercase + string.digits

# ---------------------------------------------------------------------------
# LicenseKey — stateless key generation & validation
# ---------------------------------------------------------------------------


class LicenseKey:
    """Generate and validate UAML license keys.

    Key format: ``UAML-XXXX-XXXX-XXXX-XXXX``

    The 16 payload characters encode:
      - 2 chars: tier code (CM/ST/PR/TM/EN)
      - 10 chars: random data
      - 4 chars: HMAC checksum (truncated)
    """

    @staticmethod
    def generate(tier: str, secret: str = "uaml-default-secret") -> str:
        """Generate a new license key for the given tier.

        Args:
            tier: One of Community, Starter, Professional, Team, Enterprise.
            secret: HMAC secret for checksum.

        Returns:
            Key string in ``UAML-XXXX-XXXX-XXXX-XXXX`` format.

        Raises:
            ValueError: If tier is not recognised.
        """
        tier_cap = _normalise_tier(tier)
        code = TIER_CODES[tier_cap]
        random_part = "".join(secrets.choice(_ALPHANUM) for _ in range(10))
        payload = code + random_part  # 12 chars
        checksum = _compute_checksum(payload, secret)  # 4 chars
        raw = payload + checksum  # 16 chars total
        return f"UAML-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"

    @staticmethod
    def validate(key: str, secret: str = "uaml-default-secret") -> dict:
        """Validate a license key offline (format + HMAC checksum).

        Returns:
            dict with keys: valid (bool), tier (str|None), error (str|None).
        """
        try:
            raw = _strip_key(key)
        except ValueError as exc:
            return {"valid": False, "tier": None, "error": str(exc)}

        payload = raw[:12]
        checksum = raw[12:16]
        expected = _compute_checksum(payload, secret)

        if not hmac.compare_digest(checksum, expected):
            return {"valid": False, "tier": None, "error": "Invalid checksum"}

        tier_code = raw[:2]
        tier_name = CODE_TO_TIER.get(tier_code)
        if tier_name is None:
            return {"valid": False, "tier": None, "error": f"Unknown tier code: {tier_code}"}

        return {"valid": True, "tier": tier_name, "error": None}

    @staticmethod
    def parse(key: str) -> dict:
        """Parse key structure without validating the checksum.

        Returns:
            dict with keys: tier_code, tier (name or None), random, checksum, raw.
        """
        try:
            raw = _strip_key(key)
        except ValueError:
            return {"tier_code": None, "tier": None, "random": None, "checksum": None, "raw": None}

        tier_code = raw[:2]
        return {
            "tier_code": tier_code,
            "tier": CODE_TO_TIER.get(tier_code),
            "random": raw[2:12],
            "checksum": raw[12:16],
            "raw": raw,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_tier(tier: str) -> str:
    """Normalise tier name to title-case and validate."""
    mapping = {t.lower(): t for t in TIER_CODES}
    t = tier.strip().lower()
    if t not in mapping:
        raise ValueError(f"Unknown tier: {tier!r}. Valid: {', '.join(TIER_CODES)}")
    return mapping[t]


def _strip_key(key: str) -> str:
    """Strip UAML- prefix and dashes, validate format."""
    k = key.strip().upper()
    if not k.startswith("UAML-"):
        raise ValueError("Key must start with UAML-")
    parts = k[5:].split("-")
    if len(parts) != 4 or any(len(p) != 4 for p in parts):
        raise ValueError("Key must have format UAML-XXXX-XXXX-XXXX-XXXX")
    raw = "".join(parts)
    if not all(c in _ALPHANUM for c in raw):
        raise ValueError("Key contains invalid characters")
    return raw


def _compute_checksum(payload: str, secret: str) -> str:
    """HMAC-SHA256 truncated to 4 uppercase alphanumeric chars."""
    h = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # Map hex digest to alphanumeric chars
    result = []
    for i in range(0, len(h), 4):
        val = int(h[i:i + 4], 16) % len(_ALPHANUM)
        result.append(_ALPHANUM[val])
        if len(result) == 4:
            break
    return "".join(result)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS licenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key     TEXT    UNIQUE NOT NULL,
    tier            TEXT    NOT NULL,
    customer_email  TEXT    NOT NULL,
    customer_name   TEXT    DEFAULT '',
    company         TEXT    DEFAULT '',
    issued_at       TEXT    NOT NULL,
    expires_at      TEXT    NOT NULL,
    activated_at    TEXT,
    deactivated_at  TEXT,
    max_nodes       INTEGER DEFAULT 1,
    active_nodes    INTEGER DEFAULT 0,
    status          TEXT    DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS license_activations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id      INTEGER NOT NULL REFERENCES licenses(id),
    node_id         TEXT    NOT NULL,
    hostname        TEXT    DEFAULT '',
    activated_at    TEXT    NOT NULL,
    deactivated_at  TEXT,
    ip_address      TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS license_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id      INTEGER,
    action          TEXT    NOT NULL,
    details         TEXT    DEFAULT '',
    timestamp       TEXT    NOT NULL
);
"""

# ---------------------------------------------------------------------------
# LicenseManager
# ---------------------------------------------------------------------------


class LicenseManager:
    """SQLite-backed license management with activation tracking and audit log.

    Thread-safe: each public method opens its own connection.
    """

    def __init__(self, db_path: str = "licenses.db"):
        self.db_path = Path(db_path)
        self._init_db()

    # -- internal helpers ---------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def _audit(self, conn: sqlite3.Connection, license_id: Optional[int], action: str, details: str = "") -> None:
        conn.execute(
            "INSERT INTO license_audit (license_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (license_id, action, details, _now_iso()),
        )

    # -- public API ---------------------------------------------------------

    def issue(
        self,
        tier: str,
        customer_email: str,
        customer_name: str = "",
        company: str = "",
        duration_days: int = 365,
        max_nodes: int = 1,
        secret: str = "uaml-default-secret",
    ) -> dict:
        """Issue a new license key and store it in the database."""
        key = LicenseKey.generate(tier, secret=secret)
        tier_name = _normalise_tier(tier)
        now = _now_iso()
        expires = _future_iso(duration_days)

        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO licenses
                   (license_key, tier, customer_email, customer_name, company,
                    issued_at, expires_at, max_nodes, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (key, tier_name, customer_email, customer_name, company, now, expires, max_nodes),
            )
            lid = cur.lastrowid
            self._audit(conn, lid, "issue", f"Issued {tier_name} license for {customer_email}")
            conn.commit()
            return {
                "id": lid,
                "key": key,
                "tier": tier_name,
                "customer_email": customer_email,
                "issued_at": now,
                "expires_at": expires,
                "max_nodes": max_nodes,
                "status": "pending",
            }
        finally:
            conn.close()

    def activate(self, key: str, node_id: str, hostname: str = "", ip_address: str = "") -> dict:
        """Activate a license on a node. Idempotent for same node_id."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()
            if not row:
                return {"success": False, "error": "License not found"}

            lid = row["id"]
            status = row["status"]

            if status == "revoked":
                return {"success": False, "error": "License has been revoked"}
            if status == "expired":
                return {"success": False, "error": "License has expired"}

            # Check expiry
            if _is_expired(row["expires_at"]):
                conn.execute("UPDATE licenses SET status = 'expired' WHERE id = ?", (lid,))
                self._audit(conn, lid, "auto_expire", "License expired on activation attempt")
                conn.commit()
                return {"success": False, "error": "License has expired"}

            # Idempotent: check if this node is already active
            existing = conn.execute(
                "SELECT id FROM license_activations WHERE license_id = ? AND node_id = ? AND deactivated_at IS NULL",
                (lid, node_id),
            ).fetchone()

            if existing:
                # Already activated on this node — update timestamp
                now = _now_iso()
                conn.execute(
                    "UPDATE license_activations SET activated_at = ?, hostname = ?, ip_address = ? WHERE id = ?",
                    (now, hostname, ip_address, existing["id"]),
                )
                self._audit(conn, lid, "reactivate", f"Re-activated on node {node_id}")
                conn.commit()
                return {"success": True, "message": "Already activated on this node (updated)"}

            # Check max_nodes
            if row["active_nodes"] >= row["max_nodes"]:
                return {"success": False, "error": f"Max nodes ({row['max_nodes']}) reached"}

            now = _now_iso()
            conn.execute(
                """INSERT INTO license_activations (license_id, node_id, hostname, activated_at, ip_address)
                   VALUES (?, ?, ?, ?, ?)""",
                (lid, node_id, hostname, now, ip_address),
            )
            new_active = row["active_nodes"] + 1
            conn.execute(
                "UPDATE licenses SET active_nodes = ?, activated_at = COALESCE(activated_at, ?), status = 'active' WHERE id = ?",
                (new_active, now, lid),
            )
            self._audit(conn, lid, "activate", f"Activated on node {node_id} ({hostname})")
            conn.commit()
            return {"success": True, "active_nodes": new_active, "max_nodes": row["max_nodes"]}
        finally:
            conn.close()

    def deactivate(self, key: str, node_id: str = "") -> dict:
        """Deactivate a license or a specific node activation."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()
            if not row:
                return {"success": False, "error": "License not found"}

            lid = row["id"]
            now = _now_iso()

            if node_id:
                # Deactivate specific node
                act = conn.execute(
                    "SELECT id FROM license_activations WHERE license_id = ? AND node_id = ? AND deactivated_at IS NULL",
                    (lid, node_id),
                ).fetchone()
                if not act:
                    return {"success": False, "error": f"No active activation for node {node_id}"}

                conn.execute("UPDATE license_activations SET deactivated_at = ? WHERE id = ?", (now, act["id"]))
                new_active = max(0, row["active_nodes"] - 1)
                conn.execute("UPDATE licenses SET active_nodes = ? WHERE id = ?", (new_active, lid))
                self._audit(conn, lid, "deactivate_node", f"Deactivated node {node_id}")
                conn.commit()
                return {"success": True, "active_nodes": new_active}
            else:
                # Deactivate all
                conn.execute(
                    "UPDATE license_activations SET deactivated_at = ? WHERE license_id = ? AND deactivated_at IS NULL",
                    (now, lid),
                )
                conn.execute(
                    "UPDATE licenses SET active_nodes = 0, deactivated_at = ?, status = 'pending' WHERE id = ?",
                    (now, lid),
                )
                self._audit(conn, lid, "deactivate_all", "All nodes deactivated")
                conn.commit()
                return {"success": True, "active_nodes": 0}
        finally:
            conn.close()

    def validate(self, key: str) -> dict:
        """Full validation: key format + DB lookup + expiry + status check."""
        # Offline validation first
        offline = LicenseKey.validate(key)
        if not offline["valid"]:
            return offline

        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()
            if not row:
                return {"valid": False, "tier": offline["tier"], "error": "License not found in database"}

            if row["status"] == "revoked":
                return {"valid": False, "tier": row["tier"], "error": "License has been revoked"}

            if _is_expired(row["expires_at"]):
                if row["status"] != "expired":
                    conn.execute("UPDATE licenses SET status = 'expired' WHERE id = ?", (row["id"],))
                    self._audit(conn, row["id"], "auto_expire", "Expired during validation")
                    conn.commit()
                return {"valid": False, "tier": row["tier"], "error": "License has expired"}

            return {
                "valid": True,
                "tier": row["tier"],
                "error": None,
                "status": row["status"],
                "expires_at": row["expires_at"],
                "active_nodes": row["active_nodes"],
                "max_nodes": row["max_nodes"],
            }
        finally:
            conn.close()

    def status(self, key: str) -> dict:
        """Get detailed license status information."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()
            if not row:
                return {"found": False, "error": "License not found"}

            activations = conn.execute(
                "SELECT node_id, hostname, activated_at, deactivated_at, ip_address "
                "FROM license_activations WHERE license_id = ? ORDER BY activated_at DESC",
                (row["id"],),
            ).fetchall()

            return {
                "found": True,
                "id": row["id"],
                "key": row["license_key"],
                "tier": row["tier"],
                "customer_email": row["customer_email"],
                "customer_name": row["customer_name"],
                "company": row["company"],
                "issued_at": row["issued_at"],
                "expires_at": row["expires_at"],
                "activated_at": row["activated_at"],
                "deactivated_at": row["deactivated_at"],
                "max_nodes": row["max_nodes"],
                "active_nodes": row["active_nodes"],
                "status": row["status"],
                "activations": [dict(a) for a in activations],
            }
        finally:
            conn.close()

    def list_licenses(self, status: Optional[str] = None, tier: Optional[str] = None) -> list:
        """List licenses with optional filters."""
        conn = self._connect()
        try:
            sql = "SELECT * FROM licenses WHERE 1=1"
            params: list = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            if tier:
                sql += " AND tier = ?"
                params.append(_normalise_tier(tier))
            sql += " ORDER BY id DESC"
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def revoke(self, key: str, reason: str = "") -> dict:
        """Revoke a license."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT id, status FROM licenses WHERE license_key = ?", (key,)).fetchone()
            if not row:
                return {"success": False, "error": "License not found"}
            if row["status"] == "revoked":
                return {"success": False, "error": "Already revoked"}

            now = _now_iso()
            conn.execute(
                "UPDATE licenses SET status = 'revoked', deactivated_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            conn.execute(
                "UPDATE license_activations SET deactivated_at = ? WHERE license_id = ? AND deactivated_at IS NULL",
                (now, row["id"]),
            )
            conn.execute("UPDATE licenses SET active_nodes = 0 WHERE id = ?", (row["id"],))
            self._audit(conn, row["id"], "revoke", reason or "License revoked")
            conn.commit()
            return {"success": True}
        finally:
            conn.close()

    def renew(self, key: str, duration_days: int = 365) -> dict:
        """Extend license expiry by duration_days from now (or from current expiry if later)."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT id, expires_at, status FROM licenses WHERE license_key = ?", (key,)).fetchone()
            if not row:
                return {"success": False, "error": "License not found"}
            if row["status"] == "revoked":
                return {"success": False, "error": "Cannot renew a revoked license"}

            # Extend from the later of now or current expiry
            now_dt = datetime.now(timezone.utc)
            try:
                current_exp = datetime.fromisoformat(row["expires_at"])
                if current_exp.tzinfo is None:
                    current_exp = current_exp.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                current_exp = now_dt

            base = max(now_dt, current_exp)
            new_expires = (base + timedelta(days=duration_days)).isoformat()

            new_status = "active" if row["status"] == "expired" else row["status"]
            # If it was pending or active, keep it
            if row["status"] == "expired":
                new_status = "pending"

            conn.execute(
                "UPDATE licenses SET expires_at = ?, status = ? WHERE id = ?",
                (new_expires, new_status, row["id"]),
            )
            self._audit(conn, row["id"], "renew", f"Extended by {duration_days} days, new expiry: {new_expires}")
            conn.commit()
            return {"success": True, "expires_at": new_expires, "status": new_status}
        finally:
            conn.close()

    def stats(self) -> dict:
        """Summary statistics: total, by tier, by status, active nodes."""
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]

            by_tier = {}
            for row in conn.execute("SELECT tier, COUNT(*) as cnt FROM licenses GROUP BY tier"):
                by_tier[row["tier"]] = row["cnt"]

            by_status = {}
            for row in conn.execute("SELECT status, COUNT(*) as cnt FROM licenses GROUP BY status"):
                by_status[row["status"]] = row["cnt"]

            active_nodes = conn.execute("SELECT COALESCE(SUM(active_nodes), 0) FROM licenses").fetchone()[0]

            return {
                "total": total,
                "by_tier": by_tier,
                "by_status": by_status,
                "active_nodes": active_nodes,
            }
        finally:
            conn.close()

    def cleanup_expired(self) -> int:
        """Mark expired licenses as 'expired'. Returns count of newly expired."""
        conn = self._connect()
        try:
            now = _now_iso()
            cur = conn.execute(
                "UPDATE licenses SET status = 'expired' WHERE expires_at < ? AND status NOT IN ('expired', 'revoked')",
                (now,),
            )
            count = cur.rowcount
            if count > 0:
                # Audit each
                rows = conn.execute(
                    "SELECT id FROM licenses WHERE status = 'expired' AND expires_at < ?", (now,)
                ).fetchall()
                for r in rows:
                    self._audit(conn, r["id"], "cleanup_expire", "Marked expired by cleanup")
            conn.commit()
            return count
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _is_expired(expires_at: str) -> bool:
    try:
        exp = datetime.fromisoformat(expires_at)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True


# ---------------------------------------------------------------------------
# LicenseServer — lightweight REST API
# ---------------------------------------------------------------------------


class LicenseServer:
    """Minimal HTTP server for license validation and management.

    Admin endpoints (list, stats) are only served when the request
    originates from localhost.
    """

    def __init__(self, manager: LicenseManager, host: str = "127.0.0.1", port: int = 8790):
        self.manager = manager
        self.host = host
        self.port = port

    def serve(self) -> None:
        """Start the HTTP server (blocking)."""
        manager = self.manager

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress default logging

            def _json_response(self, data: dict, status: int = 200) -> None:
                body = json.dumps(data, indent=2).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length == 0:
                    return {}
                return json.loads(self.rfile.read(length))

            def _is_local(self) -> bool:
                addr = self.client_address[0]
                return addr in ("127.0.0.1", "::1", "localhost")

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                params = parse_qs(parsed.query)

                if path == "/api/validate":
                    key = params.get("key", [""])[0]
                    if not key:
                        self._json_response({"error": "Missing key parameter"}, 400)
                        return
                    self._json_response(manager.validate(key))

                elif path == "/api/status":
                    key = params.get("key", [""])[0]
                    if not key:
                        self._json_response({"error": "Missing key parameter"}, 400)
                        return
                    self._json_response(manager.status(key))

                elif path == "/api/admin/licenses":
                    if not self._is_local():
                        self._json_response({"error": "Admin endpoints are localhost only"}, 403)
                        return
                    status_filter = params.get("status", [None])[0]
                    tier_filter = params.get("tier", [None])[0]
                    self._json_response({"licenses": manager.list_licenses(status=status_filter, tier=tier_filter)})

                elif path == "/api/admin/stats":
                    if not self._is_local():
                        self._json_response({"error": "Admin endpoints are localhost only"}, 403)
                        return
                    self._json_response(manager.stats())

                else:
                    self._json_response({"error": "Not found"}, 404)

            def do_POST(self):
                parsed = urlparse(self.path)
                path = parsed.path

                if path == "/api/activate":
                    data = self._read_json()
                    key = data.get("key", "")
                    node_id = data.get("node_id", "")
                    if not key or not node_id:
                        self._json_response({"error": "Missing key or node_id"}, 400)
                        return
                    result = manager.activate(key, node_id, data.get("hostname", ""), data.get("ip_address", ""))
                    self._json_response(result)

                elif path == "/api/deactivate":
                    data = self._read_json()
                    key = data.get("key", "")
                    if not key:
                        self._json_response({"error": "Missing key"}, 400)
                        return
                    result = manager.deactivate(key, data.get("node_id", ""))
                    self._json_response(result)

                else:
                    self._json_response({"error": "Not found"}, 404)

        server = HTTPServer((self.host, self.port), Handler)
        server.serve_forever()
