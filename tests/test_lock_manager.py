"""Tests for uaml.sync — Task Claim Protocol with Optimistic Locking.

© 2026 Ladislav Zamazal / GLG, a.s.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.sync import (
    LockManager,
    SyncEngine,
    TaskClaim,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_store(tmp_path: Path, name: str = "test") -> MemoryStore:
    """Create a fresh MemoryStore in a temp directory."""
    db_path = tmp_path / f"{name}.db"
    return MemoryStore(
        str(db_path), agent_id=name,
        ethics_mode="off", contradiction_mode="off",
    )


def _make_lock_manager(
    tmp_path: Path,
    node_id: str = "node-a",
    store: MemoryStore | None = None,
    **kwargs,
) -> LockManager:
    """Create a LockManager with a temp DB."""
    if store is None:
        store = _make_store(tmp_path, node_id)
    return LockManager(store, node_id=node_id, **kwargs)


def _make_engine(store: MemoryStore, node_id: str, tmp_path: Path) -> SyncEngine:
    """Create a SyncEngine with a temp sync directory."""
    sync_dir = tmp_path / "sync" / node_id
    return SyncEngine(store, node_id=node_id, sync_dir=str(sync_dir))


# ── Tests ────────────────────────────────────────────────────

class TestClaimCreatesPending:
    """Test that claim() creates a pending TaskClaim."""

    def test_claim_creates_pending(self, tmp_path):
        lm = _make_lock_manager(tmp_path)
        claim = lm.claim("task-42")

        assert claim.status == "pending"
        assert claim.task_id == "task-42"
        assert claim.node_id == "node-a"
        assert claim.claim_id  # non-empty UUID
        assert claim.expires_at  # non-empty

        # Verify in DB
        row = lm.store.conn.execute(
            "SELECT * FROM task_locks WHERE id = ?", (claim.claim_id,)
        ).fetchone()
        assert row is not None
        assert dict(row)["status"] == "pending"

        # Verify intent stored
        intent = lm.store.conn.execute(
            "SELECT * FROM lock_intents WHERE claim_id = ?", (claim.claim_id,)
        ).fetchone()
        assert intent is not None
        lm.store.close()


class TestConfirmNoConflict:
    """Test that confirm() succeeds when there's no competition."""

    def test_confirm_no_conflict(self, tmp_path):
        lm = _make_lock_manager(tmp_path)
        claim = lm.claim("task-42")

        result = lm.confirm(claim.claim_id)
        assert result is True

        # Verify in DB
        row = lm.store.conn.execute(
            "SELECT * FROM task_locks WHERE id = ?", (claim.claim_id,)
        ).fetchone()
        assert dict(row)["status"] == "confirmed"
        assert dict(row)["confirmed_at"] is not None
        lm.store.close()


