# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Sync — JSON changelog-based synchronization for distributed teams.

Core concept:
  - Each node maintains a local SQLite DB (via MemoryStore)
  - Changes are exported as JSONL changelogs (delta since last sync)
  - Import merges changelogs with conflict resolution
  - Works offline — changelogs accumulate, sync on reconnect
  - Git-friendly — JSONL files are text, mergeable, diffable

Usage:
    from uaml import MemoryStore
    from uaml.sync import SyncEngine

    store = MemoryStore("memory.db")
    engine = SyncEngine(store, node_id="metod-vps", sync_dir="sync/")

    # Export changes since last sync
    path = engine.export_changes()

    # Import changes from another node
    result = engine.import_changes("sync/cyril-notebook_2026-03-14T10:00:00Z.jsonl")
    # => {"applied": 5, "conflicts": 1, "skipped": 2}

© 2026 Ladislav Zamazal / GLG, a.s.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from uaml.core.store import MemoryStore


# ── Multi-table sync configuration ──────────────────────────

# Columns to export/import per table.  Only these columns are serialized
# into the JSONL changelog; primary keys and auto-generated timestamps
# are handled by the import logic.

TABLE_COLUMNS: dict[str, list[str]] = {
    "knowledge": [
        "content", "topic", "tags", "summary", "source_type", "source_ref",
        "confidence", "access_level", "trust_level", "data_layer",
        "source_origin", "agent_id", "project", "client_ref",
    ],
    "source_links": [
        "source_id", "target_id", "link_type", "confidence", "notes",
    ],
    "artifacts": [
        "name", "artifact_type", "path", "status", "source_origin",
        "project", "task_id", "client_ref", "mime_type", "size_bytes",
        "checksum", "data_layer",
    ],
    "tasks": [
        "title", "description", "status", "project", "assigned_to",
        "priority", "tags", "due_date", "parent_id", "client_ref",
        "data_layer", "completed_at",
    ],
    "entities": [
        "name", "entity_type", "properties", "source_entry_id",
    ],
    "entity_mentions": [
        "entity_id", "entry_id", "mention_type",
    ],
    "knowledge_relations": [
        "source_id", "target_id", "relation_type", "confidence",
    ],
    "session_summaries": [
        "session_id", "agent_id", "summary", "message_count",
        "start_time", "end_time",
    ],
}

# Tables that have a data_layer column (used for RBAC filtering)
_LAYER_TABLES = {"knowledge", "tasks", "artifacts"}

# Tables that have a topic column
_TOPIC_TABLES = {"knowledge"}

# Tables that have an agent_id column
_AGENT_TABLES = {"knowledge", "session_summaries"}

# Tables that have a tags column
_TAGS_TABLES = {"knowledge", "tasks"}

# Default set of all syncable tables
ALL_SYNC_TABLES: list[str] = list(TABLE_COLUMNS.keys())


# ── RBAC filtering ───────────────────────────────────────────

@dataclass
class SyncFilter:
    """Role-Based Access Control filter for sync exports.

    Restricts which rows are included in a sync changelog based on
    data layer, topic, agent, and tags.

    SECURITY INVARIANTS (never overridable):
      - Entries with data_layer='identity' are NEVER synced.
      - Entries with data_layer='personal' require explicit opt-in
        (must be listed in ``allowed_layers``).
    """

    allowed_layers: Optional[list[str]] = None
    allowed_topics: Optional[list[str]] = None
    allowed_agents: Optional[list[str]] = None
    allowed_tags: Optional[list[str]] = None

    def accepts(self, row: dict, table: str) -> bool:
        """Return True if *row* from *table* passes this filter."""
        # ── Hard security rules (identity NEVER, personal opt-in) ──
        data_layer = row.get("data_layer")
        if data_layer == "identity":
            return False  # NEVER sync identity data
        if data_layer == "personal":
            if self.allowed_layers is None or "personal" not in self.allowed_layers:
                return False  # personal blocked unless explicitly opted-in

        # ── Layer filter (only for tables that carry data_layer) ──
        if self.allowed_layers is not None and table in _LAYER_TABLES:
            if data_layer and data_layer not in self.allowed_layers:
                return False

        # ── Topic filter ──
        if self.allowed_topics is not None and table in _TOPIC_TABLES:
            topic = row.get("topic", "")
            if topic not in self.allowed_topics:
                return False

        # ── Agent filter ──
        if self.allowed_agents is not None and table in _AGENT_TABLES:
            agent_id = row.get("agent_id", "")
            if agent_id not in self.allowed_agents:
                return False

        # ── Tags filter (entry must have at least one matching tag) ──
        if self.allowed_tags is not None and table in _TAGS_TABLES:
            raw_tags = row.get("tags", "")
            entry_tags = {t.strip() for t in raw_tags.split(",") if t.strip()} if raw_tags else set()
            if not entry_tags.intersection(self.allowed_tags):
                return False

        return True


# ── Sync profiles ────────────────────────────────────────────

@dataclass
class SyncProfile:
    """Named sync configuration combining filter, direction, and conflict strategy."""

    name: str
    filter: SyncFilter
    direction: str = "bidirectional"       # bidirectional | export_only | import_only
    conflict_strategy: str = "last_write_wins"

    def allows_export(self) -> bool:
        return self.direction in ("bidirectional", "export_only")

    def allows_import(self) -> bool:
        return self.direction in ("bidirectional", "import_only")


