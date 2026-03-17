# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Backup Manager — database backup and restore.

Provides SQLite backup with compression, rotation, and verification.

Usage:
    from uaml.io.backup import BackupManager

    bm = BackupManager(store, backup_dir="/backups")
    path = bm.create_backup()
    bm.verify_backup(path)
    bm.restore_backup(path)
"""

from __future__ import annotations

import shutil
import sqlite3
import gzip
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class BackupManifest:
    """Backup manifest for compatibility with old API."""
    backup_path: Path
    entry_counts: dict = field(default_factory=dict)
    integrity_ok: bool = True
    size_bytes: int = 0

    @property
    def target_path(self) -> str:
        return str(self.backup_path)

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_path.stem if self.backup_path else "",
            "backup_path": str(self.backup_path),
            "target_path": str(self.backup_path),
            "entry_counts": self.entry_counts,
            "integrity_ok": self.integrity_ok,
            "size_bytes": self.size_bytes,
        }


@dataclass
class BackupConfig:
    """Backup configuration (compat)."""
    compress: bool = True
    label: str = ""


@dataclass
class BackupTarget:
    """Backup target (compat)."""
    path: Path = field(default_factory=lambda: Path("backups"))


class BackupManager:
    """Manage database backups."""

    def __init__(self, store: MemoryStore, backup_dir: Optional[str] = None):
        self.store = store
        self.backup_dir = Path(backup_dir) if backup_dir else Path("backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def backup_full(self, target_dir=None, **kwargs) -> BackupManifest:
        """Create backup and return manifest (backward compat).

        Args:
            target_dir: If provided, override backup directory for this backup
        """
        if target_dir:
            old_dir = self.backup_dir
            self.backup_dir = Path(target_dir)
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            try:
                path = self.create_backup(**kwargs)
            finally:
                self.backup_dir = old_dir
        else:
            path = self.create_backup(**kwargs)

        # Build manifest
        count = 0
        try:
            count = self.store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        except Exception:
            pass

        return BackupManifest(
            backup_path=path,
            entry_counts={"knowledge": count},
            integrity_ok=True,
            size_bytes=path.stat().st_size if path.exists() else 0,
        )

    def create_backup(
        self,
        *,
        compress: bool = True,
        label: str = "",
    ) -> Path:
        """Create a backup of the database.

        Args:
            compress: Use gzip compression
            label: Optional label for the backup filename

        Returns:
            Path to the backup file
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        name_parts = ["uaml_backup", timestamp]
        if label:
            name_parts.append(label)

        # SQLite online backup
        backup_db = self.backup_dir / f"{'_'.join(name_parts)}.db"

        backup_conn = sqlite3.connect(str(backup_db))
        self.store._conn.backup(backup_conn)
        backup_conn.close()

        if compress:
            gz_path = backup_db.with_suffix(".db.gz")
            with open(backup_db, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_db.unlink()
            result_path = gz_path
        else:
            result_path = backup_db

        # Audit log the backup
        try:
            self.store._audit("backup", "knowledge", 0,
                              getattr(self.store, 'agent_id', ''),
                              f"backup created: {result_path.name}")
        except Exception:
            pass

        return result_path

    def verify(self, backup_path) -> dict:
        """Verify backup with backward-compat keys."""
        result = self.verify_backup(Path(str(backup_path)))
        # Compat keys
        result["readable"] = result.get("status") != "error"
        result["checksum_ok"] = result.get("integrity") == "ok"
        return result

    def verify_backup(self, backup_path: Path) -> dict:
        """Verify a backup file integrity.

        Returns dict with status and entry count.
        """
        path = Path(backup_path)
        if not path.exists():
            return {"status": "error", "error": "File not found"}

        try:
            # Decompress if needed
            if path.suffix == ".gz":
                import tempfile
                tmp = Path(tempfile.mktemp(suffix=".db"))
                with gzip.open(path, "rb") as f_in:
                    with open(tmp, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                db_path = tmp
            else:
                db_path = path

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Check integrity
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            is_ok = integrity[0] == "ok"

            # Count entries
            count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            conn.close()

            # Cleanup temp
            if path.suffix == ".gz" and db_path != path:
                db_path.unlink()

            return {
                "status": "ok" if is_ok else "corrupt",
                "integrity": "ok" if is_ok else "failed",
                "entries": count,
                "size_bytes": path.stat().st_size,
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def list_backups(self) -> list[dict]:
        """List all backups in the backup directory."""
        backups = []
        for f in sorted(self.backup_dir.glob("uaml_backup_*")):
            backups.append({
                "path": str(f),
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "created": datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            })
        return backups

    def rotate(self, max_backups: int = 10) -> int:
        """Remove oldest backups if more than max_backups exist.

        Returns number of backups removed.
        """
        backups = sorted(
            self.backup_dir.glob("uaml_backup_*"),
            key=lambda f: f.stat().st_mtime,
        )

        removed = 0
        while len(backups) > max_backups:
            oldest = backups.pop(0)
            oldest.unlink()
            removed += 1

        return removed

    def restore_backup(self, backup_path: Path) -> bool:
        """Restore database from backup.

        ⚠️ This replaces the current database!
        """
        path = Path(backup_path)
        if not path.exists():
            return False

        try:
            if path.suffix == ".gz":
                import tempfile
                tmp = Path(tempfile.mktemp(suffix=".db"))
                with gzip.open(path, "rb") as f_in:
                    with open(tmp, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                source_path = tmp
            else:
                source_path = path

            source_conn = sqlite3.connect(str(source_path))
            source_conn.backup(self.store._conn)
            source_conn.close()

            if path.suffix == ".gz" and source_path != path:
                source_path.unlink()

            return True

        except Exception:
            return False
