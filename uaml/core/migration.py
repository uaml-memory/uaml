# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Schema Migration — manage database schema evolution.

Tracks applied migrations and applies new ones in order.
Each migration is a named SQL script with up/down operations.

Usage:
    from uaml.core.migration import MigrationManager

    mm = MigrationManager(store)
    mm.register("001_add_legal_basis", up_sql="ALTER TABLE ...", down_sql="...")
    mm.migrate()  # Apply all pending
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class Migration:
    """A database migration."""
    name: str
    up_sql: str
    down_sql: str = ""
    description: str = ""


class MigrationManager:
    """Manage schema migrations for MemoryStore."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._conn = store._conn
        self._migrations: list[Migration] = []
        self._ensure_table()

    def _ensure_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now')),
                description TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.commit()

    def register(
        self,
        name: str,
        up_sql: str,
        down_sql: str = "",
        description: str = "",
    ) -> None:
        """Register a migration."""
        self._migrations.append(Migration(
            name=name,
            up_sql=up_sql,
            down_sql=down_sql,
            description=description,
        ))

    def applied(self) -> list[str]:
        """List applied migration names."""
        rows = self._conn.execute(
            "SELECT name FROM schema_migrations ORDER BY applied_at"
        ).fetchall()
        return [r["name"] for r in rows]

    def pending(self) -> list[Migration]:
        """List migrations not yet applied."""
        done = set(self.applied())
        return [m for m in self._migrations if m.name not in done]

    def migrate(self) -> list[str]:
        """Apply all pending migrations. Returns names of applied migrations."""
        applied = []
        for m in self.pending():
            try:
                self._conn.executescript(m.up_sql)
                self._conn.execute(
                    "INSERT INTO schema_migrations (name, applied_at, description) VALUES (?, ?, ?)",
                    (m.name, datetime.now(timezone.utc).isoformat(), m.description),
                )
                self._conn.commit()
                applied.append(m.name)
            except Exception as e:
                # Rollback this migration
                self._conn.rollback()
                raise RuntimeError(f"Migration '{m.name}' failed: {e}") from e

        return applied

    def rollback_last(self) -> Optional[str]:
        """Rollback the most recently applied migration."""
        done = self.applied()
        if not done:
            return None

        last_name = done[-1]
        migration = next((m for m in self._migrations if m.name == last_name), None)

        if migration and migration.down_sql:
            self._conn.executescript(migration.down_sql)

        self._conn.execute("DELETE FROM schema_migrations WHERE name = ?", (last_name,))
        self._conn.commit()
        return last_name

    def status(self) -> dict:
        """Get migration status."""
        done = self.applied()
        pend = self.pending()
        return {
            "applied": len(done),
            "pending": len(pend),
            "applied_names": done,
            "pending_names": [m.name for m in pend],
        }