class TestConfirmWithLowerPriorityRejected:
    """Test that a lower-priority claim is rejected when competing."""

    def test_confirm_with_lower_priority_rejected(self, tmp_path):
        store = _make_store(tmp_path, "shared")
        lm_a = LockManager(store, node_id="node-a")

        # Node A claims with low priority
        claim_a = lm_a.claim("task-42", priority=1)

        # Simulate node B's higher-priority intent arriving
        now = datetime.now(timezone.utc).isoformat()
        store.conn.execute(
            """INSERT INTO lock_intents
               (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            ("claim-b-id", "task-42", "node-b", now, 2000, 5),
        )
        store.conn.commit()

        # Node A tries to confirm — should be rejected (node-b has priority 5)
        result = lm_a.confirm(claim_a.claim_id)
        assert result is False

        row = store.conn.execute(
            "SELECT status FROM task_locks WHERE id = ?", (claim_a.claim_id,)
        ).fetchone()
        assert dict(row)["status"] == "rejected"
        store.close()


class TestConfirmWithHigherPriorityWins:
    """Test that a higher-priority claim wins over lower."""

    def test_confirm_with_higher_priority_wins(self, tmp_path):
        store = _make_store(tmp_path, "shared")
        lm_a = LockManager(store, node_id="node-a")

        # Node A claims with high priority
        claim_a = lm_a.claim("task-42", priority=10)

        # Simulate node B's lower-priority intent
        now = datetime.now(timezone.utc).isoformat()
        store.conn.execute(
            """INSERT INTO lock_intents
               (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            ("claim-b-id", "task-42", "node-b", now, 2000, 1),
        )
        store.conn.commit()

        # Node A confirms — should win (higher priority)
        result = lm_a.confirm(claim_a.claim_id)
        assert result is True

        row = store.conn.execute(
            "SELECT status FROM task_locks WHERE id = ?", (claim_a.claim_id,)
        ).fetchone()
        assert dict(row)["status"] == "confirmed"
        store.close()


class TestSamePriorityEarlierTimestampWins:
    """Test that with equal priority, earlier timestamp wins."""

    def test_same_priority_earlier_timestamp_wins(self, tmp_path):
        store = _make_store(tmp_path, "shared")
        lm_a = LockManager(store, node_id="node-a")

        # Node A claims
        claim_a = lm_a.claim("task-42", priority=5)

        # Simulate node B's later claim with same priority
        later = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
        store.conn.execute(
            """INSERT INTO lock_intents
               (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            ("claim-b-id", "task-42", "node-b", later, 2000, 5),
        )
        store.conn.commit()

        # Node A (earlier) should win
        result = lm_a.confirm(claim_a.claim_id)
        assert result is True
        store.close()


class TestReleaseLock:
    """Test releasing a confirmed lock."""

    def test_release_lock(self, tmp_path):
        lm = _make_lock_manager(tmp_path)
        claim = lm.claim("task-42")
        lm.confirm(claim.claim_id)

        result = lm.release("task-42")
        assert result is True

        row = lm.store.conn.execute(
            "SELECT status, released_at FROM task_locks WHERE id = ?",
            (claim.claim_id,),
        ).fetchone()
        r = dict(row)
        assert r["status"] == "released"
        assert r["released_at"] is not None

        # Releasing again should fail
        result2 = lm.release("task-42")
        assert result2 is False
        lm.store.close()


class TestIsLockedReturnsInfo:
    """Test is_locked returns lock info for confirmed lock."""

    def test_is_locked_returns_info(self, tmp_path):
        lm = _make_lock_manager(tmp_path)
        claim = lm.claim("task-42")
        lm.confirm(claim.claim_id)

        info = lm.is_locked("task-42")
        assert info is not None
        assert info["task_id"] == "task-42"
        assert info["node_id"] == "node-a"
        assert info["status"] == "confirmed"
        lm.store.close()


class TestIsLockedReturnsNone:
    """Test is_locked returns None for unlocked task."""

    def test_is_locked_returns_none(self, tmp_path):
        lm = _make_lock_manager(tmp_path)

        info = lm.is_locked("task-99")
        assert info is None

        # Pending (unconfirmed) claim should also return None
        lm.claim("task-99")
        info = lm.is_locked("task-99")
        assert info is None
        lm.store.close()


class TestActiveLocksList:
    """Test listing active locks."""

    def test_active_locks_list(self, tmp_path):
        lm = _make_lock_manager(tmp_path)

        # Create and confirm two locks
        c1 = lm.claim("task-1")
        lm.confirm(c1.claim_id)
        c2 = lm.claim("task-2")
        lm.confirm(c2.claim_id)
        # Pending lock (should not appear)
        lm.claim("task-3")

        active = lm.active_locks()
        assert len(active) == 2
        task_ids = {l["task_id"] for l in active}
        assert task_ids == {"task-1", "task-2"}
        lm.store.close()


class TestExpiredLockCleanup:
    """Test cleanup of expired locks."""

    def test_expired_lock_cleanup(self, tmp_path):
        store = _make_store(tmp_path, "node-a")
        # Use very short lock duration so it expires immediately
        lm = LockManager(store, node_id="node-a", lock_duration_minutes=0)

        claim = lm.claim("task-42")
        lm.confirm(claim.claim_id)

        # Lock should be expired now (0-minute duration)
        time.sleep(0.1)  # ensure time passes

        expired = lm.expired_locks()
        assert len(expired) >= 1

        count = lm.cleanup_expired()
        assert count >= 1

        # Should no longer be active
        active = lm.active_locks()
        assert len(active) == 0

        row = store.conn.execute(
            "SELECT status FROM task_locks WHERE id = ?", (claim.claim_id,)
        ).fetchone()
        assert dict(row)["status"] == "expired"
        store.close()


class TestTwoNodesClaimSameTask:
    """Test two nodes claiming the same task — higher priority wins."""

    def test_two_nodes_claim_same_task(self, tmp_path):
        # Each node has its own store (distributed scenario)
        store_a = _make_store(tmp_path, "node-a")
        store_b = _make_store(tmp_path, "node-b")
        lm_a = LockManager(store_a, node_id="node-a")
        lm_b = LockManager(store_b, node_id="node-b")

        # Both claim the same task
        claim_a = lm_a.claim("task-42", priority=3)
        claim_b = lm_b.claim("task-42", priority=7)

        # Simulate intent exchange: inject B's intent into A's DB
        store_a.conn.execute(
            """INSERT INTO lock_intents
               (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (claim_b.claim_id, "task-42", "node-b",
             claim_b.timestamp, 2000, 7),
        )
        store_a.conn.commit()

        # Inject A's intent into B's DB
        store_b.conn.execute(
            """INSERT INTO lock_intents
               (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (claim_a.claim_id, "task-42", "node-a",
             claim_a.timestamp, 2000, 3),
        )
        store_b.conn.commit()

        # Node A tries to confirm — should lose (lower priority)
        result_a = lm_a.confirm(claim_a.claim_id)
        assert result_a is False

        # Node B tries to confirm — should win (higher priority)
        result_b = lm_b.confirm(claim_b.claim_id)
        assert result_b is True

        store_a.close()
        store_b.close()


class TestOfflineConflictDetection:
    """Test offline conflict detection via import_lock_intents."""

    def test_offline_conflict_detection(self, tmp_path):
        store = _make_store(tmp_path, "node-a")
        lm = LockManager(store, node_id="node-a")
        engine = _make_engine(store, "node-a", tmp_path)

        # Ensure lock tables exist in engine's store
        store.conn.executescript(
            "CREATE TABLE IF NOT EXISTS task_locks ("
            "id TEXT PRIMARY KEY, task_id TEXT, node_id TEXT, "
            "status TEXT DEFAULT 'pending', claimed_at TEXT, "
            "confirmed_at TEXT, released_at TEXT, expires_at TEXT, "
            "priority INTEGER DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS lock_intents ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT, "
            "task_id TEXT, node_id TEXT, timestamp TEXT, "
            "timeout_ms INTEGER DEFAULT 2000, priority INTEGER DEFAULT 0, "
            "resolved INTEGER DEFAULT 0);"
        )

        # Node A claims and confirms locally (offline)
        claim_a = lm.claim("task-42", priority=3)
        lm.confirm(claim_a.claim_id)

        # Simulate remote node B's exported intents file
        remote_ts = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        remote_intent = {
            "id": "remote-claim-b",
            "node": "node-b",
            "ts": remote_ts,
            "action": "claim",
            "entry_id": 0,
            "data": {
                "claim_id": "remote-claim-b",
                "task_id": "task-42",
                "node_id": "node-b",
                "timeout_ms": 2000,
                "priority": 10,  # Higher priority than node-a
            },
            "checksum": "dummy",
            "table": "lock_intents",
        }
        intent_file = tmp_path / "remote_intents.jsonl"
        with open(intent_file, "w") as f:
            f.write(json.dumps(remote_intent) + "\n")

        # Import — should detect conflict and remote wins
        result = engine.import_lock_intents(str(intent_file))
        assert result["imported"] == 1
        assert result["conflicts"] == 1
        assert len(result["conflict_details"]) == 1
        assert result["conflict_details"][0]["winner"] == "node-b"

        # Local lock should be rejected
        row = store.conn.execute(
            "SELECT status FROM task_locks WHERE id = ?", (claim_a.claim_id,)
        ).fetchone()
        assert dict(row)["status"] == "rejected"
        store.close()


class TestLockIntentExportImport:
    """Test export and import of lock intents via SyncEngine."""

    def test_lock_intent_export_import(self, tmp_path):
        # Node A: create store, lock manager, engine
        store_a = _make_store(tmp_path, "node-a")
        lm_a = LockManager(store_a, node_id="node-a")
        engine_a = _make_engine(store_a, "node-a", tmp_path)

        # Node A claims
        claim = lm_a.claim("task-100", priority=5)

        # Export lock intents
        export_path = engine_a.export_lock_intents()
        assert Path(export_path).exists()

        # Read and verify JSONL content
        with open(export_path) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1

        obj = json.loads(lines[0])
        assert obj["data"]["task_id"] == "task-100"
        assert obj["data"]["claim_id"] == claim.claim_id

        # Node B: import the intents
        store_b = _make_store(tmp_path, "node-b")
        LockManager(store_b, node_id="node-b")  # ensures tables exist
        engine_b = _make_engine(store_b, "node-b", tmp_path)

        result = engine_b.import_lock_intents(export_path)
        assert result["imported"] == 1
        assert result["conflicts"] == 0

        # Verify intent is in node-b's DB
        intent = store_b.conn.execute(
            "SELECT * FROM lock_intents WHERE claim_id = ?", (claim.claim_id,)
        ).fetchone()
        assert intent is not None

        store_a.close()
        store_b.close()


class TestClaimAlreadyLockedTask:
    """Test claiming a task that's already locked by another node."""

    def test_claim_already_locked_task(self, tmp_path):
        store = _make_store(tmp_path, "shared")
        lm_a = LockManager(store, node_id="node-a")

        # Node A claims and confirms
        claim_a = lm_a.claim("task-42", priority=5)
        lm_a.confirm(claim_a.claim_id)

        # Node B tries to claim same task (simulated via same DB)
        lm_b = LockManager(store, node_id="node-b")
        claim_b = lm_b.claim("task-42", priority=3)

        # Node B tries to confirm — node A's intent is still there (resolved=1)
        # But the lock itself is confirmed, so B should still be able to create a
        # pending claim. The confirm should succeed since A's intent is resolved.
        # However, if we check active locks, A's lock is there.
        info = lm_b.is_locked("task-42")
        assert info is not None
        assert info["node_id"] == "node-a"
        store.close()


class TestResolveConflictTiebreak:
    """Test resolve_conflict with various tiebreak scenarios."""

    def test_resolve_conflict_tiebreak(self, tmp_path):
        store = _make_store(tmp_path, "test")
        lm = LockManager(store, node_id="test")

        # Test 1: Higher priority wins
        claims = [
            TaskClaim(claim_id="c1", task_id="t1", node_id="a",
                      timestamp="2026-01-01T00:00:00", priority=1),
            TaskClaim(claim_id="c2", task_id="t1", node_id="b",
                      timestamp="2026-01-01T00:00:00", priority=5),
        ]
        winner = lm.resolve_conflict(claims)
        assert winner.claim_id == "c2"  # higher priority

        # Test 2: Same priority, earlier timestamp wins
        claims = [
            TaskClaim(claim_id="c1", task_id="t1", node_id="a",
                      timestamp="2026-01-01T00:00:05", priority=5),
            TaskClaim(claim_id="c2", task_id="t1", node_id="b",
                      timestamp="2026-01-01T00:00:00", priority=5),
        ]
        winner = lm.resolve_conflict(claims)
        assert winner.claim_id == "c2"  # earlier timestamp

        # Test 3: Same priority, same timestamp — lexicographic node_id
        claims = [
            TaskClaim(claim_id="c1", task_id="t1", node_id="node-b",
                      timestamp="2026-01-01T00:00:00", priority=5),
            TaskClaim(claim_id="c2", task_id="t1", node_id="node-a",
                      timestamp="2026-01-01T00:00:00", priority=5),
        ]
        winner = lm.resolve_conflict(claims)
        assert winner.claim_id == "c2"  # "node-a" < "node-b"

        # Test 4: Single claim returns itself
        single = [TaskClaim(claim_id="only", task_id="t1", node_id="x")]
        winner = lm.resolve_conflict(single)
        assert winner.claim_id == "only"

        # Test 5: Three-way conflict
        claims = [
            TaskClaim(claim_id="c1", task_id="t1", node_id="a",
                      timestamp="2026-01-01T00:00:00", priority=3),
            TaskClaim(claim_id="c2", task_id="t1", node_id="b",
                      timestamp="2026-01-01T00:00:00", priority=7),
            TaskClaim(claim_id="c3", task_id="t1", node_id="c",
                      timestamp="2026-01-01T00:00:00", priority=5),
        ]
        winner = lm.resolve_conflict(claims)
        assert winner.claim_id == "c2"  # highest priority
        store.close()


class TestTaskClaimDataclass:
    """Test TaskClaim to_dict/from_dict round-trip."""

    def test_to_dict_from_dict(self):
        claim = TaskClaim(
            claim_id="test-uuid",
            task_id="task-42",
            node_id="node-a",
            timestamp="2026-03-14T10:00:00+00:00",
            status="confirmed",
            timeout_ms=3000,
            priority=5,
            expires_at="2026-03-14T11:00:00+00:00",
        )
        d = claim.to_dict()
        assert d["claim_id"] == "test-uuid"
        assert d["priority"] == 5

        restored = TaskClaim.from_dict(d)
        assert restored.claim_id == claim.claim_id
        assert restored.task_id == claim.task_id
        assert restored.priority == claim.priority
        assert restored.status == claim.status
