"""Tests for UAML Retention Policies."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from uaml.core.store import MemoryStore
from uaml.core.retention import RetentionManager, RetentionPolicy


@pytest.fixture
def rm(tmp_path):
    store = MemoryStore(tmp_path / "ret.db", agent_id="test")
    # Recent entry
    store.learn("Fresh knowledge", topic="current", data_layer="knowledge")
    # Old entry (manually insert)
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    store._conn.execute(
        """INSERT INTO knowledge (content, topic, confidence, data_layer,
           source_type, source_origin, created_at, updated_at, agent_id)
           VALUES (?, ?, ?, ?, 'manual', 'external', ?, ?, 'test')""",
        ("Stale operational data", "ops", 0.5, "operational", old, old),
    )
    store._conn.commit()

    manager = RetentionManager(store)
    yield manager
    store.close()


class TestRetentionManager:
    def test_evaluate_no_policies(self, rm):
        actions = rm.evaluate()
        assert actions == []

    def test_evaluate_with_policy(self, rm):
        rm.add_policy(RetentionPolicy(
            name="archive_old_ops",
            data_layer="operational",
            max_age_days=90,
            action="archive",
        ))
        actions = rm.evaluate()
        assert len(actions) >= 1
        assert actions[0].action == "archive"

    def test_recent_not_affected(self, rm):
        rm.add_policy(RetentionPolicy(
            name="purge_old",
            max_age_days=90,
            action="delete",
        ))
        actions = rm.evaluate()
        # Recent entry should NOT be in actions
        topics = [a.topic for a in actions]
        assert "current" not in topics

    def test_dry_run(self, rm):
        rm.add_policy(RetentionPolicy(
            name="test", max_age_days=90, action="delete",
        ))
        result = rm.execute(dry_run=True)
        assert result["dry_run"] is True
        assert result["total_actions"] >= 1
        # Verify nothing actually deleted
        count = rm.store._conn.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]
        assert count >= 2

    def test_execute_delete(self, rm):
        rm.add_policy(RetentionPolicy(
            name="delete_old_ops",
            data_layer="operational",
            max_age_days=90,
            action="delete",
        ))
        result = rm.execute(dry_run=False)
        assert result["executed"] >= 1

    def test_execute_archive(self, rm):
        rm.add_policy(RetentionPolicy(
            name="archive_ops",
            data_layer="operational",
            max_age_days=90,
            action="archive",
        ))
        rm.execute(dry_run=False)
        row = rm.store._conn.execute(
            "SELECT data_layer FROM knowledge WHERE topic = 'ops'"
        ).fetchone()
        assert row["data_layer"] == "archive"

    def test_execute_reduce_confidence(self, rm):
        rm.add_policy(RetentionPolicy(
            name="decay", max_age_days=90, action="reduce_confidence",
        ))
        rm.execute(dry_run=False)
        row = rm.store._conn.execute(
            "SELECT confidence FROM knowledge WHERE topic = 'ops'"
        ).fetchone()
        assert row["confidence"] < 0.5

    def test_remove_policy(self, rm):
        rm.add_policy(RetentionPolicy(name="temp", max_age_days=30))
        assert rm.remove_policy("temp") is True
        assert rm.remove_policy("nonexistent") is False

    def test_disabled_policy(self, rm):
        rm.add_policy(RetentionPolicy(
            name="disabled", max_age_days=90, enabled=False,
        ))
        actions = rm.evaluate()
        assert all(a.policy_name != "disabled" for a in actions)

    def test_list_policies(self, rm):
        rm.add_policy(RetentionPolicy(name="p1", max_age_days=30))
        policies = rm.list_policies()
        assert len(policies) == 1
        assert policies[0]["name"] == "p1"

    def test_topic_filter(self, rm):
        rm.add_policy(RetentionPolicy(
            name="ops_only", max_age_days=90, topic="ops",
        ))
        actions = rm.evaluate()
        assert all("ops" in a.topic for a in actions)
