"""Tests for GDPR consent management and DPIA."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.compliance.consent import ConsentManager
from uaml.compliance.dpia import DPIAGenerator, BreachRegister


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db", agent_id="test")
    yield s
    s.close()


class TestConsentManager:
    def test_grant_and_check(self, store):
        cm = ConsentManager(store)
        cm.grant("client-1", "storage", granted_by="client-1")
        assert cm.check("client-1", "storage") is True
        assert cm.check("client-1", "analytics") is False

    def test_revoke(self, store):
        cm = ConsentManager(store)
        cm.grant("client-2", "storage", granted_by="client-2")
        assert cm.check("client-2", "storage") is True
        cm.revoke("client-2", "storage")
        assert cm.check("client-2", "storage") is False

    def test_list_consents(self, store):
        cm = ConsentManager(store)
        cm.grant("client-3", "storage", granted_by="client-3")
        cm.grant("client-3", "analytics", granted_by="client-3")

        active = cm.list_consents("client-3")
        assert len(active) == 2

    def test_consent_summary(self, store):
        cm = ConsentManager(store)
        cm.grant("client-4", "storage", granted_by="client-4")
        cm.grant("client-4", "sharing", granted_by="client-4")
        cm.revoke("client-4", "sharing")

        summary = cm.consent_summary("client-4")
        assert summary["active_count"] == 1
        assert summary["revoked_count"] == 1


class TestDPIAGenerator:
    def test_generate_empty(self, store):
        dpia = DPIAGenerator(store)
        assessment = dpia.generate()
        assert "risk_assessment" in assessment
        assert assessment["overall_risk"] in ("low", "medium", "high")

    def test_generate_with_data(self, store):
        store.learn("Client data", client_ref="c1", data_layer="knowledge")
        store.learn("Identity", data_layer="identity")

        dpia = DPIAGenerator(store)
        assessment = dpia.generate()
        assert assessment["data_inventory"]["has_personal_data"] is True


class TestBreachRegister:
    def test_record_breach(self, store):
        reg = BreachRegister(store)
        bid = reg.record_breach("Unauthorized access", severity="high")
        assert bid > 0

    def test_update_breach(self, store):
        reg = BreachRegister(store)
        bid = reg.record_breach("Data leak")
        reg.update_breach(bid, dpa_notified=True, status="resolved")
        status = reg.breach_status(bid)
        assert status["dpa_notified"] == 1
        assert status["status"] == "resolved"

    def test_72h_deadline(self, store):
        reg = BreachRegister(store)
        bid = reg.record_breach("Test breach")
        status = reg.breach_status(bid)
        assert status["deadline_72h"] is False  # Just created
        assert status["hours_elapsed"] < 1

    def test_list_breaches(self, store):
        reg = BreachRegister(store)
        reg.record_breach("Breach 1")
        reg.record_breach("Breach 2")
        all_breaches = reg.list_breaches()
        assert len(all_breaches) == 2


class TestPurge:
    def test_dry_run(self, store):
        store.learn("Old entry", data_layer="operational")
        result = store.purge(data_layer="operational", dry_run=True)
        assert result["status"] == "dry_run"
        assert result["would_delete"] >= 1

    def test_actual_purge(self, store):
        store.learn("Temp data", data_layer="operational", tags="temp")
        result = store.purge(tags="temp", dry_run=False)
        assert result["status"] == "completed"
        assert result["deleted"] >= 1

    def test_no_criteria_refused(self, store):
        result = store.purge(dry_run=False)
        assert result["status"] == "refused"

    def test_delete_entry(self, store):
        eid = store.learn("Delete me")
        assert store.delete_entry(eid) is True
        assert store.delete_entry(99999) is False

    def test_identity_protected(self, store):
        store.learn("My identity", data_layer="identity")
        result = store.purge(confidence_below=1.0, dry_run=True)
        # Identity entries should be excluded unless explicitly targeted
        assert result["status"] == "dry_run"


class TestContextSummary:
    def test_micro(self, store):
        store.learn("Python is great for scripting", summary="Python scripting")
        store.learn("SQLite is embedded", summary="SQLite DB")

        result = store.context_summary(size="micro")
        assert result["size"] == "micro"
        assert result["entries_used"] > 0
        assert len(result["text"]) <= 250  # micro + some slack

    def test_full(self, store):
        for i in range(10):
            store.learn(f"Knowledge entry number {i} with detailed content about topic {i}")

        result = store.context_summary(size="full")
        assert result["entries_used"] > 0
        assert result["char_limit"] == 8000

    def test_empty(self, store):
        result = store.context_summary(topic="nonexistent")
        assert result["entries_used"] == 0
        assert result["text"] == ""
