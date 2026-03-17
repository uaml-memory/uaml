# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Data Inventory — GDPR Art. 30 records of processing activities.

Catalogs all data types, purposes, legal bases, and retention periods
for compliance reporting.

Usage:
    from uaml.compliance.inventory import DataInventory

    inv = DataInventory(store)
    inv.register_activity("knowledge_storage", purpose="AI memory",
                          legal_basis="legitimate_interest")
    report = inv.generate_report()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class ProcessingActivity:
    """A registered data processing activity."""
    id: int
    name: str
    purpose: str
    legal_basis: str
    data_categories: list[str]
    retention_days: int
    recipients: list[str]
    transfers_outside_eu: bool
    registered_at: str


class DataInventory:
    """GDPR Article 30 data processing inventory."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self):
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS data_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                purpose TEXT NOT NULL,
                legal_basis TEXT NOT NULL,
                data_categories TEXT DEFAULT '[]',
                retention_days INTEGER DEFAULT 365,
                recipients TEXT DEFAULT '[]',
                transfers_outside_eu INTEGER DEFAULT 0,
                registered_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
            )
        """)
        self.store._conn.commit()

    def register_activity(
        self,
        name: str,
        purpose: str,
        legal_basis: str,
        *,
        data_categories: Optional[list[str]] = None,
        retention_days: int = 365,
        recipients: Optional[list[str]] = None,
        transfers_outside_eu: bool = False,
    ) -> int:
        """Register a processing activity."""
        import json
        cursor = self.store._conn.execute(
            """INSERT OR REPLACE INTO data_inventory
               (name, purpose, legal_basis, data_categories, retention_days,
                recipients, transfers_outside_eu)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name, purpose, legal_basis,
                json.dumps(data_categories or []),
                retention_days,
                json.dumps(recipients or []),
                int(transfers_outside_eu),
            ),
        )
        self.store._conn.commit()
        return cursor.lastrowid

    def list_activities(self) -> list[ProcessingActivity]:
        """List all registered activities."""
        import json
        rows = self.store._conn.execute(
            "SELECT * FROM data_inventory ORDER BY name"
        ).fetchall()

        return [
            ProcessingActivity(
                id=r["id"],
                name=r["name"],
                purpose=r["purpose"],
                legal_basis=r["legal_basis"],
                data_categories=json.loads(r["data_categories"]),
                retention_days=r["retention_days"],
                recipients=json.loads(r["recipients"]),
                transfers_outside_eu=bool(r["transfers_outside_eu"]),
                registered_at=r["registered_at"],
            )
            for r in rows
        ]

    def remove_activity(self, name: str) -> bool:
        """Remove a processing activity."""
        cursor = self.store._conn.execute(
            "DELETE FROM data_inventory WHERE name = ?", (name,)
        )
        self.store._conn.commit()
        return cursor.rowcount > 0

    def generate_report(self) -> dict:
        """Generate GDPR Art. 30 compliance report."""
        activities = self.list_activities()

        from collections import Counter
        bases = Counter(a.legal_basis for a in activities)
        eu_transfers = sum(1 for a in activities if a.transfers_outside_eu)

        return {
            "title": "Records of Processing Activities (GDPR Art. 30)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_activities": len(activities),
            "legal_bases": dict(bases),
            "eu_transfers": eu_transfers,
            "activities": [
                {
                    "name": a.name,
                    "purpose": a.purpose,
                    "legal_basis": a.legal_basis,
                    "data_categories": a.data_categories,
                    "retention_days": a.retention_days,
                    "recipients": a.recipients,
                    "transfers_outside_eu": a.transfers_outside_eu,
                }
                for a in activities
            ],
        }

    def check_compliance(self) -> list[str]:
        """Check for compliance issues."""
        issues = []
        activities = self.list_activities()

        if not activities:
            issues.append("No processing activities registered (GDPR Art. 30 requires records)")

        for a in activities:
            if not a.purpose:
                issues.append(f"Activity '{a.name}' missing purpose")
            if not a.legal_basis:
                issues.append(f"Activity '{a.name}' missing legal basis")
            if a.transfers_outside_eu and not a.recipients:
                issues.append(f"Activity '{a.name}' has EU transfers but no recipients listed")

        return issues
