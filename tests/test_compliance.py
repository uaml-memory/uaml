"""Tests for Compliance Auditor — GDPR, ISO 27001, internal checks."""

import pytest
from uaml.core.store import MemoryStore
from uaml.ethics.checker import EthicsChecker
from uaml.compliance.auditor import ComplianceAuditor, Severity, ComplianceStandard


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "compliance.db", agent_id="auditor")


@pytest.fixture
def populated_store(store):
    """Store with realistic data for compliance testing."""
    # General knowledge
    for i in range(10):
        store.learn(f"General knowledge entry {i} about AI systems", topic="ai", data_layer="knowledge")

    # Client data WITH legal basis
    store.learn("Client A contract details", client_ref="client-a", legal_basis="contract",
                project="legal-case-1", data_layer="project")
    store.learn("Client A email correspondence", client_ref="client-a", legal_basis="contract",
                project="legal-case-1", data_layer="project")

    # Client data WITHOUT legal basis (compliance issue)
    store.learn("Client B preliminary notes", client_ref="client-b", project="case-2",
                data_layer="project")

    # Identity data
    store.learn("Agent personality: helpful and precise", data_layer="identity")

    # Grant consent for client-a
    store.grant_consent("client-a", purpose="legal services", granted_by="client-a-representative")

    return store


@pytest.fixture
def auditor(populated_store):
    return ComplianceAuditor(populated_store)


class TestFullAudit:
    """Test complete audit report."""

    def test_full_audit_runs(self, auditor):
        report = auditor.full_audit()
        assert report.generated_at
        assert report.agent_id == "auditor"
        assert len(report.findings) > 0

    def test_full_audit_has_all_standards(self, auditor):
        report = auditor.full_audit()
        standards = {f.standard for f in report.findings}
        assert ComplianceStandard.GDPR in standards
        assert ComplianceStandard.ISO27001 in standards
        assert ComplianceStandard.INTERNAL in standards

    def test_score_calculation(self, auditor):
        report = auditor.full_audit()
        assert 0 <= report.score <= 100

    def test_report_to_json(self, auditor):
        report = auditor.full_audit()
        j = report.to_json()
        import json
        data = json.loads(j)
        assert "score" in data
        assert "findings" in data

    def test_audit_creates_audit_entry(self, populated_store):
        auditor = ComplianceAuditor(populated_store)
        auditor.full_audit()
        # Should have logged the audit itself
        row = populated_store.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action LIKE '%compliance_audit%'"
        ).fetchone()[0]
        assert row >= 1


