# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Compliance Auditor — automated compliance checks and reporting.

Supports:
- GDPR Art. 5/6/7/15/17/25/30/35 compliance checks
- ISO 27001 Annex A control mapping
- Retention policy enforcement
- Data protection impact assessment (DPIA) templates
- Audit trail integrity verification

Usage:
    from uaml.compliance import ComplianceAuditor

    auditor = ComplianceAuditor(store)
    report = auditor.full_audit()
    report = auditor.gdpr_check()
    report = auditor.retention_check()
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from uaml.core.store import MemoryStore


class Severity(str, Enum):
    CRITICAL = "critical"   # Must fix immediately
    HIGH = "high"           # Fix within 24h
    MEDIUM = "medium"       # Fix within 1 week
    LOW = "low"             # Advisory
    INFO = "info"           # Informational


class ComplianceStandard(str, Enum):
    GDPR = "GDPR"
    ISO27001 = "ISO 27001"
    INTERNAL = "Internal"


@dataclass
class Finding:
    """A single compliance finding."""
    check_id: str
    title: str
    description: str
    severity: Severity
    standard: ComplianceStandard
    article: str = ""         # e.g. "Art. 5(1)(e)" for GDPR
    control: str = ""         # e.g. "A.8.10" for ISO 27001
    passed: bool = False
    details: dict = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "severity": self.severity.value,
            "standard": self.standard.value,
            "article": self.article,
            "control": self.control,
            "passed": self.passed,
            "description": self.description,
            "recommendation": self.recommendation,
            "details": self.details,
        }


