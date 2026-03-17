"""Tests for UAML Data Inventory."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.compliance.inventory import DataInventory


@pytest.fixture
def inv(tmp_path):
    store = MemoryStore(tmp_path / "inv.db", agent_id="test")
    i = DataInventory(store)
    yield i
    store.close()


class TestDataInventory:
    def test_register_activity(self, inv):
        aid = inv.register_activity(
            "knowledge_storage",
            purpose="AI memory management",
            legal_basis="legitimate_interest",
        )
        assert aid > 0

    def test_list_activities(self, inv):
        inv.register_activity("a", purpose="p", legal_basis="consent")
        activities = inv.list_activities()
        assert len(activities) == 1
        assert activities[0].name == "a"

    def test_remove_activity(self, inv):
        inv.register_activity("temp", purpose="p", legal_basis="consent")
        assert inv.remove_activity("temp") is True
        assert inv.remove_activity("nonexistent") is False

    def test_generate_report(self, inv):
        inv.register_activity("store", purpose="memory", legal_basis="legitimate_interest")
        inv.register_activity("export", purpose="backup", legal_basis="consent",
                            transfers_outside_eu=True, recipients=["backup_provider"])
        report = inv.generate_report()
        assert report["total_activities"] == 2
        assert report["eu_transfers"] == 1

    def test_check_compliance_empty(self, inv):
        issues = inv.check_compliance()
        assert len(issues) >= 1  # No activities = issue

    def test_check_compliance_ok(self, inv):
        inv.register_activity("store", purpose="memory", legal_basis="consent")
        issues = inv.check_compliance()
        assert len(issues) == 0

    def test_data_categories(self, inv):
        inv.register_activity("ml", purpose="training", legal_basis="consent",
                            data_categories=["personal", "behavioral"])
        activities = inv.list_activities()
        assert "personal" in activities[0].data_categories

    def test_retention_days(self, inv):
        inv.register_activity("logs", purpose="audit", legal_basis="legal_obligation",
                            retention_days=90)
        activities = inv.list_activities()
        assert activities[0].retention_days == 90

    def test_eu_transfer_compliance(self, inv):
        inv.register_activity("cloud", purpose="storage", legal_basis="consent",
                            transfers_outside_eu=True)
        issues = inv.check_compliance()
        assert any("EU transfers" in i for i in issues)
