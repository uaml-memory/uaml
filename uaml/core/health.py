# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Health Check — system health monitoring.

Provides comprehensive health checks for all UAML subsystems:
database, storage, crypto, compliance, graph, etc.

Usage:
    from uaml.core.health import HealthChecker

    checker = HealthChecker(store)
    report = checker.full_check()
    print(report["status"])  # "healthy" | "degraded" | "unhealthy"
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from uaml.core.store import MemoryStore


class HealthChecker:
    """Check health of UAML subsystems."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def full_check(self) -> dict:
        """Run all health checks."""
        checks = {}
        start = time.monotonic()

        checks["database"] = self._check_database()
        checks["storage"] = self._check_storage()
        checks["audit"] = self._check_audit()
        checks["knowledge"] = self._check_knowledge()

        elapsed = time.monotonic() - start

        # Determine overall status
        statuses = [c["status"] for c in checks.values()]
        if all(s == "ok" for s in statuses):
            overall = "healthy"
        elif any(s == "error" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"

        return {
            "status": overall,
            "check_ms": round(elapsed * 1000, 1),
            "checks": checks,
        }

    def _check_database(self) -> dict:
        """Check database connectivity and integrity."""
        try:
            # Simple query
            row = self.store._conn.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()
            count = row["c"] if row else 0

            # Check integrity
            integrity = self.store._conn.execute("PRAGMA integrity_check").fetchone()
            is_ok = integrity[0] == "ok" if integrity else False

            return {
                "status": "ok" if is_ok else "warning",
                "entries": count,
                "integrity": "ok" if is_ok else "failed",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_storage(self) -> dict:
        """Check storage space and DB size."""
        try:
            db_path = self.store.db_path if hasattr(self.store, 'db_path') else None
            if db_path and Path(str(db_path)).exists():
                size_bytes = Path(str(db_path)).stat().st_size
                size_mb = size_bytes / (1024 * 1024)

                # Check available disk space
                stat_result = os.statvfs(str(db_path))
                free_mb = (stat_result.f_bavail * stat_result.f_frsize) / (1024 * 1024)

                status = "ok"
                if free_mb < 100:
                    status = "warning"
                if free_mb < 10:
                    status = "error"

                return {
                    "status": status,
                    "db_size_mb": round(size_mb, 2),
                    "free_space_mb": round(free_mb, 0),
                }
            return {"status": "ok", "note": "in-memory database"}
        except Exception as e:
            return {"status": "warning", "error": str(e)}

    def _check_audit(self) -> dict:
        """Check audit log status."""
        try:
            # Check if audit_log table exists
            tables = self.store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
            ).fetchall()

            if not tables:
                return {"status": "warning", "note": "audit_log table not found"}

            count = self.store._conn.execute(
                "SELECT COUNT(*) as c FROM audit_log"
            ).fetchone()
            entry_count = count["c"] if count else 0

            return {
                "status": "ok",
                "entries": entry_count,
            }
        except Exception as e:
            return {"status": "warning", "error": str(e)}

    def _check_knowledge(self) -> dict:
        """Check knowledge base health."""
        try:
            stats = self.store.stats()
            total = stats.get("knowledge", stats.get("total_entries", 0))

            # Check for orphaned entries (no content)
            empty = self.store._conn.execute(
                "SELECT COUNT(*) as c FROM knowledge WHERE content IS NULL OR content = ''"
            ).fetchone()
            empty_count = empty["c"] if empty else 0

            status = "ok"
            if empty_count > total * 0.1 and total > 0:
                status = "warning"

            return {
                "status": status,
                "total_entries": total,
                "empty_entries": empty_count,
                "topics": len(stats.get("top_topics", {})),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def quick_check(self) -> dict:
        """Fast health check — just DB connectivity."""
        try:
            self.store._conn.execute("SELECT 1").fetchone()
            return {"status": "healthy", "db": "ok"}
        except Exception as e:
            return {"status": "unhealthy", "db": "error", "error": str(e)}