# Pre-built profiles
TEAM_FULL = SyncProfile(
    name="team-full",
    filter=SyncFilter(allowed_layers=["knowledge", "team", "operational", "project"]),
    direction="bidirectional",
    conflict_strategy="last_write_wins",
)

TEAM_READONLY = SyncProfile(
    name="team-readonly",
    filter=SyncFilter(allowed_layers=["knowledge", "team", "operational", "project"]),
    direction="import_only",
    conflict_strategy="last_write_wins",
)

EXTERNAL_PARTNER = SyncProfile(
    name="external-partner",
    filter=SyncFilter(allowed_layers=["knowledge", "project"]),
    direction="export_only",
    conflict_strategy="last_write_wins",
)

ADMIN = SyncProfile(
    name="admin",
    filter=SyncFilter(allowed_layers=["knowledge", "team", "operational", "project", "personal"]),
    direction="bidirectional",
    conflict_strategy="last_write_wins",
)


# ── Sync table schema ────────────────────────────────────────

SYNC_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    entries_count INTEGER DEFAULT 0,
    conflicts_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_state (
    node_id TEXT PRIMARY KEY,
    last_sync_ts TEXT,
    last_export_ts TEXT
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_entry_id INTEGER,
    remote_entry_id INTEGER,
    local_data TEXT,
    remote_data TEXT,
    resolution TEXT,
    resolved_at TEXT
);
"""


# ── Data classes ─────────────────────────────────────────────

@dataclass
class ChangeEntry:
    """A single change in a JSONL changelog."""

    id: str
    node_id: str
    timestamp: str
    action: str
    entry_id: int
    data: dict
    checksum: str
    table: str = "knowledge"  # multi-table support (v0.3)

    @staticmethod
    def compute_checksum(data: dict) -> str:
        """Compute SHA-256 checksum of data dict."""
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def verify_checksum(self) -> bool:
        """Verify the checksum matches the data."""
        return self.checksum == self.compute_checksum(self.data)

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        obj: dict = {
            "id": self.id,
            "node": self.node_id,
            "ts": self.timestamp,
            "action": self.action,
            "entry_id": self.entry_id,
            "data": self.data,
            "checksum": self.checksum,
        }
        if self.table != "knowledge":
            obj["table"] = self.table
        return json.dumps(obj, ensure_ascii=False)

    @classmethod
    def from_json(cls, obj: dict) -> "ChangeEntry":
        """Deserialize from a parsed JSON object."""
        required = {"id", "node", "ts", "action", "entry_id", "data", "checksum"}
        missing = required - set(obj.keys())
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        return cls(
            id=obj["id"],
            node_id=obj["node"],
            timestamp=obj["ts"],
            action=obj["action"],
            entry_id=obj["entry_id"],
            data=obj["data"],
            checksum=obj["checksum"],
            table=obj.get("table", "knowledge"),
        )


# ── Conflict resolution ─────────────────────────────────────

class ConflictResolver:
    """Handles merge conflicts during sync import.

    Strategies:
      - last_write_wins: newer timestamp wins (default)
      - priority_node: specified node always wins
      - manual_review: log conflict, skip application
    """

    def __init__(
        self,
        strategy: str = "last_write_wins",
        priority_node: Optional[str] = None,
    ):
        if strategy not in ("last_write_wins", "priority_node", "manual_review"):
            raise ValueError(f"Unknown strategy: {strategy}")
        if strategy == "priority_node" and not priority_node:
            raise ValueError("priority_node strategy requires priority_node parameter")
        self.strategy = strategy
        self.priority_node = priority_node

    def resolve(
        self, local: ChangeEntry, remote: ChangeEntry
    ) -> ChangeEntry:
        """Resolve a conflict between local and remote changes.

        Returns the winning ChangeEntry.
        """
        if self.strategy == "last_write_wins":
            # Compare ISO 8601 timestamps lexicographically (works for UTC)
            if remote.timestamp >= local.timestamp:
                return remote
            return local

        if self.strategy == "priority_node":
            if remote.node_id == self.priority_node:
                return remote
            if local.node_id == self.priority_node:
                return local
            # Neither is priority — fall back to last-write-wins
            return remote if remote.timestamp >= local.timestamp else local

        # manual_review — caller should handle; return remote as placeholder
        return remote


# ── Sync engine ──────────────────────────────────────────────

class SyncEngine:
    """Main synchronization engine.

    Exports changes from audit_log as JSONL changelogs,
    imports changelogs with conflict resolution.
    """

    VALID_ACTIONS = {"learn", "update", "delete", "tag", "link"}

    def __init__(
        self,
        store: MemoryStore,
        node_id: str,
        sync_dir: str = "sync/",
        conflict_resolver: Optional[ConflictResolver] = None,
    ):
        self.store = store
        self.node_id = node_id
        self.sync_dir = Path(sync_dir)
        self.resolver = conflict_resolver or ConflictResolver()
        self._ensure_sync_tables()

    def _ensure_sync_tables(self) -> None:
        """Create sync-specific tables if they don't exist."""
        self.store.conn.executescript(SYNC_SCHEMA_SQL)
        self.store.conn.commit()

    # ── Export ────────────────────────────────────────────────

    def export_changes(
        self,
        since: Optional[str] = None,
        *,
        tables: Optional[list[str]] = None,
        sync_filter: Optional[SyncFilter] = None,
        sync_profile: Optional[SyncProfile] = None,
    ) -> str:
        """Export changes since timestamp as a JSONL file.

        Args:
            since: ISO 8601 timestamp. If None, uses last export timestamp
                   for this node (or exports all if no previous export).
            tables: List of table names to export. Defaults to ALL_SYNC_TABLES.
            sync_filter: Optional RBAC filter to restrict exported rows.
            sync_profile: Optional sync profile (overrides filter/direction).

        Returns:
            Filepath of the generated JSONL changelog.
        """
        if sync_profile is not None:
            if not sync_profile.allows_export():
                raise ValueError(
                    f"Profile '{sync_profile.name}' does not allow exports "
                    f"(direction={sync_profile.direction})"
                )
            sync_filter = sync_profile.filter

        target_tables = set(tables or ALL_SYNC_TABLES)

        if since is None:
            row = self.store.conn.execute(
                "SELECT last_export_ts FROM sync_state WHERE node_id = ?",
                (self.node_id,),
            ).fetchone()
            since = row["last_export_ts"] if row and row["last_export_ts"] else None

        # Query audit_log for changes since timestamp
        if since:
            rows = self.store.conn.execute(
                "SELECT * FROM audit_log WHERE ts > ? ORDER BY ts ASC",
                (since,),
            ).fetchall()
        else:
            rows = self.store.conn.execute(
                "SELECT * FROM audit_log ORDER BY ts ASC"
            ).fetchall()

        entries = []
        for row in rows:
            change = self._audit_to_change(dict(row), target_tables=target_tables)
            if change:
                # Apply RBAC filter
                if sync_filter and not sync_filter.accepts(change.data, change.table):
                    continue
                entries.append(change)

        # Write JSONL
        now = datetime.now(timezone.utc).isoformat()
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = now.replace(":", "-")
        filename = f"{self.node_id}_{safe_ts}.jsonl"
        filepath = self.sync_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(entry.to_jsonl() + "\n")

        # Update sync state
        self.store.conn.execute(
            """INSERT INTO sync_state (node_id, last_export_ts)
               VALUES (?, ?)
               ON CONFLICT(node_id) DO UPDATE SET last_export_ts = ?""",
            (self.node_id, now, now),
        )
        # Log export
        self.store.conn.execute(
            """INSERT INTO sync_log (node_id, direction, timestamp, entries_count, conflicts_count)
               VALUES (?, 'export', ?, ?, 0)""",
            (self.node_id, now, len(entries)),
        )
        self.store.conn.commit()

        return str(filepath)

    def _audit_to_change(
        self,
        audit: dict,
        *,
        target_tables: Optional[set[str]] = None,
    ) -> Optional[ChangeEntry]:
        """Convert an audit_log row to a ChangeEntry.

        Reads current state of the target entry for the data payload.
        Supports multi-table via *target_tables* filter.
        """
        action_raw = audit.get("action", "")
        # Parse action — format is "action|details" or just "action"
        action = action_raw.split("|")[0].strip()

        if action not in self.VALID_ACTIONS:
            return None

        target_table = audit.get("target_table", "")
        target_id = audit.get("target_id", 0)

        if not target_id:
            return None

        # Filter to requested tables (default: knowledge only for backward compat)
        allowed = target_tables or {"knowledge"}
        if target_table not in allowed:
            return None

        # Ensure the table is in our column config
        if target_table not in TABLE_COLUMNS:
            return None

        # Build data payload from current DB state
        data: dict = {}
        if action in ("learn", "update", "tag"):
            row = self.store.conn.execute(
                f"SELECT * FROM {target_table} WHERE id = ?", (target_id,)
            ).fetchone()
            if row:
                r = dict(row)
                cols = TABLE_COLUMNS[target_table]
                data = {col: r.get(col) for col in cols if col in r}
            else:
                # Entry was deleted after the audit — skip
                return None
        elif action == "delete":
            data = {"deleted": True}
        elif action == "link":
            data = {"link_action": action_raw}

        checksum = ChangeEntry.compute_checksum(data)

        return ChangeEntry(
            id=str(uuid.uuid4()),
            node_id=self.node_id,
            timestamp=audit.get("ts", datetime.now(timezone.utc).isoformat()),
            action=action,
            entry_id=target_id,
            data=data,
            checksum=checksum,
            table=target_table,
        )

    # ── Import ────────────────────────────────────────────────

    def import_changes(
        self,
        filepath: str,
        *,
        tables: Optional[list[str]] = None,
        sync_filter: Optional[SyncFilter] = None,
        sync_profile: Optional[SyncProfile] = None,
    ) -> dict:
        """Import a JSONL changelog file.

        Args:
            filepath: Path to the JSONL changelog.
            tables: Restrict import to these tables. Defaults to all.
            sync_filter: Optional RBAC filter.
            sync_profile: Optional sync profile (overrides filter/direction).

        Returns:
            {"applied": N, "conflicts": N, "skipped": N}
        """
        if sync_profile is not None:
            if not sync_profile.allows_import():
                raise ValueError(
                    f"Profile '{sync_profile.name}' does not allow imports "
                    f"(direction={sync_profile.direction})"
                )
            sync_filter = sync_profile.filter

        target_tables = set(tables) if tables else None

        result = {"applied": 0, "conflicts": 0, "skipped": 0}
        entries: list[ChangeEntry] = []

        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    entry = ChangeEntry.from_json(obj)
                    entries.append(entry)
                except (json.JSONDecodeError, ValueError) as e:
                    result["skipped"] += 1
                    continue

        # Deduplicate: skip entries we've already imported (by change ID)
        for entry in entries:
            if not entry.verify_checksum():
                result["skipped"] += 1
                continue

            # Table filter
            if target_tables and entry.table not in target_tables:
                result["skipped"] += 1
                continue

            # RBAC filter
            if sync_filter and not sync_filter.accepts(entry.data, entry.table):
                result["skipped"] += 1
                continue

            # Check if already imported (by change UUID in sync_log details or
            # by matching content_hash for learn actions)
            if self._is_duplicate(entry):
                result["skipped"] += 1
                continue

            # Apply change
            outcome = self._apply_change(entry)
            if outcome == "applied":
                result["applied"] += 1
            elif outcome == "conflict":
                result["conflicts"] += 1
            else:
                result["skipped"] += 1

        # Extract remote node from entries
        remote_node = entries[0].node_id if entries else "unknown"
        now = datetime.now(timezone.utc).isoformat()

        # Update sync state
        if entries:
            self.set_last_sync(remote_node, now)

        # Log import
        self.store.conn.execute(
            """INSERT INTO sync_log (node_id, direction, timestamp, entries_count, conflicts_count)
               VALUES (?, 'import', ?, ?, ?)""",
            (remote_node, now, result["applied"], result["conflicts"]),
        )
        self.store.conn.commit()

        return result

    def _is_duplicate(self, entry: ChangeEntry) -> bool:
        """Check if a change entry has already been imported."""
        # For learn actions: check content_hash
        if entry.action == "learn" and "content" in entry.data:
            content = entry.data["content"]
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
            existing = self.store.conn.execute(
                "SELECT id FROM knowledge WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if existing:
                return True
        return False

    def _apply_change(self, entry: ChangeEntry) -> str:
        """Apply a single change entry. Returns 'applied', 'conflict', or 'skipped'."""
        # Route non-knowledge tables to generic handler
        if entry.table != "knowledge":
            return self._apply_generic(entry)

        if entry.action == "learn":
            return self._apply_learn(entry)
        elif entry.action == "update":
            return self._apply_update(entry)
        elif entry.action == "delete":
            return self._apply_delete(entry)
        elif entry.action == "tag":
            return self._apply_tag(entry)
        elif entry.action == "link":
            return self._apply_link(entry)
        return "skipped"

    def _apply_learn(self, entry: ChangeEntry) -> str:
        """Apply a learn action."""
        data = entry.data
        try:
            self.store.learn(
                data.get("content", ""),
                agent_id=data.get("agent_id"),
                topic=data.get("topic", ""),
                summary=data.get("summary", ""),
                source_type=data.get("source_type", "manual"),
                source_ref=data.get("source_ref", ""),
                tags=data.get("tags", ""),
                confidence=data.get("confidence", 0.8),
                access_level=data.get("access_level", "internal"),
                trust_level=data.get("trust_level", "unverified"),
                data_layer=data.get("data_layer"),
                source_origin=data.get("source_origin"),
                project=data.get("project"),
                client_ref=data.get("client_ref"),
                dedup=True,
            )
            return "applied"
        except Exception:
            return "skipped"

    def _apply_generic(self, entry: ChangeEntry) -> str:
        """Apply a learn/update action for non-knowledge tables."""
        table = entry.table
        data = entry.data

        if table not in TABLE_COLUMNS:
            return "skipped"

        if entry.action == "delete":
            try:
                self.store.conn.execute(
                    f"DELETE FROM {table} WHERE id = ?", (entry.entry_id,)
                )
                self.store.conn.commit()
                return "applied"
            except Exception:
                return "skipped"

        if entry.action in ("learn", "update"):
            cols = TABLE_COLUMNS[table]
            present = {c: data[c] for c in cols if c in data and data[c] is not None}
            if not present:
                return "skipped"

            col_names = list(present.keys())
            placeholders = ", ".join("?" for _ in col_names)
            col_list = ", ".join(col_names)
            values = [present[c] for c in col_names]

            try:
                self.store.conn.execute(
                    f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                    values,
                )
                self.store.conn.commit()
                return "applied"
            except Exception:
                return "skipped"

        return "skipped"

    def _apply_update(self, entry: ChangeEntry) -> str:
        """Apply an update action with conflict detection."""
        data = entry.data
        target_id = entry.entry_id

        # Check if entry exists locally
        local_row = self.store.conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (target_id,)
        ).fetchone()

        if not local_row:
            # Entry doesn't exist locally — treat as learn
            return self._apply_learn(entry)

        local = dict(local_row)
        local_updated = local.get("updated_at", "")

        # Conflict detection: if local was also modified
        if local_updated and local_updated > entry.timestamp:
            # Build local ChangeEntry for conflict resolution
            local_data = {
                "content": local.get("content", ""),
                "topic": local.get("topic", ""),
                "tags": local.get("tags", ""),
            }
            local_change = ChangeEntry(
                id=str(uuid.uuid4()),
                node_id=self.node_id,
                timestamp=local_updated,
                action="update",
                entry_id=target_id,
                data=local_data,
                checksum=ChangeEntry.compute_checksum(local_data),
            )

            if self.resolver.strategy == "manual_review":
                self._log_conflict(local_change, entry, "pending")
                return "conflict"

            winner = self.resolver.resolve(local_change, entry)
            self._log_conflict(
                local_change, entry,
                f"resolved:{winner.node_id}",
            )

            if winner.node_id == self.node_id:
                # Local wins — skip remote change
                return "conflict"
            # Remote wins — apply it

        # Apply update
        now = datetime.now(timezone.utc).isoformat()
        update_fields = []
        update_values = []
        for col in ("content", "topic", "tags", "summary", "source_type",
                     "source_ref", "confidence", "access_level", "trust_level",
                     "data_layer", "source_origin", "project", "client_ref"):
            if col in data:
                update_fields.append(f"{col} = ?")
                update_values.append(data[col])

        if update_fields:
            update_fields.append("updated_at = ?")
            update_values.append(now)
            update_values.append(target_id)
            self.store.conn.execute(
                f"UPDATE knowledge SET {', '.join(update_fields)} WHERE id = ?",
                update_values,
            )
            self.store.conn.commit()

        return "applied"

    def _apply_delete(self, entry: ChangeEntry) -> str:
        """Apply a delete action."""
        if self.store.delete_entry(entry.entry_id):
            return "applied"
        return "skipped"

    def _apply_tag(self, entry: ChangeEntry) -> str:
        """Apply a tag change."""
        data = entry.data
        if "tags" not in data:
            return "skipped"
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.store.conn.execute(
            "UPDATE knowledge SET tags = ?, updated_at = ? WHERE id = ?",
            (data["tags"], now, entry.entry_id),
        )
        self.store.conn.commit()
        return "applied" if cursor.rowcount > 0 else "skipped"

    def _apply_link(self, entry: ChangeEntry) -> str:
        """Apply a link action."""
        data = entry.data
        source_id = data.get("source_id")
        target_id = data.get("target_id")
        link_type = data.get("link_type", "based_on")
        if source_id and target_id:
            try:
                self.store.link_source(source_id, target_id, link_type)
                return "applied"
            except Exception:
                return "skipped"
        return "skipped"

    def _log_conflict(
        self,
        local: ChangeEntry,
        remote: ChangeEntry,
        resolution: str,
    ) -> None:
        """Log a conflict to sync_conflicts table."""
        resolved_at = (
            datetime.now(timezone.utc).isoformat()
            if not resolution.startswith("pending")
            else None
        )
        self.store.conn.execute(
            """INSERT INTO sync_conflicts
               (local_entry_id, remote_entry_id, local_data, remote_data, resolution, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                local.entry_id,
                remote.entry_id,
                json.dumps(local.data, ensure_ascii=False),
                json.dumps(remote.data, ensure_ascii=False),
                resolution,
                resolved_at,
            ),
        )
        self.store.conn.commit()

    # ── Sync state ────────────────────────────────────────────

    def get_last_sync(self, remote_node: Optional[str] = None) -> Optional[str]:
        """Get last sync timestamp for a remote node.

        If remote_node is None, returns the most recent sync timestamp
        across all nodes.
        """
        if remote_node:
            row = self.store.conn.execute(
                "SELECT last_sync_ts FROM sync_state WHERE node_id = ?",
                (remote_node,),
            ).fetchone()
            return row["last_sync_ts"] if row else None

        row = self.store.conn.execute(
            "SELECT MAX(last_sync_ts) as ts FROM sync_state"
        ).fetchone()
        return row["ts"] if row and row["ts"] else None

    def set_last_sync(self, remote_node: str, timestamp: str) -> None:
        """Record the last sync timestamp for a remote node."""
        self.store.conn.execute(
            """INSERT INTO sync_state (node_id, last_sync_ts)
               VALUES (?, ?)
               ON CONFLICT(node_id) DO UPDATE SET last_sync_ts = ?""",
            (remote_node, timestamp, timestamp),
        )
        self.store.conn.commit()

    # ── Full export / import ─────────────────────────────────

    def full_export(
        self,
        *,
        tables: Optional[list[str]] = None,
        sync_filter: Optional[SyncFilter] = None,
    ) -> str:
        """Export entire tables as a JSONL file (for initial sync).

        Args:
            tables: Tables to export. Defaults to ALL_SYNC_TABLES.
            sync_filter: Optional RBAC filter to restrict exported rows.

        Returns:
            Filepath of the generated JSONL file.
        """
        target_tables = tables or ALL_SYNC_TABLES
        now = datetime.now(timezone.utc).isoformat()
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = now.replace(":", "-")
        filename = f"{self.node_id}_full_{safe_ts}.jsonl"
        filepath = self.sync_dir / filename
        total = 0

        with open(filepath, "w", encoding="utf-8") as f:
            for table in target_tables:
                if table not in TABLE_COLUMNS:
                    continue
                cols = TABLE_COLUMNS[table]
                try:
                    rows = self.store.conn.execute(
                        f"SELECT * FROM {table} ORDER BY id ASC"
                    ).fetchall()
                except Exception:
                    # Table may not have an id column (entity_mentions)
                    rows = self.store.conn.execute(
                        f"SELECT * FROM {table}"
                    ).fetchall()

                for row in rows:
                    r = dict(row)
                    data = {col: r.get(col) for col in cols if col in r}

                    # Apply RBAC filter
                    if sync_filter and not sync_filter.accepts(data, table):
                        continue

                    checksum = ChangeEntry.compute_checksum(data)
                    entry = ChangeEntry(
                        id=str(uuid.uuid4()),
                        node_id=self.node_id,
                        timestamp=r.get("created_at", now),
                        action="learn",
                        entry_id=r.get("id", 0),
                        data=data,
                        checksum=checksum,
                        table=table,
                    )
                    f.write(entry.to_jsonl() + "\n")
                    total += 1

        # Log export
        self.store.conn.execute(
            """INSERT INTO sync_log (node_id, direction, timestamp, entries_count, conflicts_count)
               VALUES (?, 'export', ?, ?, 0)""",
            (self.node_id, now, total),
        )
        self.store.conn.commit()

        return str(filepath)

    def full_import(self, filepath: str) -> dict:
        """Import a full JSONL export (for initial setup on a new node).

        Same as import_changes but skips conflict detection — all entries
        are treated as new learns with dedup.  Supports multi-table entries.

        Returns:
            {"applied": N, "conflicts": 0, "skipped": N}
        """
        result = {"applied": 0, "conflicts": 0, "skipped": 0}

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    entry = ChangeEntry.from_json(obj)
                except (json.JSONDecodeError, ValueError):
                    result["skipped"] += 1
                    continue

                if not entry.verify_checksum():
                    result["skipped"] += 1
                    continue

                if entry.table == "knowledge":
                    outcome = self._apply_learn(entry)
                else:
                    outcome = self._apply_generic(entry)

                if outcome == "applied":
                    result["applied"] += 1
                else:
                    result["skipped"] += 1

        now = datetime.now(timezone.utc).isoformat()
        remote_node = "full_import"
        self.store.conn.execute(
            """INSERT INTO sync_log (node_id, direction, timestamp, entries_count, conflicts_count)
               VALUES (?, 'import', ?, ?, 0)""",
            (remote_node, now, result["applied"]),
        )
        self.store.conn.commit()

        return result

    # ── Lock intent export/import (SyncEngine integration) ───

    def export_lock_intents(self, since: Optional[str] = None) -> str:
        """Export lock intents as a JSONL file.

        Args:
            since: ISO 8601 timestamp. If None, exports all unresolved intents.

        Returns:
            Filepath of the generated JSONL file.
        """
        query = "SELECT * FROM lock_intents"
        params: list = []
        if since:
            query += " WHERE timestamp > ?"
            params.append(since)
        query += " ORDER BY timestamp ASC"

        try:
            rows = self.store.conn.execute(query, params).fetchall()
        except Exception:
            rows = []

        now = datetime.now(timezone.utc).isoformat()
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        safe_ts = now.replace(":", "-")
        filename = f"{self.node_id}_locks_{safe_ts}.jsonl"
        filepath = self.sync_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for row in rows:
                r = dict(row)
                obj = {
                    "id": r.get("claim_id", str(uuid.uuid4())),
                    "node": r.get("node_id", self.node_id),
                    "ts": r.get("timestamp", now),
                    "action": "claim",
                    "entry_id": 0,
                    "data": {
                        "claim_id": r.get("claim_id"),
                        "task_id": r.get("task_id"),
                        "node_id": r.get("node_id"),
                        "timeout_ms": r.get("timeout_ms"),
                        "priority": r.get("priority"),
                        "resolved": r.get("resolved", 0),
                    },
                    "checksum": ChangeEntry.compute_checksum({
                        "claim_id": r.get("claim_id"),
                        "task_id": r.get("task_id"),
                        "node_id": r.get("node_id"),
                    }),
                    "table": "lock_intents",
                }
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")

        return str(filepath)

    def import_lock_intents(self, filepath: str) -> dict:
        """Import remote lock intents and detect conflicts.

        Args:
            filepath: Path to a JSONL file of lock intents.

        Returns:
            {"imported": N, "conflicts": N, "skipped": N,
             "conflict_details": [{"task_id": ..., "local_claim": ..., "remote_claim": ...}]}
        """
        result: dict = {
            "imported": 0, "conflicts": 0, "skipped": 0, "conflict_details": [],
        }

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    result["skipped"] += 1
                    continue

                data = obj.get("data", {})
                claim_id = data.get("claim_id")
                task_id = data.get("task_id")
                node_id = data.get("node_id", obj.get("node"))
                timestamp = obj.get("ts")
                timeout_ms = data.get("timeout_ms", 2000)
                priority = data.get("priority", 0)

                if not claim_id or not task_id:
                    result["skipped"] += 1
                    continue

                # Check for duplicate
                existing = self.store.conn.execute(
                    "SELECT id FROM lock_intents WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                if existing:
                    result["skipped"] += 1
                    continue

                # Insert remote intent
                self.store.conn.execute(
                    """INSERT INTO lock_intents
                       (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
                       VALUES (?, ?, ?, ?, ?, ?, 0)""",
                    (claim_id, task_id, node_id, timestamp, timeout_ms, priority),
                )
                result["imported"] += 1

                # Detect conflict with local confirmed locks
                local_lock = self.store.conn.execute(
                    "SELECT * FROM task_locks WHERE task_id = ? AND status = 'confirmed'",
                    (task_id,),
                ).fetchone()

                if local_lock:
                    local_lock = dict(local_lock)
                    local_claim = TaskClaim(
                        claim_id=local_lock.get("id", ""),
                        task_id=task_id,
                        node_id=local_lock["node_id"],
                        timestamp=local_lock.get("claimed_at", ""),
                        status="confirmed",
                        priority=local_lock.get("priority", 0),
                    )
                    remote_claim = TaskClaim(
                        claim_id=claim_id,
                        task_id=task_id,
                        node_id=node_id,
                        timestamp=timestamp,
                        status="pending",
                        priority=priority,
                    )
                    winner = LockManager._resolve_conflict_static(
                        [local_claim, remote_claim]
                    )
                    if winner.claim_id != local_claim.claim_id:
                        # Remote wins — reject local lock
                        self.store.conn.execute(
                            "UPDATE task_locks SET status = 'rejected' "
                            "WHERE task_id = ? AND status = 'confirmed'",
                            (task_id,),
                        )
                    result["conflicts"] += 1
                    result["conflict_details"].append({
                        "task_id": task_id,
                        "local_claim": local_claim.claim_id,
                        "remote_claim": claim_id,
                        "winner": winner.node_id,
                    })

        self.store.conn.commit()
        return result


# ── Task Claim Protocol with Optimistic Locking ─────────────

LOCK_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS task_locks (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_at TEXT,
    confirmed_at TEXT,
    released_at TEXT,
    expires_at TEXT,
    priority INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lock_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    timeout_ms INTEGER DEFAULT 2000,
    priority INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0
);
"""


@dataclass
class TaskClaim:
    """Represents a distributed task lock claim.

    Part of the Task Claim Protocol — optimistic locking for distributed
    UAML nodes that may operate offline.

    © 2026 Ladislav Zamazal / GLG, a.s.
    """

    claim_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    node_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    status: str = "pending"  # pending | confirmed | rejected | released | expired
    timeout_ms: int = 2000
    priority: int = 0
    expires_at: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskClaim":
        """Deserialize from dictionary."""
        return cls(
            claim_id=data.get("claim_id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            node_id=data.get("node_id", ""),
            timestamp=data.get("timestamp", ""),
            status=data.get("status", "pending"),
            timeout_ms=data.get("timeout_ms", 2000),
            priority=data.get("priority", 0),
            expires_at=data.get("expires_at", ""),
        )


class LockManager:
    """Distributed task locking with optimistic concurrency control.

    Uses a two-phase claim protocol:
      1. claim() — create a pending lock intent (optimistic)
      2. confirm() — check for conflicts, finalize or reject

    Conflict resolution:
      - Higher priority wins
      - Same priority: earlier timestamp wins
      - Same timestamp: lexicographic node_id tiebreak

    © 2026 Ladislav Zamazal / GLG, a.s.
    """

    def __init__(
        self,
        store: MemoryStore,
        node_id: str,
        default_timeout_ms: int = 2000,
        lock_duration_minutes: int = 60,
    ):
        self.store = store
        self.node_id = node_id
        self.default_timeout_ms = default_timeout_ms
        self.lock_duration_minutes = lock_duration_minutes
        self._ensure_lock_tables()

    def _ensure_lock_tables(self) -> None:
        """Create lock-specific tables if they don't exist."""
        self.store.conn.executescript(LOCK_SCHEMA_SQL)
        self.store.conn.commit()

    def _audit(self, action: str, task_id: str, details: str = "") -> None:
        """Record an audit log entry for lock operations."""
        try:
            self.store.conn.execute(
                "INSERT INTO audit_log (agent_id, action, target_table, target_id) "
                "VALUES (?, ?, 'task_locks', 0)",
                (self.node_id, f"{action}{'|' + details if details else ''}"),
            )
            self.store.conn.commit()
        except Exception:
            pass  # Audit should never break main operations

    def claim(self, task_id: str, priority: int = 0) -> TaskClaim:
        """Create a pending claim intent for a task.

        The claim is stored locally and can be exported via JSONL for
        other nodes to evaluate.

        Args:
            task_id: The task/entry being claimed.
            priority: Node priority — higher wins ties.

        Returns:
            A TaskClaim with status='pending'.
        """
        now = datetime.now(timezone.utc)
        expires_at = (
            now + timedelta(minutes=self.lock_duration_minutes)
        ).isoformat()

        claim = TaskClaim(
            claim_id=str(uuid.uuid4()),
            task_id=task_id,
            node_id=self.node_id,
            timestamp=now.isoformat(),
            status="pending",
            timeout_ms=self.default_timeout_ms,
            priority=priority,
            expires_at=expires_at,
        )

        # Store in task_locks
        self.store.conn.execute(
            """INSERT INTO task_locks
               (id, task_id, node_id, status, claimed_at, expires_at, priority)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
            (claim.claim_id, task_id, self.node_id,
             claim.timestamp, expires_at, priority),
        )

        # Store in lock_intents for sync
        self.store.conn.execute(
            """INSERT INTO lock_intents
               (claim_id, task_id, node_id, timestamp, timeout_ms, priority, resolved)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (claim.claim_id, task_id, self.node_id, claim.timestamp,
             self.default_timeout_ms, priority),
        )
        self.store.conn.commit()

        self._audit("claim", task_id, f"claim_id={claim.claim_id}")
        return claim

    def confirm(self, claim_id: str) -> bool:
        """Confirm a pending claim after checking for conflicts.

        Checks the lock_intents table for competing claims on the same
        task_id. If this claim wins (or no competition), confirms it.
        Otherwise rejects it.

        Args:
            claim_id: The claim UUID to confirm.

        Returns:
            True if confirmed, False if rejected.
        """
        row = self.store.conn.execute(
            "SELECT * FROM task_locks WHERE id = ?", (claim_id,)
        ).fetchone()
        if not row:
            return False

        lock = dict(row)
        task_id = lock["task_id"]

        # Check for competing intents on the same task
        competing = self.store.conn.execute(
            """SELECT * FROM lock_intents
               WHERE task_id = ? AND claim_id != ? AND resolved = 0""",
            (task_id, claim_id),
        ).fetchall()

        if competing:
            # Build claims list for resolution
            our_claim = TaskClaim(
                claim_id=claim_id,
                task_id=task_id,
                node_id=lock["node_id"],
                timestamp=lock["claimed_at"],
                status="pending",
                priority=lock.get("priority", 0),
            )
            claims = [our_claim]

            for comp in competing:
                c = dict(comp)
                claims.append(TaskClaim(
                    claim_id=c["claim_id"],
                    task_id=task_id,
                    node_id=c["node_id"],
                    timestamp=c["timestamp"],
                    status="pending",
                    priority=c.get("priority", 0),
                ))

            winner = self.resolve_conflict(claims)

            if winner.claim_id != claim_id:
                # We lost — reject
                self.store.conn.execute(
                    "UPDATE task_locks SET status = 'rejected' WHERE id = ?",
                    (claim_id,),
                )
                self.store.conn.execute(
                    "UPDATE lock_intents SET resolved = 1 WHERE claim_id = ?",
                    (claim_id,),
                )
                self.store.conn.commit()
                self._audit(
                    "confirm_rejected", task_id,
                    f"claim_id={claim_id},winner={winner.claim_id}",
                )
                return False

        # We won (or no competition) — confirm
        now = datetime.now(timezone.utc).isoformat()
        self.store.conn.execute(
            "UPDATE task_locks SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
            (now, claim_id),
        )
        self.store.conn.execute(
            "UPDATE lock_intents SET resolved = 1 WHERE claim_id = ?",
            (claim_id,),
        )
        self.store.conn.commit()

        self._audit("confirm", task_id, f"claim_id={claim_id}")
        return True

    def release(self, task_id: str) -> bool:
        """Release a confirmed lock on a task.

        Args:
            task_id: The task to release.

        Returns:
            True if a lock was released, False if no active lock found.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.store.conn.execute(
            """UPDATE task_locks SET status = 'released', released_at = ?
               WHERE task_id = ? AND status = 'confirmed' AND node_id = ?""",
            (now, task_id, self.node_id),
        )
        self.store.conn.commit()

        if cursor.rowcount > 0:
            self._audit("release", task_id)
            return True
        return False

    def is_locked(self, task_id: str) -> Optional[dict]:
        """Check if a task is currently locked.

        Args:
            task_id: The task to check.

        Returns:
            Lock info dict if locked, None otherwise.
        """
        now = datetime.now(timezone.utc).isoformat()
        row = self.store.conn.execute(
            """SELECT * FROM task_locks
               WHERE task_id = ? AND status = 'confirmed' AND expires_at > ?""",
            (task_id, now),
        ).fetchone()

        if row:
            return dict(row)
        return None

    def active_locks(self) -> list[dict]:
        """List all active (confirmed, non-expired) locks.

        Returns:
            List of lock info dicts.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = self.store.conn.execute(
            """SELECT * FROM task_locks
               WHERE status = 'confirmed' AND expires_at > ?
               ORDER BY claimed_at ASC""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def expired_locks(self) -> list[dict]:
        """List expired locks (confirmed but past expires_at).

        Returns:
            List of expired lock info dicts.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = self.store.conn.execute(
            """SELECT * FROM task_locks
               WHERE status = 'confirmed' AND expires_at <= ?
               ORDER BY expires_at ASC""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_expired(self) -> int:
        """Release all expired locks.

        Returns:
            Number of locks released.
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.store.conn.execute(
            """UPDATE task_locks SET status = 'expired', released_at = ?
               WHERE status = 'confirmed' AND expires_at <= ?""",
            (now, now),
        )
        self.store.conn.commit()
        count = cursor.rowcount
        if count > 0:
            self._audit("cleanup_expired", "*", f"count={count}")
        return count

    def resolve_conflict(self, claims: list[TaskClaim]) -> TaskClaim:
        """Resolve multiple competing claims for the same task.

        Resolution order:
          1. Higher priority wins
          2. Same priority: earlier timestamp wins
          3. Same timestamp: lexicographic node_id tiebreak (lower wins)

        Args:
            claims: List of competing TaskClaim objects.

        Returns:
            The winning TaskClaim.
        """
        return self._resolve_conflict_static(claims)

    @staticmethod
    def _resolve_conflict_static(claims: list[TaskClaim]) -> TaskClaim:
        """Static conflict resolution — usable without a LockManager instance."""
        if not claims:
            raise ValueError("No claims to resolve")
        if len(claims) == 1:
            return claims[0]

        # Sort: highest priority first, then earliest timestamp, then lowest node_id
        sorted_claims = sorted(
            claims,
            key=lambda c: (-c.priority, c.timestamp, c.node_id),
        )
        return sorted_claims[0]
