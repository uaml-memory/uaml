"""Tests for UAML Schema Migration."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.migration import MigrationManager


@pytest.fixture
def mm(tmp_path):
    store = MemoryStore(tmp_path / "mig.db", agent_id="test")
    manager = MigrationManager(store)
    yield manager
    store.close()


class TestMigrationManager:
    def test_register_and_migrate(self, mm):
        mm.register(
            "001_test_table",
            up_sql="CREATE TABLE test_mig (id INTEGER PRIMARY KEY, val TEXT);",
            down_sql="DROP TABLE IF EXISTS test_mig;",
        )
        applied = mm.migrate()
        assert applied == ["001_test_table"]

    def test_idempotent(self, mm):
        mm.register("001", up_sql="CREATE TABLE IF NOT EXISTS t1 (id INTEGER);")
        mm.migrate()
        applied = mm.migrate()  # Should be empty — already applied
        assert applied == []

    def test_pending(self, mm):
        mm.register("001", up_sql="SELECT 1;")
        mm.register("002", up_sql="SELECT 1;")
        assert len(mm.pending()) == 2
        mm.migrate()
        assert len(mm.pending()) == 0

    def test_rollback(self, mm):
        mm.register(
            "001",
            up_sql="CREATE TABLE rollback_test (id INTEGER);",
            down_sql="DROP TABLE IF EXISTS rollback_test;",
        )
        mm.migrate()
        rolled = mm.rollback_last()
        assert rolled == "001"
        assert len(mm.applied()) == 0

    def test_rollback_empty(self, mm):
        assert mm.rollback_last() is None

    def test_status(self, mm):
        mm.register("001", up_sql="SELECT 1;")
        mm.register("002", up_sql="SELECT 1;")
        mm.migrate()

        status = mm.status()
        assert status["applied"] == 2
        assert status["pending"] == 0

    def test_failed_migration(self, mm):
        mm.register("bad", up_sql="THIS IS NOT VALID SQL SYNTAX;")
        with pytest.raises(RuntimeError, match="failed"):
            mm.migrate()
        assert len(mm.applied()) == 0
