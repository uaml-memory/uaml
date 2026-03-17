# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Scheduler — periodic maintenance tasks for MemoryStore.

Manages scheduled tasks: stale detection, dedup, backup reminders,
compliance checks, and custom user-defined tasks.

Usage:
    from uaml.core.scheduler import MaintenanceScheduler

    scheduler = MaintenanceScheduler(store)
    scheduler.register_task("dedup", interval_hours=24, callback=my_dedup)
    due = scheduler.check_due()
    scheduler.run_due()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ScheduledTask:
    """A periodic maintenance task."""
    name: str
    interval_seconds: float
    callback: Callable
    description: str = ""
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0
    error_count: int = 0
    last_error: str = ""

    @property
    def is_due(self) -> bool:
        if not self.enabled:
            return False
        return (time.monotonic() - self.last_run) >= self.interval_seconds

    @property
    def next_run_in(self) -> float:
        """Seconds until next run."""
        elapsed = time.monotonic() - self.last_run
        remaining = self.interval_seconds - elapsed
        return max(0, remaining)


class MaintenanceScheduler:
    """Schedule and run periodic maintenance tasks."""

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}

    def register_task(
        self,
        name: str,
        callback: Callable,
        *,
        interval_hours: float = 24,
        interval_seconds: Optional[float] = None,
        description: str = "",
    ) -> ScheduledTask:
        """Register a maintenance task.

        Args:
            name: Unique task name
            callback: Function to execute (no args)
            interval_hours: Run interval in hours (default 24)
            interval_seconds: Override interval in seconds
            description: Human description
        """
        seconds = interval_seconds if interval_seconds is not None else interval_hours * 3600

        task = ScheduledTask(
            name=name,
            interval_seconds=seconds,
            callback=callback,
            description=description,
        )
        self._tasks[name] = task
        return task

    def unregister(self, name: str) -> bool:
        """Remove a task."""
        return self._tasks.pop(name, None) is not None

    def check_due(self) -> list[str]:
        """Check which tasks are due to run."""
        return [name for name, task in self._tasks.items() if task.is_due]

    def run_task(self, name: str) -> bool:
        """Run a specific task. Returns True on success."""
        task = self._tasks.get(name)
        if not task:
            return False

        try:
            task.callback()
            task.last_run = time.monotonic()
            task.run_count += 1
            task.last_error = ""
            return True
        except Exception as e:
            task.error_count += 1
            task.last_error = str(e)
            task.last_run = time.monotonic()  # Don't retry immediately
            return False

    def run_due(self) -> dict[str, bool]:
        """Run all due tasks. Returns {name: success}."""
        results = {}
        for name in self.check_due():
            results[name] = self.run_task(name)
        return results

    def enable(self, name: str) -> bool:
        task = self._tasks.get(name)
        if task:
            task.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        task = self._tasks.get(name)
        if task:
            task.enabled = False
            return True
        return False

    def status(self) -> dict:
        """Get scheduler status."""
        return {
            "total_tasks": len(self._tasks),
            "enabled": sum(1 for t in self._tasks.values() if t.enabled),
            "due_now": len(self.check_due()),
            "tasks": {
                name: {
                    "enabled": t.enabled,
                    "interval_hours": round(t.interval_seconds / 3600, 1),
                    "is_due": t.is_due,
                    "run_count": t.run_count,
                    "error_count": t.error_count,
                    "last_error": t.last_error,
                    "next_run_in_seconds": round(t.next_run_in, 0),
                }
                for name, t in self._tasks.items()
            },
        }

    def list_tasks(self) -> list[dict]:
        """List all tasks."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "enabled": t.enabled,
                "interval_hours": round(t.interval_seconds / 3600, 1),
                "run_count": t.run_count,
            }
            for t in self._tasks.values()
        ]
