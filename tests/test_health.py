"""Tests for UAML Health Check."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.health import HealthChecker


@pytest.fixture
def checker(tmp_path):
    store = MemoryStore(tmp_path / "health.db", agent_id="test")
    store.learn("Test entry", topic="test")
    c = HealthChecker(store)
    yield c
    store.close()


class TestHealthChecker:
    def test_full_check(self, checker):
        report = checker.full_check()
        assert report["status"] in ("healthy", "degraded", "unhealthy")
        assert "checks" in report
        assert "database" in report["checks"]

    def test_database_ok(self, checker):
        result = checker._check_database()
        assert result["status"] == "ok"
        assert result["entries"] >= 1

    def test_storage(self, checker):
        result = checker._check_storage()
        assert result["status"] in ("ok", "warning")

    def test_audit(self, checker):
        result = checker._check_audit()
        assert result["status"] in ("ok", "warning")

    def test_knowledge(self, checker):
        result = checker._check_knowledge()
        assert result["status"] == "ok"
        assert result["total_entries"] >= 1

    def test_quick_check(self, checker):
        result = checker.quick_check()
        assert result["status"] == "healthy"
        assert result["db"] == "ok"

    def test_healthy_score(self, checker):
        report = checker.full_check()
        assert report["check_ms"] >= 0

    def test_empty_store(self, tmp_path):
        store = MemoryStore(tmp_path / "empty.db", agent_id="test")
        c = HealthChecker(store)
        report = c.full_check()
        assert report["status"] in ("healthy", "degraded")
        store.close()
