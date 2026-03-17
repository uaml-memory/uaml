"""Tests for UAML GDPR compliance features."""

import pytest

from uaml.core.store import MemoryStore
from uaml.core.models import LegalBasis


@pytest.fixture
def store():
    s = MemoryStore(":memory:", agent_id="test-agent")
    return s


class TestLegalBasis:
    def test_learn_with_legal_basis(self, store):
        entry_id = store.learn(
            "Client A prefers email communication",
            topic="preferences",
            client_ref="client-a",
            legal_basis="consent",
            consent_ref="consent-001",
        )
        row = store.conn.execute(
            "SELECT legal_basis, consent_ref FROM knowledge WHERE id = ?",
            (entry_id,),
        ).fetchone()
        assert row["legal_basis"] == "consent"
        assert row["consent_ref"] == "consent-001"

    def test_learn_without_legal_basis(self, store):
        entry_id = store.learn("General knowledge", topic="general")
        row = store.conn.execute(
            "SELECT legal_basis FROM knowledge WHERE id = ?",
            (entry_id,),
        ).fetchone()
        assert row["legal_basis"] is None

    def test_legal_basis_enum(self):
        assert LegalBasis.CONSENT.value == "consent"
        assert LegalBasis.CONTRACT.value == "contract"
        assert LegalBasis.LEGITIMATE_INTEREST.value == "legitimate_interest"


class TestConsent:
    def test_grant_consent(self, store):
        consent_id = store.grant_consent(
            client_ref="client-a",
            purpose="Knowledge storage for legal advisory",
            granted_by="Pavel Zamazal",
            evidence="email-2026-03-08",
        )
        assert consent_id > 0

    def test_list_consents(self, store):
        store.grant_consent("client-a", "purpose-1", "admin")
        store.grant_consent("client-a", "purpose-2", "admin")
        store.grant_consent("client-b", "purpose-1", "admin")

        consents_a = store.list_consents("client-a")
        assert len(consents_a) == 2

        consents_b = store.list_consents("client-b")
        assert len(consents_b) == 1

    def test_revoke_consent(self, store):
        consent_id = store.grant_consent("client-a", "purpose", "admin")

        # Active before revocation
        active = store.list_consents("client-a", active_only=True)
        assert len(active) == 1

        # Revoke
        store.revoke_consent(consent_id, revoked_by="client-a")

        # No longer active
        active = store.list_consents("client-a", active_only=True)
        assert len(active) == 0

        # But still in history
        all_consents = store.list_consents("client-a", active_only=False)
        assert len(all_consents) == 1
        assert all_consents[0]["revoked_at"] is not None

    def test_multiple_consents_revoke_one(self, store):
        c1 = store.grant_consent("client-a", "storage", "admin")
        c2 = store.grant_consent("client-a", "analytics", "admin")

        store.revoke_consent(c1, "client-a")

        active = store.list_consents("client-a", active_only=True)
        assert len(active) == 1
        assert active[0]["purpose"] == "analytics"


class TestAccessReport:
    def test_empty_report(self, store):
        report = store.access_report("nonexistent-client")
        assert report["client_ref"] == "nonexistent-client"
        assert report["summary"]["total_knowledge"] == 0
        assert report["summary"]["total_tasks"] == 0

    def test_full_report(self, store):
        # Add data for client
        store.learn("Client A info", client_ref="client-a", legal_basis="consent")
        store.learn("Client A preference", client_ref="client-a", legal_basis="consent")
        store.create_task("Review client A case", client_ref="client-a")
        store.create_artifact("report.pdf", project="case-a", client_ref="client-a")
        store.grant_consent("client-a", "storage", "admin")

        report = store.access_report("client-a")
        assert report["summary"]["total_knowledge"] == 2
        assert report["summary"]["total_tasks"] == 1
        assert report["summary"]["total_artifacts"] == 1
        assert report["summary"]["active_consents"] == 1

    def test_report_isolation(self, store):
        """Data from client-b should not appear in client-a report."""
        store.learn("Client A data", client_ref="client-a")
        store.learn("Client B data", client_ref="client-b")

        report_a = store.access_report("client-a")
        assert report_a["summary"]["total_knowledge"] == 1
        assert all(k["client_ref"] == "client-a" for k in report_a["knowledge"])

    def test_report_has_timestamp(self, store):
        report = store.access_report("client-a")
        assert "generated_at" in report
        assert "2026" in report["generated_at"]
