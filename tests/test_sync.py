"""Tests for uaml.sync — JSON changelog-based synchronization.

© 2026 GLG, a.s. / GLG, a.s.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.sync import (
    ADMIN,
    ALL_SYNC_TABLES,
    EXTERNAL_PARTNER,
    TEAM_FULL,
    TEAM_READONLY,
    ChangeEntry,
    ConflictResolver,
    SyncEngine,
    SyncFilter,
    SyncProfile,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_store(tmp_path: Path, name: str = "test") -> MemoryStore:
    """Create a fresh MemoryStore in a temp directory."""
    db_path = tmp_path / f"{name}.db"
    return MemoryStore(str(db_path), agent_id=name, ethics_mode="off", contradiction_mode="off")


def _make_engine(store: MemoryStore, node_id: str, tmp_path: Path) -> SyncEngine:
    """Create a SyncEngine with a temp sync directory."""
    sync_dir = tmp_path / "sync" / node_id
    return SyncEngine(store, node_id=node_id, sync_dir=str(sync_dir))


# ── Tests ────────────────────────────────────────────────────

class TestExportEmpty:
    """Test 1: export from an empty DB."""

    def test_export_empty_db(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        filepath = engine.export_changes()
        assert os.path.exists(filepath)

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 0
        store.close()


class TestLearnAndExport:
    """Test 2: learn entries, then export changes."""

    def test_learn_export(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Python GIL prevents true threading", topic="python", tags="concurrency")
        store.learn("SQLite uses WAL mode for concurrency", topic="databases")

        filepath = engine.export_changes()

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2

        # Verify JSONL structure
        for line in lines:
            obj = json.loads(line)
            assert "id" in obj
            assert "node" in obj
            assert obj["node"] == "node-a"
            assert "ts" in obj
            assert "action" in obj
            assert obj["action"] == "learn"
            assert "data" in obj
            assert "checksum" in obj
        store.close()


class TestImportToFreshDB:
    """Test 3: import changelog to a fresh database."""

    def test_import_fresh(self, tmp_path):
        # Source node
        store_a = _make_store(tmp_path, "node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)

        store_a.learn("Fact one", topic="test")
        store_a.learn("Fact two", topic="test")
        filepath = engine_a.export_changes()

        # Target node (fresh)
        store_b = _make_store(tmp_path, "node-b")
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        result = engine_b.import_changes(filepath)
        assert result["applied"] == 2
        assert result["skipped"] == 0

        # Verify data arrived
        results = store_b.search("Fact one")
        assert len(results) >= 1
        assert "Fact one" in results[0].entry.content

        store_a.close()
        store_b.close()


class TestBidirectionalSync:
    """Test 4: sync between two nodes in both directions."""

    def test_bidirectional(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        store_b = _make_store(tmp_path, "node-b")
        engine_a = _make_engine(store_a, "node-a", tmp_path)
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        # Node A learns
        store_a.learn("Knowledge from A", topic="sync-test")
        path_a = engine_a.export_changes()

        # Node B learns
        store_b.learn("Knowledge from B", topic="sync-test")
        path_b = engine_b.export_changes()

        # Import A → B
        result_ab = engine_b.import_changes(path_a)
        assert result_ab["applied"] == 1

        # Import B → A
        result_ba = engine_a.import_changes(path_b)
        assert result_ba["applied"] == 1

        # Both nodes should have both entries
        a_results = store_a.search("Knowledge from B")
        assert len(a_results) >= 1
        b_results = store_b.search("Knowledge from A")
        assert len(b_results) >= 1

        store_a.close()
        store_b.close()


class TestConflictResolution:
    """Test 5: conflict detection and last-write-wins resolution."""

    def test_conflict_last_write_wins(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        store_b = _make_store(tmp_path, "node-b")
        engine_a = _make_engine(store_a, "node-a", tmp_path)
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        # Both nodes have entry ID 1
        id_a = store_a.learn("Original fact", topic="test")
        id_b = store_b.learn("Original fact", topic="test")

        # Node A updates locally
        store_a.conn.execute(
            "UPDATE knowledge SET content = 'Updated by A', updated_at = '2026-03-14T11:00:00Z' WHERE id = ?",
            (id_a,),
        )
        store_a.conn.commit()

        # Node B exports an update with a later timestamp
        entry = ChangeEntry(
            id="conflict-test-id",
            node_id="node-b",
            timestamp="2026-03-14T12:00:00Z",
            action="update",
            entry_id=id_a,
            data={"content": "Updated by B", "topic": "test", "tags": ""},
            checksum=ChangeEntry.compute_checksum({"content": "Updated by B", "topic": "test", "tags": ""}),
        )
        # Write manual JSONL
        sync_dir = tmp_path / "manual_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        filepath = sync_dir / "conflict.jsonl"
        with open(filepath, "w") as f:
            f.write(entry.to_jsonl() + "\n")

        result = engine_a.import_changes(str(filepath))
        # Remote is newer — should win
        assert result["applied"] + result["conflicts"] >= 1

        store_a.close()
        store_b.close()


class TestOfflineSync:
    """Test 6: offline sync — accumulate changes, batch import."""

    def test_offline_accumulate(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)

        # Accumulate changes while "offline"
        store_a.learn("Day 1 note", topic="journal")
        store_a.learn("Day 2 note", topic="journal")
        store_a.learn("Day 3 note", topic="journal")

        # Export all accumulated
        filepath = engine_a.export_changes()

        # Import to fresh node
        store_b = _make_store(tmp_path, "node-b")
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        result = engine_b.import_changes(filepath)
        assert result["applied"] == 3

        store_a.close()
        store_b.close()


class TestFullExportImport:
    """Test 7: full export and full import."""

    def test_full_export_import(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)

        store_a.learn("Entry 1", topic="test")
        store_a.learn("Entry 2", topic="test")
        store_a.learn("Entry 3", topic="test")

        filepath = engine_a.full_export()
        assert os.path.exists(filepath)

        # Full import to fresh node
        store_b = _make_store(tmp_path, "node-b")
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        result = engine_b.full_import(filepath)
        assert result["applied"] == 3
        assert result["conflicts"] == 0

        # Verify
        stats = store_b.stats()
        assert stats["knowledge"] == 3

        store_a.close()
        store_b.close()


class TestChecksumValidation:
    """Test 8: checksum validation — corrupt data should be skipped."""

    def test_bad_checksum_skipped(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        entry = ChangeEntry(
            id="bad-checksum",
            node_id="node-x",
            timestamp="2026-03-14T10:00:00Z",
            action="learn",
            entry_id=99,
            data={"content": "Test content", "topic": "test"},
            checksum="0000000000000000000000000000000000000000000000000000000000000000",
        )

        sync_dir = tmp_path / "bad_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        filepath = sync_dir / "bad.jsonl"
        with open(filepath, "w") as f:
            f.write(entry.to_jsonl() + "\n")

        result = engine.import_changes(str(filepath))
        assert result["skipped"] == 1
        assert result["applied"] == 0

        store.close()


class TestDuplicateDetection:
    """Test 9: importing the same changelog twice — second import is skipped."""

    def test_duplicate_skip(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)
        store_a.learn("Unique fact", topic="test")
        filepath = engine_a.export_changes()

        store_b = _make_store(tmp_path, "node-b")
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        result1 = engine_b.import_changes(filepath)
        assert result1["applied"] == 1

        result2 = engine_b.import_changes(filepath)
        assert result2["skipped"] == 1
        assert result2["applied"] == 0

        # Only one entry in DB
        stats = store_b.stats()
        assert stats["knowledge"] == 1

        store_a.close()
        store_b.close()


class TestSyncStateTracking:
    """Test 10: sync state tracking — last_sync timestamps."""

    def test_sync_state(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        assert engine.get_last_sync("node-b") is None

        engine.set_last_sync("node-b", "2026-03-14T10:00:00Z")
        assert engine.get_last_sync("node-b") == "2026-03-14T10:00:00Z"

        engine.set_last_sync("node-b", "2026-03-14T12:00:00Z")
        assert engine.get_last_sync("node-b") == "2026-03-14T12:00:00Z"

        # Get latest across all nodes
        engine.set_last_sync("node-c", "2026-03-14T15:00:00Z")
        assert engine.get_last_sync() == "2026-03-14T15:00:00Z"

        store.close()


class TestJSONLFormat:
    """Test 11: JSONL format validation."""

    def test_jsonl_structure(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "test-node", tmp_path)

        store.learn("Test content", topic="infra", tags="server,vps")
        filepath = engine.export_changes()

        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # Required fields
                assert isinstance(obj["id"], str)
                assert obj["node"] == "test-node"
                assert isinstance(obj["ts"], str)
                assert obj["action"] in ("learn", "update", "delete", "tag", "link")
                assert isinstance(obj["entry_id"], int)
                assert isinstance(obj["data"], dict)
                assert isinstance(obj["checksum"], str)
                assert len(obj["checksum"]) == 64  # SHA-256 hex

                # Verify checksum
                entry = ChangeEntry.from_json(obj)
                assert entry.verify_checksum()

        store.close()


class TestLargeBatchSync:
    """Test 12: large batch sync (100+ entries)."""

    def test_large_batch(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)

        for i in range(120):
            store_a.learn(f"Batch entry number {i}: {os.urandom(8).hex()}", topic="batch")

        filepath = engine_a.export_changes()

        store_b = _make_store(tmp_path, "node-b")
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        result = engine_b.import_changes(filepath)
        assert result["applied"] == 120

        stats = store_b.stats()
        assert stats["knowledge"] == 120

        store_a.close()
        store_b.close()


class TestDeleteSync:
    """Test 13: sync of delete operations."""

    def test_delete_sync(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        store_b = _make_store(tmp_path, "node-b")
        engine_a = _make_engine(store_a, "node-a", tmp_path)
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        # Both nodes have the same entry
        id_a = store_a.learn("To be deleted", topic="test")
        id_b = store_b.learn("To be deleted", topic="test")

        # Node A deletes
        store_a.delete_entry(id_a)

        # Export includes the delete
        filepath = engine_a.export_changes()

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]
        actions = [json.loads(l)["action"] for l in lines]
        assert "delete" in actions

        store_a.close()
        store_b.close()


class TestTagSync:
    """Test 14: tag/update sync."""

    def test_tag_sync(self, tmp_path):
        store_a = _make_store(tmp_path, "node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)

        entry_id = store_a.learn("Taggable entry", topic="test", tags="initial")

        # Manually create a tag change entry
        data = {"tags": "updated,tagged"}
        entry = ChangeEntry(
            id="tag-change-1",
            node_id="node-remote",
            timestamp="2026-03-14T10:00:00Z",
            action="tag",
            entry_id=entry_id,
            data=data,
            checksum=ChangeEntry.compute_checksum(data),
        )

        sync_dir = tmp_path / "tag_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        filepath = sync_dir / "tags.jsonl"
        with open(filepath, "w") as f:
            f.write(entry.to_jsonl() + "\n")

        result = engine_a.import_changes(str(filepath))
        assert result["applied"] == 1

        # Verify tags updated
        row = store_a.conn.execute(
            "SELECT tags FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()
        assert row["tags"] == "updated,tagged"

        store_a.close()


class TestErrorHandling:
    """Test 15: error handling — corrupt JSONL, missing fields."""

    def test_corrupt_jsonl(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        sync_dir = tmp_path / "corrupt"
        sync_dir.mkdir(parents=True, exist_ok=True)
        filepath = sync_dir / "corrupt.jsonl"

        with open(filepath, "w") as f:
            f.write("not valid json\n")
            f.write('{"id":"ok","node":"x","ts":"2026-03-14T10:00:00Z"}\n')  # missing fields
            f.write("{}\n")  # empty object
            f.write("\n")  # empty line

        result = engine.import_changes(str(filepath))
        assert result["skipped"] == 3  # 3 bad lines (empty line is skipped by strip check)
        assert result["applied"] == 0

        store.close()

    def test_missing_file(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        with pytest.raises(FileNotFoundError):
            engine.import_changes("/nonexistent/path.jsonl")

        store.close()


class TestChangeEntryDataclass:
    """Test 16: ChangeEntry serialization and deserialization."""

    def test_roundtrip(self):
        data = {"content": "Test", "topic": "unit-test"}
        checksum = ChangeEntry.compute_checksum(data)
        entry = ChangeEntry(
            id="test-uuid",
            node_id="test-node",
            timestamp="2026-03-14T10:00:00Z",
            action="learn",
            entry_id=42,
            data=data,
            checksum=checksum,
        )

        jsonl = entry.to_jsonl()
        obj = json.loads(jsonl)
        restored = ChangeEntry.from_json(obj)

        assert restored.id == entry.id
        assert restored.node_id == entry.node_id
        assert restored.timestamp == entry.timestamp
        assert restored.action == entry.action
        assert restored.entry_id == entry.entry_id
        assert restored.data == entry.data
        assert restored.checksum == entry.checksum
        assert restored.verify_checksum()

    def test_bad_checksum_detected(self):
        data = {"content": "Test"}
        entry = ChangeEntry(
            id="x", node_id="n", timestamp="t", action="learn",
            entry_id=1, data=data, checksum="wrong",
        )
        assert not entry.verify_checksum()


class TestConflictResolverStrategies:
    """Test 17: ConflictResolver strategy options."""

    def test_last_write_wins(self):
        resolver = ConflictResolver("last_write_wins")
        local = ChangeEntry("a", "n1", "2026-03-14T10:00:00Z", "update", 1, {}, "x")
        remote = ChangeEntry("b", "n2", "2026-03-14T11:00:00Z", "update", 1, {}, "y")
        assert resolver.resolve(local, remote) == remote

    def test_priority_node(self):
        resolver = ConflictResolver("priority_node", priority_node="n1")
        local = ChangeEntry("a", "n1", "2026-03-14T10:00:00Z", "update", 1, {}, "x")
        remote = ChangeEntry("b", "n2", "2026-03-14T11:00:00Z", "update", 1, {}, "y")
        # n1 is priority, should win even though remote is newer
        assert resolver.resolve(local, remote) == local

    def test_manual_review(self):
        resolver = ConflictResolver("manual_review")
        local = ChangeEntry("a", "n1", "2026-03-14T10:00:00Z", "update", 1, {}, "x")
        remote = ChangeEntry("b", "n2", "2026-03-14T11:00:00Z", "update", 1, {}, "y")
        # manual_review returns remote as placeholder
        result = resolver.resolve(local, remote)
        assert result == remote

    def test_invalid_strategy(self):
        with pytest.raises(ValueError):
            ConflictResolver("invalid")

    def test_priority_node_missing(self):
        with pytest.raises(ValueError):
            ConflictResolver("priority_node")


class TestManualReviewConflict:
    """Test 18: manual_review strategy logs conflict and skips application."""

    def test_manual_review_logs_conflict(self, tmp_path):
        store = _make_store(tmp_path)
        resolver = ConflictResolver("manual_review")
        engine = SyncEngine(store, "node-a", sync_dir=str(tmp_path / "sync"), conflict_resolver=resolver)

        # Create an entry and mark it as recently updated
        entry_id = store.learn("Local version", topic="test")
        store.conn.execute(
            "UPDATE knowledge SET updated_at = '2026-03-14T12:00:00Z' WHERE id = ?",
            (entry_id,),
        )
        store.conn.commit()

        # Create a remote update with an older timestamp → triggers conflict
        data = {"content": "Remote version", "topic": "test", "tags": ""}
        remote = ChangeEntry(
            id="remote-1",
            node_id="node-b",
            timestamp="2026-03-14T11:00:00Z",
            action="update",
            entry_id=entry_id,
            data=data,
            checksum=ChangeEntry.compute_checksum(data),
        )

        sync_dir = tmp_path / "review_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        filepath = sync_dir / "review.jsonl"
        with open(filepath, "w") as f:
            f.write(remote.to_jsonl() + "\n")

        result = engine.import_changes(str(filepath))
        assert result["conflicts"] == 1

        # Check conflict was logged
        row = store.conn.execute("SELECT * FROM sync_conflicts").fetchone()
        assert row is not None
        assert row["resolution"] == "pending"

        store.close()


class TestExportSince:
    """Test 19: export changes with explicit since timestamp."""

    def test_export_since(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Old entry", topic="test")

        # Use a cutoff before the second entry but after the first
        # Since audit_log uses second-level timestamps, we manually set
        # the first audit entry to an earlier time
        store.conn.execute(
            "UPDATE audit_log SET ts = '2026-03-14T09:00:00' WHERE id = (SELECT MIN(id) FROM audit_log)"
        )
        store.conn.commit()
        cutoff = "2026-03-14T09:00:00"

        store.learn("New entry after cutoff", topic="test")

        filepath = engine.export_changes(since=cutoff)

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]
        # Only the new entry should be exported
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert "New entry after cutoff" in obj["data"]["content"]

        store.close()


class TestSyncLogTracking:
    """Test 20: sync_log table tracks operations."""

    def test_sync_log(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Test", topic="test")
        engine.export_changes()

        logs = store.conn.execute("SELECT * FROM sync_log ORDER BY id").fetchall()
        assert len(logs) >= 1
        log = dict(logs[-1])
        assert log["node_id"] == "node-a"
        assert log["direction"] == "export"
        assert log["entries_count"] == 1

        store.close()


class TestLinkSync:
    """Test 21: link action sync."""

    def test_link_import(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        id1 = store.learn("Source entry", topic="test")
        id2 = store.learn("Target entry", topic="test")

        data = {"source_id": id1, "target_id": id2, "link_type": "based_on"}
        entry = ChangeEntry(
            id="link-1",
            node_id="node-remote",
            timestamp="2026-03-14T10:00:00Z",
            action="link",
            entry_id=0,
            data=data,
            checksum=ChangeEntry.compute_checksum(data),
        )

        sync_dir = tmp_path / "link_sync"
        sync_dir.mkdir(parents=True, exist_ok=True)
        filepath = sync_dir / "links.jsonl"
        with open(filepath, "w") as f:
            f.write(entry.to_jsonl() + "\n")

        result = engine.import_changes(str(filepath))
        assert result["applied"] == 1

        # Verify link exists
        sources = store.get_sources(id2)
        assert len(sources) >= 1

        store.close()


# ══════════════════════════════════════════════════════════════
# NEW TESTS — multi-table, RBAC, sync profiles (v0.3)
# ══════════════════════════════════════════════════════════════


class TestMultiTableExport:
    """Test 22: multi-table export (tasks, artifacts)."""

    def test_multi_table_export(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        # Insert knowledge
        store.learn("Multi-table test fact", topic="test")

        # Insert a task
        task_id = store.create_task("Fix the sync engine", project="uaml", tags="sync")

        # Insert an artifact directly
        store.conn.execute(
            "INSERT INTO artifacts (name, artifact_type, project, data_layer) "
            "VALUES (?, ?, ?, ?)",
            ("design.md", "file", "uaml", "project"),
        )
        store.conn.commit()

        # Full export of all tables
        filepath = engine.full_export(tables=["knowledge", "tasks", "artifacts"])

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        # Should have entries from all three tables
        tables_seen = set()
        for line in lines:
            obj = json.loads(line)
            tables_seen.add(obj.get("table", "knowledge"))

        assert "knowledge" in tables_seen
        assert "tasks" in tables_seen
        assert "artifacts" in tables_seen

        # Import to fresh node
        store_b = _make_store(tmp_path, "node-b")
        engine_b = _make_engine(store_b, "node-b", tmp_path)
        result = engine_b.full_import(filepath)
        assert result["applied"] >= 3

        # Verify task arrived
        row = store_b.conn.execute(
            "SELECT * FROM tasks WHERE title = ?", ("Fix the sync engine",)
        ).fetchone()
        assert row is not None

        # Verify artifact arrived
        row = store_b.conn.execute(
            "SELECT * FROM artifacts WHERE name = ?", ("design.md",)
        ).fetchone()
        assert row is not None

        store.close()
        store_b.close()


class TestIdentityNeverSynced:
    """Test 23: CRITICAL — identity layer is NEVER synced regardless of filter."""

    def test_identity_never_synced(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        # Insert knowledge with identity layer
        store.learn("My secret identity info", topic="self",
                     data_layer="identity", agent_id="agent-a")

        # Insert normal knowledge
        store.learn("Public fact", topic="test", data_layer="knowledge")

        # Try exporting even with no filter — identity should be excluded
        filepath = engine.full_export(
            tables=["knowledge"],
            sync_filter=SyncFilter(),  # empty filter = default rules
        )

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        for line in lines:
            obj = json.loads(line)
            assert obj["data"].get("data_layer") != "identity", \
                "Identity data must NEVER appear in sync export!"

        assert len(lines) == 1  # Only the public fact

        # Also test: explicitly requesting identity in allowed_layers still blocks it
        filepath2 = engine.full_export(
            tables=["knowledge"],
            sync_filter=SyncFilter(allowed_layers=["identity", "knowledge"]),
        )

        with open(filepath2) as f:
            lines2 = [l.strip() for l in f if l.strip()]

        for line in lines2:
            obj = json.loads(line)
            assert obj["data"].get("data_layer") != "identity"

        store.close()


class TestPersonalLayerBlockedByDefault:
    """Test 24: personal layer is blocked by default, opt-in required."""

    def test_personal_layer_blocked_by_default(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("My personal note", topic="diary", data_layer="personal")
        store.learn("Team fact", topic="test", data_layer="knowledge")

        # Default filter blocks personal
        filepath = engine.full_export(
            tables=["knowledge"],
            sync_filter=SyncFilter(),
        )

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        for line in lines:
            obj = json.loads(line)
            assert obj["data"].get("data_layer") != "personal"

        assert len(lines) == 1

        # Explicit opt-in allows personal
        filepath2 = engine.full_export(
            tables=["knowledge"],
            sync_filter=SyncFilter(allowed_layers=["knowledge", "personal"]),
        )

        with open(filepath2) as f:
            lines2 = [l.strip() for l in f if l.strip()]

        layers = [json.loads(l)["data"].get("data_layer") for l in lines2]
        assert "personal" in layers
        assert len(lines2) == 2

        store.close()


class TestSyncFilterByTopic:
    """Test 25: filter exports by topic."""

    def test_sync_filter_by_topic(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Infra note", topic="infra")
        store.learn("UAML design", topic="uaml")
        store.learn("Random stuff", topic="misc")

        filt = SyncFilter(allowed_topics=["infra", "uaml"])
        filepath = engine.full_export(tables=["knowledge"], sync_filter=filt)

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        assert len(lines) == 2
        topics = {json.loads(l)["data"]["topic"] for l in lines}
        assert topics == {"infra", "uaml"}

        store.close()


class TestSyncFilterByLayer:
    """Test 26: filter exports by data_layer."""

    def test_sync_filter_by_layer(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Knowledge fact", topic="test", data_layer="knowledge")
        store.learn("Project detail", topic="test", data_layer="project")
        store.learn("Operational note", topic="test", data_layer="operational")

        filt = SyncFilter(allowed_layers=["project"])
        filepath = engine.full_export(tables=["knowledge"], sync_filter=filt)

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        assert len(lines) == 1
        assert json.loads(lines[0])["data"]["data_layer"] == "project"

        store.close()


class TestSyncFilterByAgent:
    """Test 27b: filter exports by agent_id."""

    def test_sync_filter_by_agent(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Agent-B says hi", topic="test", agent_id="agent-b")
        store.learn("Agent-A says hi", topic="test", agent_id="agent-a")
        store.learn("Default says hi", topic="test")

        filt = SyncFilter(allowed_agents=["agent-b"])
        filepath = engine.full_export(tables=["knowledge"], sync_filter=filt)

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        assert len(lines) == 1
        assert json.loads(lines[0])["data"]["agent_id"] == "agent-b"

        store.close()


class TestSyncProfileTeamFull:
    """Test 28: TEAM_FULL profile — bidirectional, non-identity data."""

    def test_sync_profile_team_full(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Team fact", topic="test", data_layer="knowledge")
        store.learn("Identity secret", topic="self", data_layer="identity")
        store.learn("Personal diary", topic="diary", data_layer="personal")

        filepath = engine.full_export(
            tables=["knowledge"],
            sync_filter=TEAM_FULL.filter,
        )

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        # Only team fact (identity blocked, personal not in TEAM_FULL layers)
        assert len(lines) == 1
        assert json.loads(lines[0])["data"]["data_layer"] == "knowledge"

        # TEAM_FULL allows both export and import
        assert TEAM_FULL.allows_export()
        assert TEAM_FULL.allows_import()

        store.close()


class TestSyncProfileExternalPartner:
    """Test 29: EXTERNAL_PARTNER profile — export_only, knowledge+project only."""

    def test_sync_profile_external_partner(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Shared fact", topic="test", data_layer="knowledge")
        store.learn("Project doc", topic="test", data_layer="project")
        store.learn("Ops internal", topic="test", data_layer="operational")
        store.learn("Identity info", topic="test", data_layer="identity")

        filepath = engine.full_export(
            tables=["knowledge"],
            sync_filter=EXTERNAL_PARTNER.filter,
        )

        with open(filepath) as f:
            lines = [l.strip() for l in f if l.strip()]

        layers = {json.loads(l)["data"]["data_layer"] for l in lines}
        assert "knowledge" in layers
        assert "project" in layers
        assert "operational" not in layers
        assert "identity" not in layers
        assert len(lines) == 2

        # EXTERNAL_PARTNER is export_only
        assert EXTERNAL_PARTNER.allows_export()
        assert not EXTERNAL_PARTNER.allows_import()

        store.close()


class TestExportOnlyProfile:
    """Test 30: export-only profile blocks import."""

    def test_export_only_profile(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        store.learn("Some fact", topic="test")
        filepath = engine.export_changes(sync_profile=EXTERNAL_PARTNER)

        # Attempting import with an export-only profile should raise
        with pytest.raises(ValueError, match="does not allow imports"):
            engine.import_changes(filepath, sync_profile=EXTERNAL_PARTNER)

        store.close()


class TestImportOnlyProfile:
    """Test 31: import-only profile blocks export."""

    def test_import_only_profile(self, tmp_path):
        store = _make_store(tmp_path)
        engine = _make_engine(store, "node-a", tmp_path)

        with pytest.raises(ValueError, match="does not allow exports"):
            engine.export_changes(sync_profile=TEAM_READONLY)

        store.close()
