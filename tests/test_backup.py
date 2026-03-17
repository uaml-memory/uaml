"""Tests for UAML Backup Manager."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.io.backup import BackupManager


@pytest.fixture
def bm(tmp_path):
    store = MemoryStore(tmp_path / "backup_src.db", agent_id="test")
    store.learn("Important data", topic="critical")
    store.learn("More data", topic="info")
    manager = BackupManager(store, backup_dir=str(tmp_path / "backups"))
    yield manager
    store.close()


class TestBackupManager:
    def test_create_backup_compressed(self, bm):
        path = bm.create_backup(compress=True)
        assert path.exists()
        assert path.suffix == ".gz"

    def test_create_backup_uncompressed(self, bm):
        path = bm.create_backup(compress=False)
        assert path.exists()
        assert path.suffix == ".db"

    def test_create_with_label(self, bm):
        path = bm.create_backup(label="test")
        assert "test" in path.name

    def test_verify_backup(self, bm):
        path = bm.create_backup(compress=False)
        result = bm.verify_backup(path)
        assert result["status"] == "ok"
        assert result["entries"] == 2

    def test_verify_compressed(self, bm):
        path = bm.create_backup(compress=True)
        result = bm.verify_backup(path)
        assert result["status"] == "ok"

    def test_verify_missing(self, bm, tmp_path):
        result = bm.verify_backup(tmp_path / "nonexistent.db")
        assert result["status"] == "error"

    def test_list_backups(self, bm):
        bm.create_backup(label="a")
        bm.create_backup(label="b")
        backups = bm.list_backups()
        assert len(backups) >= 2

    def test_rotate(self, bm):
        for i in range(5):
            bm.create_backup(label=f"rot{i}")
        backups_before = len(bm.list_backups())
        if backups_before > 3:
            removed = bm.rotate(max_backups=3)
            assert removed >= 1
            assert len(bm.list_backups()) <= 3

    def test_restore(self, bm, tmp_path):
        path = bm.create_backup(compress=False)

        # Create a new store and restore into it
        new_store = MemoryStore(tmp_path / "restored.db", agent_id="test")
        new_bm = BackupManager(new_store, backup_dir=str(tmp_path / "backups"))
        ok = new_bm.restore_backup(path)
        assert ok is True

        count = new_store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 2
        new_store.close()

    def test_restore_compressed(self, bm, tmp_path):
        path = bm.create_backup(compress=True)
        new_store = MemoryStore(tmp_path / "restored2.db", agent_id="test")
        new_bm = BackupManager(new_store, backup_dir=str(tmp_path / "backups"))
        ok = new_bm.restore_backup(path)
        assert ok is True
        new_store.close()

    def test_restore_missing(self, bm, tmp_path):
        assert bm.restore_backup(tmp_path / "nope.db") is False
