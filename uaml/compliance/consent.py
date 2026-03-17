# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Consent Management — GDPR Art. 7 consent tracking.

Manages consent records: grant, revoke, check, audit.
Every consent action is audited for accountability.

Usage:
    from uaml.compliance.consent import ConsentManager

    cm = ConsentManager(store)
    cm.grant("client-42", purpose="knowledge_storage", granted_by="client-42")
    cm.check("client-42", purpose="knowledge_storage")  # True
    cm.revoke("client-42", purpose="knowledge_storage")
    cm.check("client-42", purpose="knowledge_storage")  # False
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


class ConsentManager:
    """Manage GDPR consent records."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Ensure consents table exists."""
        self.store.conn.execute("""
            CREATE TABLE IF NOT EXISTS consents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_ref TEXT NOT NULL,
                purpose TEXT NOT NULL,
                granted_at TEXT NOT NULL,
                revoked_at TEXT,
                granted_by TEXT NOT NULL,
                scope TEXT DEFAULT '',
                evidence TEXT DEFAULT '',
                UNIQUE(client_ref, purpose, granted_at)
            )
        """)
        self.store.conn.commit()

    def grant(
        self,
        client_ref: str,
        purpose: str,
        *,
        granted_by: str,
        scope: str = "",
        evidence: str = "",
    ) -> int:
        """Record consent grant.

        Args:
            client_ref: Data subject identifier
            purpose: Processing purpose (e.g., "knowledge_storage")
            granted_by: Who gave consent
            scope: Scope details
            evidence: Reference to consent document/email

        Returns:
            Consent record ID
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = self.store.conn.execute(
            """INSERT INTO consents (client_ref, purpose, granted_at, granted_by, scope, evidence)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (client_ref, purpose, now, granted_by, scope, evidence),
        )
        self.store.conn.commit()

        # Audit
        self.store.learn(
            f"Consent granted: {client_ref} for {purpose} by {granted_by}",
            topic="gdpr", source_type="audit",
            tags="consent,gdpr", data_layer="operational",
        )

        return cursor.lastrowid

    def revoke(self, client_ref: str, purpose: str) -> int:
        """Revoke active consent.

        Returns number of consents revoked.
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = self.store.conn.execute(
            """UPDATE consents SET revoked_at = ?
            WHERE client_ref = ? AND purpose = ? AND revoked_at IS NULL""",
            (now, client_ref, purpose),
        )
        self.store.conn.commit()

        if cursor.rowcount > 0:
            self.store.learn(
                f"Consent revoked: {client_ref} for {purpose}",
                topic="gdpr", source_type="audit",
                tags="consent,gdpr,revocation", data_layer="operational",
            )

        return cursor.rowcount

    def check(self, client_ref: str, purpose: str) -> bool:
        """Check if active consent exists for client+purpose."""
        count = self.store.conn.execute(
            """SELECT COUNT(*) FROM consents
            WHERE client_ref = ? AND purpose = ? AND revoked_at IS NULL""",
            (client_ref, purpose),
        ).fetchone()[0]
        return count > 0

    def list_consents(
        self,
        client_ref: Optional[str] = None,
        *,
        include_revoked: bool = False,
    ) -> list[dict]:
        """List consent records."""
        where = []
        params: list = []

        if client_ref:
            where.append("client_ref = ?")
            params.append(client_ref)

        if not include_revoked:
            where.append("revoked_at IS NULL")

        clause = f"WHERE {' AND '.join(where)}" if where else ""

        rows = self.store.conn.execute(
            f"SELECT * FROM consents {clause} ORDER BY granted_at DESC",
            params,
        ).fetchall()

        return [dict(r) for r in rows]

    def consent_summary(self, client_ref: str) -> dict:
        """Get consent summary for a data subject."""
        active = self.store.conn.execute(
            "SELECT purpose, granted_at, scope FROM consents "
            "WHERE client_ref = ? AND revoked_at IS NULL",
            (client_ref,),
        ).fetchall()

        revoked = self.store.conn.execute(
            "SELECT purpose, granted_at, revoked_at FROM consents "
            "WHERE client_ref = ? AND revoked_at IS NOT NULL",
            (client_ref,),
        ).fetchall()

        return {
            "client_ref": client_ref,
            "active_consents": [dict(r) for r in active],
            "revoked_consents": [dict(r) for r in revoked],
            "active_count": len(active),
            "revoked_count": len(revoked),
        }