@dataclass
class AuditReport:
    """Complete compliance audit report."""
    generated_at: str
    agent_id: str
    findings: list[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(1 for f in self.findings if f.passed)

    @property
    def failed(self) -> int:
        return sum(1 for f in self.findings if not f.passed)

    @property
    def critical_findings(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.severity == Severity.CRITICAL]

    @property
    def score(self) -> float:
        """Compliance score 0-100."""
        if not self.findings:
            return 0.0
        return round(self.passed / len(self.findings) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "agent_id": self.agent_id,
            "score": self.score,
            "passed": self.passed,
            "failed": self.failed,
            "total_checks": len(self.findings),
            "critical_issues": len(self.critical_findings),
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)


class ComplianceAuditor:
    """Automated compliance auditor for UAML memory stores.

    Runs checks against GDPR, ISO 27001, and internal policies.
    Produces actionable findings with severity and recommendations.
    """

    def __init__(self, store: MemoryStore):
        self.store = store

    def full_audit(self) -> AuditReport:
        """Run all compliance checks. Returns comprehensive report."""
        now = datetime.now(timezone.utc).isoformat()
        report = AuditReport(
            generated_at=now,
            agent_id=self.store.agent_id,
        )

        # GDPR checks
        report.findings.extend(self._check_gdpr_lawfulness())
        report.findings.extend(self._check_gdpr_purpose_limitation())
        report.findings.extend(self._check_gdpr_data_minimization())
        report.findings.extend(self._check_gdpr_storage_limitation())
        report.findings.extend(self._check_gdpr_consent_tracking())
        report.findings.extend(self._check_gdpr_access_rights())
        report.findings.extend(self._check_gdpr_data_protection())

        # ISO 27001 checks
        report.findings.extend(self._check_iso_audit_trail())
        report.findings.extend(self._check_iso_access_control())
        report.findings.extend(self._check_iso_data_classification())
        report.findings.extend(self._check_iso_backup())
        report.findings.extend(self._check_iso_encryption())

        # Internal checks
        report.findings.extend(self._check_client_isolation())
        report.findings.extend(self._check_ethics_pipeline())
        report.findings.extend(self._check_data_integrity())

        # Summary
        report.summary = {
            "gdpr": {
                "checks": len([f for f in report.findings if f.standard == ComplianceStandard.GDPR]),
                "passed": len([f for f in report.findings if f.standard == ComplianceStandard.GDPR and f.passed]),
            },
            "iso27001": {
                "checks": len([f for f in report.findings if f.standard == ComplianceStandard.ISO27001]),
                "passed": len([f for f in report.findings if f.standard == ComplianceStandard.ISO27001 and f.passed]),
            },
            "internal": {
                "checks": len([f for f in report.findings if f.standard == ComplianceStandard.INTERNAL]),
                "passed": len([f for f in report.findings if f.standard == ComplianceStandard.INTERNAL and f.passed]),
            },
        }

        # Audit the audit
        self.store._audit(
            "compliance_audit", "system", 0, self.store.agent_id,
            details=f"score={report.score}, findings={len(report.findings)}, "
                    f"critical={len(report.critical_findings)}",
        )

        return report

    def gdpr_check(self) -> AuditReport:
        """Run GDPR-specific checks only."""
        now = datetime.now(timezone.utc).isoformat()
        report = AuditReport(generated_at=now, agent_id=self.store.agent_id)
        report.findings.extend(self._check_gdpr_lawfulness())
        report.findings.extend(self._check_gdpr_purpose_limitation())
        report.findings.extend(self._check_gdpr_data_minimization())
        report.findings.extend(self._check_gdpr_storage_limitation())
        report.findings.extend(self._check_gdpr_consent_tracking())
        report.findings.extend(self._check_gdpr_access_rights())
        report.findings.extend(self._check_gdpr_data_protection())
        return report

    def retention_check(self, max_age_days: int = 365) -> AuditReport:
        """Check data retention compliance."""
        now = datetime.now(timezone.utc).isoformat()
        report = AuditReport(generated_at=now, agent_id=self.store.agent_id)
        report.findings.extend(self._check_gdpr_storage_limitation(max_age_days))
        return report

    # ── GDPR Checks ──────────────────────────────────────────

    def _check_gdpr_lawfulness(self) -> list[Finding]:
        """GDPR Art. 6 — Lawfulness of processing (legal basis)."""
        findings = []

        # Check if entries have legal_basis
        total = self.store.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        with_basis = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE legal_basis IS NOT NULL AND legal_basis != ''"
        ).fetchone()[0]

        # For client data, legal basis is required
        client_entries = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE client_ref IS NOT NULL"
        ).fetchone()[0]
        client_with_basis = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE client_ref IS NOT NULL "
            "AND legal_basis IS NOT NULL AND legal_basis != ''"
        ).fetchone()[0]

        findings.append(Finding(
            check_id="GDPR-001",
            title="Legal basis for client data processing",
            description=f"{client_with_basis}/{client_entries} client entries have legal_basis set",
            severity=Severity.HIGH if client_entries > 0 and client_with_basis < client_entries else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 6(1)",
            passed=client_entries == 0 or client_with_basis == client_entries,
            details={"total": total, "with_basis": with_basis,
                     "client_entries": client_entries, "client_with_basis": client_with_basis},
            recommendation="Set legal_basis on all client-related entries (consent, contract, legal_obligation, etc.)",
        ))

        return findings

    def _check_gdpr_purpose_limitation(self) -> list[Finding]:
        """GDPR Art. 5(1)(b) — Purpose limitation."""
        findings = []

        # Check if entries have topic/project (purpose indicator)
        total = self.store.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        with_purpose = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE "
            "(topic IS NOT NULL AND topic != '') OR (project IS NOT NULL AND project != '')"
        ).fetchone()[0]

        ratio = with_purpose / total if total > 0 else 1.0
        findings.append(Finding(
            check_id="GDPR-002",
            title="Purpose limitation — entries categorized",
            description=f"{with_purpose}/{total} entries have topic or project ({ratio*100:.0f}%)",
            severity=Severity.MEDIUM if ratio < 0.5 else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 5(1)(b)",
            passed=ratio >= 0.5,
            details={"total": total, "with_purpose": with_purpose, "ratio": round(ratio, 3)},
            recommendation="Assign topic/project to entries to demonstrate purpose limitation",
        ))

        return findings

    def _check_gdpr_data_minimization(self) -> list[Finding]:
        """GDPR Art. 5(1)(c) — Data minimization."""
        findings = []

        # Check for potential over-collection (very large entries, duplicates)
        large_entries = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE LENGTH(content) > 10000"
        ).fetchone()[0]

        # Check dedup effectiveness
        total = self.store.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        unique = self.store.conn.execute(
            "SELECT COUNT(DISTINCT content_hash) FROM knowledge WHERE content_hash IS NOT NULL"
        ).fetchone()[0]
        dup_count = total - unique if total > unique else 0

        findings.append(Finding(
            check_id="GDPR-003",
            title="Data minimization — deduplication",
            description=f"{dup_count} potential duplicate entries detected",
            severity=Severity.LOW if dup_count > 0 else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 5(1)(c)",
            passed=dup_count == 0,
            details={"total": total, "unique_hashes": unique, "duplicates": dup_count,
                     "large_entries": large_entries},
            recommendation="Run dedup cleanup to remove duplicate entries" if dup_count > 0 else "",
        ))

        return findings

    def _check_gdpr_storage_limitation(self, max_age_days: int = 365) -> list[Finding]:
        """GDPR Art. 5(1)(e) — Storage limitation."""
        findings = []

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        old_entries = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE created_at < ? AND valid_until IS NULL",
            (cutoff,),
        ).fetchone()[0]

        # Check entries with explicit expiry
        expired = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE valid_until IS NOT NULL AND valid_until < ?",
            (datetime.now(timezone.utc).isoformat(),),
        ).fetchone()[0]

        findings.append(Finding(
            check_id="GDPR-004",
            title=f"Storage limitation — entries older than {max_age_days} days",
            description=f"{old_entries} entries older than {max_age_days} days without expiry",
            severity=Severity.MEDIUM if old_entries > 100 else Severity.LOW if old_entries > 0 else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 5(1)(e)",
            passed=old_entries == 0,
            details={"old_entries": old_entries, "expired": expired, "max_age_days": max_age_days},
            recommendation="Review old entries and set valid_until or archive them",
        ))

        if expired > 0:
            findings.append(Finding(
                check_id="GDPR-004b",
                title="Expired entries pending deletion",
                description=f"{expired} entries past their valid_until date",
                severity=Severity.HIGH,
                standard=ComplianceStandard.GDPR,
                article="Art. 5(1)(e)",
                passed=False,
                details={"expired": expired},
                recommendation="Delete or archive expired entries immediately",
            ))

        return findings

    def _check_gdpr_consent_tracking(self) -> list[Finding]:
        """GDPR Art. 7 — Consent management."""
        findings = []

        # Check if consents table has entries for clients that have data
        clients_with_data = self.store.conn.execute(
            "SELECT DISTINCT client_ref FROM knowledge WHERE client_ref IS NOT NULL"
        ).fetchall()
        client_refs = [r[0] for r in clients_with_data]

        clients_without_consent = []
        for cr in client_refs:
            consent = self.store.conn.execute(
                "SELECT COUNT(*) FROM consents WHERE client_ref = ? AND revoked_at IS NULL",
                (cr,),
            ).fetchone()[0]
            if consent == 0:
                clients_without_consent.append(cr)

        findings.append(Finding(
            check_id="GDPR-005",
            title="Consent tracking for client data",
            description=f"{len(clients_without_consent)}/{len(client_refs)} clients without active consent",
            severity=Severity.HIGH if clients_without_consent else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 7",
            passed=len(clients_without_consent) == 0,
            details={"clients_total": len(client_refs),
                     "without_consent": clients_without_consent[:10]},
            recommendation="Record consent for all clients or establish alternative legal basis",
        ))

        return findings

    def _check_gdpr_access_rights(self) -> list[Finding]:
        """GDPR Art. 15 — Right of access."""
        findings = []

        # Check if access_report function works (we have it in MemoryStore)
        has_method = hasattr(self.store, 'access_report')

        findings.append(Finding(
            check_id="GDPR-006",
            title="Subject access request capability",
            description="access_report() method available for GDPR Art. 15 requests",
            severity=Severity.CRITICAL if not has_method else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 15",
            passed=has_method,
            recommendation="Implement access_report(client_ref) for subject access requests",
        ))

        return findings

    def _check_gdpr_data_protection(self) -> list[Finding]:
        """GDPR Art. 25 — Data protection by design."""
        findings = []

        # Check if ethics checker is configured
        has_ethics = self.store._ethics is not None

        findings.append(Finding(
            check_id="GDPR-007",
            title="Data protection by design — ethics pipeline",
            description="Ethics checker " + ("active" if has_ethics else "NOT configured"),
            severity=Severity.HIGH if not has_ethics else Severity.INFO,
            standard=ComplianceStandard.GDPR,
            article="Art. 25",
            passed=has_ethics,
            details={"ethics_mode": self.store._ethics_mode},
            recommendation="Enable ethics checker: MemoryStore(ethics_checker=EthicsChecker(), ethics_mode='enforce')",
        ))

        return findings

    # ── ISO 27001 Checks ─────────────────────────────────────

    def _check_iso_audit_trail(self) -> list[Finding]:
        """ISO 27001 A.8.15 — Logging and monitoring."""
        findings = []

        audit_count = self.store.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        knowledge_count = self.store.conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

        # Audit entries should be >= knowledge entries (each learn = 1 audit)
        ratio = audit_count / knowledge_count if knowledge_count > 0 else 1.0

        findings.append(Finding(
            check_id="ISO-001",
            title="Audit trail completeness",
            description=f"{audit_count} audit entries for {knowledge_count} knowledge entries (ratio: {ratio:.2f})",
            severity=Severity.HIGH if ratio < 0.5 else Severity.INFO,
            standard=ComplianceStandard.ISO27001,
            control="A.8.15",
            passed=ratio >= 0.8,
            details={"audit_count": audit_count, "knowledge_count": knowledge_count, "ratio": round(ratio, 3)},
            recommendation="Ensure all data operations are audited",
        ))

        return findings

    def _check_iso_access_control(self) -> list[Finding]:
        """ISO 27001 A.8.3 — Information access restriction."""
        findings = []

        # Check data layer distribution (identity should be small + protected)
        layers = {}
        rows = self.store.conn.execute(
            "SELECT COALESCE(data_layer, 'knowledge') as layer, COUNT(*) as cnt "
            "FROM knowledge GROUP BY layer"
        ).fetchall()
        for r in rows:
            layers[r[0]] = r[1]

        identity_count = layers.get("identity", 0)
        total = sum(layers.values())

        findings.append(Finding(
            check_id="ISO-002",
            title="Data classification — layer distribution",
            description=f"Identity: {identity_count}, Total: {total}",
            severity=Severity.INFO,
            standard=ComplianceStandard.ISO27001,
            control="A.8.3",
            passed=True,
            details={"layers": layers},
        ))

        return findings

    def _check_iso_data_classification(self) -> list[Finding]:
        """ISO 27001 A.8.2 — Information classification."""
        findings = []

        # Check access_level distribution
        rows = self.store.conn.execute(
            "SELECT COALESCE(access_level, 'internal') as level, COUNT(*) as cnt "
            "FROM knowledge GROUP BY level"
        ).fetchall()
        levels = {r[0]: r[1] for r in rows}

        findings.append(Finding(
            check_id="ISO-003",
            title="Data classification labels",
            description=f"Access levels: {levels}",
            severity=Severity.INFO,
            standard=ComplianceStandard.ISO27001,
            control="A.8.2",
            passed=True,
            details={"access_levels": levels},
        ))

        return findings

    def _check_iso_backup(self) -> list[Finding]:
        """ISO 27001 A.8.13 — Information backup."""
        findings = []

        # Check if any backup audit entries exist
        backup_entries = self.store.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action LIKE '%backup%'"
        ).fetchone()[0]

        findings.append(Finding(
            check_id="ISO-004",
            title="Backup operations recorded",
            description=f"{backup_entries} backup operations in audit log",
            severity=Severity.HIGH if backup_entries == 0 else Severity.INFO,
            standard=ComplianceStandard.ISO27001,
            control="A.8.13",
            passed=backup_entries > 0,
            details={"backup_audit_entries": backup_entries},
            recommendation="Run regular backups: uaml backup run --target /path/to/backup",
        ))

        return findings

    def _check_iso_encryption(self) -> list[Finding]:
        """ISO 27001 A.8.24 — Use of cryptography."""
        findings = []

        # Check if PQC module is available
        try:
            from uaml.crypto import PQCKeyPair
            pqc_available = True
        except ImportError:
            pqc_available = False

        findings.append(Finding(
            check_id="ISO-005",
            title="Post-quantum cryptography available",
            description=f"PQC module: {'available (ML-KEM-768)' if pqc_available else 'NOT available'}",
            severity=Severity.MEDIUM if not pqc_available else Severity.INFO,
            standard=ComplianceStandard.ISO27001,
            control="A.8.24",
            passed=pqc_available,
            recommendation="Install pqcrypto: pip install pqcrypto" if not pqc_available else "",
        ))

        return findings

    # ── Internal Checks ──────────────────────────────────────

    def _check_client_isolation(self) -> list[Finding]:
        """Internal — verify client data isolation."""
        findings = []

        # Check for entries with multiple client_refs (should not exist)
        multi_client = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE client_ref LIKE '%,%'"
        ).fetchone()[0]

        findings.append(Finding(
            check_id="INT-001",
            title="Client data isolation",
            description=f"{multi_client} entries with multiple client references",
            severity=Severity.CRITICAL if multi_client > 0 else Severity.INFO,
            standard=ComplianceStandard.INTERNAL,
            passed=multi_client == 0,
            details={"multi_client_entries": multi_client},
            recommendation="Each entry must belong to exactly one client (or none)",
        ))

        return findings

    def _check_ethics_pipeline(self) -> list[Finding]:
        """Internal — ethics pipeline status."""
        findings = []

        # Check for rejected entries in audit log
        rejected = self.store.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action LIKE '%ethics_rejected%'"
        ).fetchone()[0]
        flagged = self.store.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action LIKE '%ethics_flagged%'"
        ).fetchone()[0]

        findings.append(Finding(
            check_id="INT-002",
            title="Ethics pipeline activity",
            description=f"Rejected: {rejected}, Flagged: {flagged}",
            severity=Severity.INFO,
            standard=ComplianceStandard.INTERNAL,
            passed=True,
            details={"rejected": rejected, "flagged": flagged},
        ))

        return findings

    def _check_data_integrity(self) -> list[Finding]:
        """Internal — verify content hash integrity."""
        findings = []

        # Sample check: verify content_hash matches content
        rows = self.store.conn.execute(
            "SELECT id, content, content_hash FROM knowledge "
            "WHERE content_hash IS NOT NULL LIMIT 100"
        ).fetchall()

        mismatches = 0
        for r in rows:
            expected = hashlib.sha256(r[1].encode()).hexdigest()[:32]
            if r[2] != expected:
                mismatches += 1

        findings.append(Finding(
            check_id="INT-003",
            title="Content hash integrity",
            description=f"Checked {len(rows)} entries, {mismatches} hash mismatches",
            severity=Severity.CRITICAL if mismatches > 0 else Severity.INFO,
            standard=ComplianceStandard.INTERNAL,
            passed=mismatches == 0,
            details={"checked": len(rows), "mismatches": mismatches},
            recommendation="Re-hash corrupted entries or investigate tampering" if mismatches > 0 else "",
        ))

        return findings

    # ─── GDPR Data Subject Access Reports ────────────────────────

    def access_report(
        self,
        subject_ref: str,
        *,
        include_audit: bool = True,
    ) -> dict:
        """Generate GDPR Art. 15 data subject access report.

        Returns all data associated with a subject identifier (client_ref,
        agent_id, or content mention).
        """
        from datetime import datetime, timezone

        report = {
            "report_type": "GDPR Art. 15 — Data Subject Access Report",
            "subject_ref": subject_ref,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "categories": {},
        }

        # Knowledge entries
        knowledge = self.store.conn.execute(
            "SELECT id, content, topic, summary, source_type, source_ref, tags, "
            "confidence, legal_basis, data_layer, created_at, updated_at "
            "FROM knowledge WHERE client_ref = ? OR agent_id = ?",
            (subject_ref, subject_ref),
        ).fetchall()

        report["categories"]["knowledge"] = {
            "count": len(knowledge),
            "entries": [dict(r) for r in knowledge],
            "legal_bases": list(set(
                r["legal_basis"] for r in knowledge
                if r["legal_basis"]
            )),
        }

        # Tasks
        task_check = self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if task_check:
            tasks = self.store.conn.execute(
                "SELECT id, title, description, status, project, assigned_to, "
                "created_at, updated_at FROM tasks "
                "WHERE assigned_to = ? OR project = ?",
                (subject_ref, subject_ref),
            ).fetchall()
            report["categories"]["tasks"] = {
                "count": len(tasks),
                "entries": [dict(r) for r in tasks],
            }

        # Audit trail
        if include_audit:
            audit_check = self.store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
            ).fetchone()
            if audit_check:
                audit = self.store.conn.execute(
                    "SELECT * FROM audit_log WHERE details LIKE ? "
                    "ORDER BY ts DESC LIMIT 100",
                    (f"%{subject_ref}%",),
                ).fetchall()
                report["categories"]["audit_trail"] = {
                    "count": len(audit),
                    "entries": [dict(r) for r in audit],
                }

        # Processing purposes
        purposes = set()
        for entry in knowledge:
            layer = entry["data_layer"] or ""
            if layer == "knowledge":
                purposes.add("Knowledge storage and retrieval")
            elif layer == "operational":
                purposes.add("Operational logging and audit")
            elif layer == "team":
                purposes.add("Team collaboration")
            elif layer == "project":
                purposes.add("Project delivery")
        report["processing_purposes"] = sorted(purposes)

        # Retention info
        created_dates = [r["created_at"] for r in knowledge if r["created_at"]]
        report["retention"] = {
            "oldest_entry": min(created_dates, default=None),
            "newest_entry": max(created_dates, default=None),
            "total_entries": len(knowledge),
        }

        # Data subject rights reminder
        report["rights"] = {
            "rectification": "Art. 16 — Right to rectification",
            "erasure": "Art. 17 — Right to erasure ('right to be forgotten')",
            "restriction": "Art. 18 — Right to restriction of processing",
            "portability": "Art. 20 — Right to data portability",
            "objection": "Art. 21 — Right to object",
        }

        return report

    def erasure_report(self, subject_ref: str) -> dict:
        """GDPR Art. 17 — preview what would be deleted."""
        from datetime import datetime, timezone

        count = self.store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE client_ref = ?",
            (subject_ref,),
        ).fetchone()[0]

        return {
            "report_type": "GDPR Art. 17 — Erasure Impact Report",
            "subject_ref": subject_ref,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "affected": {"knowledge_entries": count},
            "status": "preview",
        }

    def execute_erasure(self, subject_ref: str) -> dict:
        """Execute GDPR Art. 17 erasure — DESTRUCTIVE."""
        from datetime import datetime, timezone

        deleted = self.store.conn.execute(
            "DELETE FROM knowledge WHERE client_ref = ?",
            (subject_ref,),
        ).rowcount
        self.store.conn.commit()

        self.store.learn(
            f"GDPR Art. 17 erasure executed for: {subject_ref}. Deleted {deleted} entries.",
            topic="gdpr", source_type="audit",
            tags="gdpr,erasure", data_layer="operational",
        )

        return {
            "report_type": "GDPR Art. 17 — Erasure Execution",
            "subject_ref": subject_ref,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "deleted": {"knowledge_entries": deleted},
            "status": "completed",
        }
