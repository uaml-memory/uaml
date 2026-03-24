"""Tests for UAML Scheduler."""

from __future__ import annotations

import pytest

from uaml.core.scheduler import MaintenanceScheduler


class TestScheduler:
    def test_register_task(self):
        s = MaintenanceScheduler()
        task = s.register_task("test", lambda: None, interval_hours=1)
        assert task.name == "test"

    def test_due_immediately(self):
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: None, interval_seconds=0)
        assert "t1" in s.check_due()

    def test_not_due(self):
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: None, interval_seconds=99999)
        # Run it first so last_run is set
        s.run_task("t1")
        assert "t1" not in s.check_due()

    def test_run_task(self):
        results = []
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: results.append("done"))
        assert s.run_task("t1") is True
        assert results == ["done"]

    def test_run_task_error(self):
        s = MaintenanceScheduler()
        s.register_task("bad", lambda: 1/0)
        assert s.run_task("bad") is False
        assert s._tasks["bad"].error_count == 1

    def test_run_due(self):
        count = [0]
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: count.__setitem__(0, count[0]+1), interval_seconds=0)
        results = s.run_due()
        assert results["t1"] is True
        assert count[0] == 1

    def test_disable_enable(self):
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: None, interval_seconds=0)
        s.disable("t1")
        assert "t1" not in s.check_due()
        s.enable("t1")
        assert "t1" in s.check_due()

    def test_unregister(self):
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: None)
        assert s.unregister("t1") is True
        assert s.unregister("nonexistent") is False

    def test_status(self):
        s = MaintenanceScheduler()
        s.register_task("t1", lambda: None)
        status = s.status()
        assert status["total_tasks"] == 1
        assert "t1" in status["tasks"]

    def test_list_tasks(self):
        s = MaintenanceScheduler()
        s.register_task("a", lambda: None, description="Task A")
        tasks = s.list_tasks()
        assert len(tasks) == 1
        assert tasks[0]["description"] == "Task A"

    def test_nonexistent_task(self):
        s = MaintenanceScheduler()
        assert s.run_task("nope") is False
