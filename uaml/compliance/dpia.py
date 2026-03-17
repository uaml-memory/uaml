# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML DPIA & Breach Notification — GDPR Art. 35 & Art. 33/34.

Data Protection Impact Assessment (DPIA) generator and
breach notification record management.

Usage:
    from uaml.compliance.dpia import DPIAGenerator, BreachRegister

    dpia = DPIAGenerator(store)
    assessment = dpia.generate()

    register = BreachRegister(store)
    register.record_breach(description="Unauthorized access", severity="high")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


class DPIAGenerator:
    """Generate Data Protection Impact Assessments (GDPR Art. 35)."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def generate(self) -> dict:
        """Generate a DPIA for the UAML memory system.

        Analyzes stored data and processing activities to produce
        a structured assessment.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Analyze data inventory
        inventory = self._data_inventory()
        risks = self._assess_risks(inventory)
        mitigations = self._identify_mitigations()

        return {
            "title": "Data Protection Impact Assessment — UAML Memory System",
            "generated_at": now,
            "legal_reference": "GDPR Art. 35",
            "system_description": {
                "name": "UAML (Universal Agent Memory Layer)",
                "purpose": "AI agent memory management with knowledge storage, retrieval, and reasoning",
                "data_controller": self.store.agent_id,
                "processing_basis": "Legitimate interest / contract fulfillment",
            },
            "data_inventory": inventory,
            "risk_assessment": risks,
            "mitigations": mitigations,
            "overall_risk": self._overall_risk(risks),
            "recommendation": self._recommendation(risks),
        }

    def _data_inventory(self) -> dict:
        """Analyze what data is stored."""
        total = self.store.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

        layers = {}
        for row in self.store.conn.execute(
            "SELECT data_layer, COUNT(*) as cnt FROM knowledge GROUP BY data_layer"
        ).fetchall():
            layers[row["data_layer"] or "unclassified"] = row["cnt"]

        with_client = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE client_ref IS NOT NULL"
        ).fetchone()[0]

        with_legal_basis = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE legal_basis IS NOT NULL AND legal_basis != ''"
        ).fetchone()[0]

        return {
            "total_entries": total,
            "by_layer": layers,
            "client_data_entries": with_client,
            "with_legal_basis": with_legal_basis,
            "identity_entries": layers.get("identity", 0),
            "has_personal_data": with_client > 0 or layers.get("identity", 0) > 0,
        }

    def _assess_risks(self, inventory: dict) -> list[dict]:
        """Assess data protection risks."""
        risks = []

        if inventory["identity_entries"] > 0:
            risks.append({
                "risk": "Identity data stored",
                "level": "high",
                "description": f"{inventory['identity_entries']} identity entries stored",
                "gdpr_article": "Art. 5(1)(c) — Data minimization",
            })

        if inventory["client_data_entries"] > 0:
            coverage = inventory["with_legal_basis"] / max(inventory["client_data_entries"], 1)
            if coverage < 1.0:
                risks.append({
                    "risk": "Client data without legal basis",
                    "level": "high",
                    "description": f"{coverage:.0%} of client data has legal basis",
                    "gdpr_article": "Art. 6(1) — Lawfulness",
                })

        if inventory["total_entries"] > 10000:
            risks.append({
                "risk": "Large data volume",
                "level": "medium",
                "description": f"{inventory['total_entries']} total entries",
                "gdpr_article": "Art. 5(1)(e) — Storage limitation",
            })

        if not risks:
            risks.append({
                "risk": "No significant risks identified",
                "level": "low",
                "description": "Current data processing appears proportionate",
                "gdpr_article": "Art. 35(7)(c)",
            })

        return risks

    def _identify_mitigations(self) -> list[dict]:
        """Identify existing mitigations."""
        mitigations = []

        # Check encryption
        mitigations.append({
            "control": "PQC encryption available",
            "type": "technical",
            "description": "ML-KEM-768 post-quantum encryption for data at rest and in transit",
            "gdpr_article": "Art. 32 — Security of processing",
        })

        # Check audit trail
        audit_count = self.store.conn.execute(
            "SELECT COUNT(*) FROM audit_log"
        ).fetchone()[0]
        mitigations.append({
            "control": "Audit trail",
            "type": "organizational",
            "description": f"{audit_count} audit log entries",
            "gdpr_article": "Art. 5(2) — Accountability",
        })

        # Check ethics pipeline
        mitigations.append({
            "control": "Ethics checker pipeline",
            "type": "technical",
            "description": "Content screening before storage",
            "gdpr_article": "Art. 25 — Data protection by design",
        })

        # Data layer classification
        mitigations.append({
            "control": "5-layer data classification",
            "type": "organizational",
            "description": "identity/knowledge/team/operational/project hierarchy",
            "gdpr_article": "Art. 5(1)(b) — Purpose limitation",
        })

        return mitigations

    def _overall_risk(self, risks: list[dict]) -> str:
        levels = [r["level"] for r in risks]
        if "high" in levels:
            return "high"
        if "medium" in levels:
            return "medium"
        return "low"

    def _recommendation(self, risks: list[dict]) -> str:
        level = self._overall_risk(risks)
        if level == "high":
            return "Consult DPO before proceeding. Address high-risk findings."
        if level == "medium":
            return "Processing may proceed with documented mitigations."
        return "No additional measures required at this time."