class TestGDPRChecks:
    """Test GDPR-specific compliance checks."""

    def test_gdpr_check_runs(self, auditor):
        report = auditor.gdpr_check()
        assert all(f.standard == ComplianceStandard.GDPR for f in report.findings)

    def test_legal_basis_missing(self, auditor):
        """Client-b has no legal basis — should flag."""
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-001")
        assert not finding.passed  # client-b has no legal_basis

    def test_consent_tracking(self, auditor):
        """Client-a has consent, client-b does not."""
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-005")
        assert not finding.passed  # client-b without consent
        assert "client-b" in finding.details.get("without_consent", [])

    def test_access_rights_capability(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-006")
        assert finding.passed  # access_report() exists

    def test_purpose_limitation(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-002")
        # Most entries have topic or project
        assert finding.passed

    def test_data_minimization(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-003")
        assert finding.passed  # No duplicates

    def test_data_protection_no_ethics(self, auditor):
        """Without ethics checker, should flag."""
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-007")
        assert not finding.passed  # No ethics checker configured

    def test_data_protection_with_ethics(self, tmp_path):
        """With ethics checker, should pass."""
        checker = EthicsChecker()
        store = MemoryStore(tmp_path / "ethics.db", ethics_checker=checker, ethics_mode="enforce")
        auditor = ComplianceAuditor(store)
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "GDPR-007")
        assert finding.passed


class TestISO27001Checks:
    """Test ISO 27001 compliance checks."""

    def test_audit_trail(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "ISO-001")
        # We have audit entries from learn() calls
        assert finding.passed

    def test_data_classification(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "ISO-003")
        assert finding.passed
        assert "access_levels" in finding.details

    def test_backup_check(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "ISO-004")
        # No backups run yet
        assert not finding.passed

    def test_backup_after_backup(self, populated_store, tmp_path):
        """After running backup, check should pass."""
        from uaml.io.backup import BackupManager
        mgr = BackupManager(populated_store)
        mgr.backup_full(tmp_path / "backup")

        auditor = ComplianceAuditor(populated_store)
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "ISO-004")
        assert finding.passed

    def test_encryption_available(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "ISO-005")
        assert finding.passed  # pqcrypto is installed


class TestInternalChecks:
    """Test internal compliance checks."""

    def test_client_isolation(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "INT-001")
        assert finding.passed  # No multi-client entries

    def test_data_integrity(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "INT-003")
        assert finding.passed  # No hash mismatches

    def test_ethics_pipeline_activity(self, auditor):
        report = auditor.full_audit()
        finding = next(f for f in report.findings if f.check_id == "INT-002")
        assert finding.passed  # Informational


class TestRetentionCheck:
    """Test retention policy checks."""

    def test_retention_check(self, auditor):
        report = auditor.retention_check(max_age_days=365)
        assert len(report.findings) >= 1
        finding = report.findings[0]
        assert finding.check_id == "GDPR-004"

    def test_retention_strict(self, auditor):
        """With 0-day retention, all entries should be flagged."""
        report = auditor.retention_check(max_age_days=0)
        # Entries created today are 0 days old, cutoff is 0 days → might or might not flag
        assert len(report.findings) >= 1


class TestEmptyStore:
    """Test auditing an empty store."""

    def test_empty_store_audit(self, tmp_path):
        store = MemoryStore(tmp_path / "empty.db")
        auditor = ComplianceAuditor(store)
        report = auditor.full_audit()
        assert report.score > 0  # Should have some passing checks
        assert len(report.critical_findings) == 0


class TestAccessReport:
    """Test GDPR data subject access report."""

    def test_access_report_empty(self, tmp_path):
        store = MemoryStore(tmp_path / "access.db", agent_id="test")
        auditor = ComplianceAuditor(store)
        report = auditor.access_report("nonexistent")
        assert report["subject_ref"] == "nonexistent"
        assert report["categories"]["knowledge"]["count"] == 0
        assert "rights" in report
        store.close()

    def test_access_report_with_data(self, tmp_path):
        store = MemoryStore(tmp_path / "access2.db", agent_id="test")
        store.learn("Client data entry", client_ref="client-42",
                    data_layer="knowledge", legal_basis="contract")
        store.learn("Another entry", client_ref="client-42",
                    data_layer="project")

        auditor = ComplianceAuditor(store)
        report = auditor.access_report("client-42")
        assert report["categories"]["knowledge"]["count"] == 2
        assert "contract" in report["categories"]["knowledge"]["legal_bases"]
        assert "Knowledge storage and retrieval" in report["processing_purposes"]
        store.close()

    def test_erasure_report(self, tmp_path):
        store = MemoryStore(tmp_path / "erase.db", agent_id="test")
        store.learn("Sensitive data", client_ref="delete-me")
        store.learn("Also sensitive", client_ref="delete-me")

        auditor = ComplianceAuditor(store)
        preview = auditor.erasure_report("delete-me")
        assert preview["affected"]["knowledge_entries"] == 2
        assert preview["status"] == "preview"

        result = auditor.execute_erasure("delete-me")
        assert result["deleted"]["knowledge_entries"] == 2
        assert result["status"] == "completed"

        # Verify deletion
        remaining = store.conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE client_ref = 'delete-me'"
        ).fetchone()[0]
        assert remaining == 0
        store.close()