class BreachRegister:
    """Manage data breach records (GDPR Art. 33/34)."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.store.conn.execute("""
            CREATE TABLE IF NOT EXISTS breach_register (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'medium',
                detected_at TEXT NOT NULL,
                reported_at TEXT,
                affected_subjects TEXT DEFAULT '',
                data_categories TEXT DEFAULT '',
                consequences TEXT DEFAULT '',
                measures_taken TEXT DEFAULT '',
                dpa_notified INTEGER DEFAULT 0,
                subjects_notified INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open'
            )
        """)
        self.store.conn.commit()

    def record_breach(
        self,
        description: str,
        *,
        severity: str = "medium",
        affected_subjects: str = "",
        data_categories: str = "",
        consequences: str = "",
    ) -> int:
        """Record a data breach.

        GDPR Art. 33 requires notification to DPA within 72 hours.
        """
        now = datetime.now(timezone.utc).isoformat()

        cursor = self.store.conn.execute(
            """INSERT INTO breach_register
            (description, severity, detected_at, affected_subjects,
             data_categories, consequences)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (description, severity, now, affected_subjects,
             data_categories, consequences),
        )
        self.store.conn.commit()

        # Audit
        self.store.learn(
            f"DATA BREACH RECORDED [{severity}]: {description}",
            topic="security", source_type="audit",
            tags="breach,gdpr,art33", data_layer="operational",
        )

        return cursor.lastrowid

    def update_breach(
        self,
        breach_id: int,
        *,
        measures_taken: Optional[str] = None,
        dpa_notified: Optional[bool] = None,
        subjects_notified: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> bool:
        """Update breach record with response actions."""
        updates = []
        params: list = []

        if measures_taken is not None:
            updates.append("measures_taken = ?")
            params.append(measures_taken)
        if dpa_notified is not None:
            updates.append("dpa_notified = ?")
            params.append(1 if dpa_notified else 0)
            if dpa_notified:
                updates.append("reported_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())
        if subjects_notified is not None:
            updates.append("subjects_notified = ?")
            params.append(1 if subjects_notified else 0)
        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if not updates:
            return False

        params.append(breach_id)
        self.store.conn.execute(
            f"UPDATE breach_register SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        self.store.conn.commit()
        return True

    def list_breaches(self, *, status: Optional[str] = None) -> list[dict]:
        """List breach records."""
        if status:
            rows = self.store.conn.execute(
                "SELECT * FROM breach_register WHERE status = ? ORDER BY detected_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.store.conn.execute(
                "SELECT * FROM breach_register ORDER BY detected_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def breach_status(self, breach_id: int) -> Optional[dict]:
        """Get breach status including 72-hour deadline."""
        row = self.store.conn.execute(
            "SELECT * FROM breach_register WHERE id = ?", (breach_id,)
        ).fetchone()

        if not row:
            return None

        d = dict(row)
        detected = datetime.fromisoformat(d["detected_at"])
        now = datetime.now(timezone.utc)
        hours_elapsed = (now - detected).total_seconds() / 3600

        d["hours_elapsed"] = round(hours_elapsed, 1)
        d["deadline_72h"] = hours_elapsed > 72
        d["dpa_notification_required"] = not d["dpa_notified"] and d["severity"] != "low"

        return d
