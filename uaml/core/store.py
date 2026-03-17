# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""MemoryStore — the main interface to UAML's knowledge database.

Usage:
    from uaml import MemoryStore

    store = MemoryStore("memory.db")
    store.learn("Python's GIL prevents true threading", agent_id="agent1", topic="python")
    results = store.search("GIL threading")
    store.close()
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from uaml.core.models import (
    AccessLevel,
    DataLayer,
    KnowledgeEntry,
    SearchResult,
    SourceOrigin,
    SourceType,
    TrustLevel,
)
from uaml.core.schema import PRAGMA_SQL, SCHEMA_SQL, SCHEMA_VERSION, MIGRATIONS

# Lazy imports to avoid circular dependency
EthicsChecker = None  # type: ignore
ContradictionChecker = None  # type: ignore


class EthicsViolation(Exception):
    """Raised when content is rejected by the ethics checker in enforce mode."""
    pass


class ContradictionWarning:
    """Returned alongside entry ID when contradictions are detected."""
    def __init__(self, action: str, details: list, conflicting_ids: list, superseded_ids: list, severity: str):
        self.action = action
        self.details = details
        self.conflicting_ids = conflicting_ids
        self.superseded_ids = superseded_ids
        self.severity = severity

    @property
    def has_conflict(self) -> bool:
        return self.action != "ok"

    def __repr__(self):
        return f"ContradictionWarning(action={self.action}, severity={self.severity}, details={self.details})"


class MemoryStore:
    """Core UAML memory store backed by SQLite + FTS5.

    Thread-safe for reads (WAL mode). Single writer at a time.
    Optionally integrates an ethics checker for pre-learn content filtering.
    """

    def __init__(
        self,
        db_path: str | Path = "memory.db",
        agent_id: str = "default",
        ethics_checker: Optional["EthicsChecker"] = None,
        ethics_mode: str = "warn",  # "warn", "enforce", "off"
        contradiction_mode: str = "warn",  # "warn", "auto", "off"
    ):
        self.db_path = Path(db_path)
        self.agent_id = agent_id
        self._ethics = ethics_checker
        self._ethics_mode = ethics_mode
        self._contradiction_mode = contradiction_mode
        self._contradiction_checker = None  # Lazy init
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database and apply schema if needed."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # Apply pragmas
        for pragma in PRAGMA_SQL.strip().split("\n"):
            pragma = pragma.strip()
            if pragma and not pragma.startswith("--"):
                self._conn.execute(pragma)

        # Migrate legacy DBs before applying full schema
        try:
            self._conn.execute("SELECT 1 FROM knowledge LIMIT 1")
            # Table exists — ensure missing columns before schema indexes
            existing_cols = {
                r[1] for r in self._conn.execute("PRAGMA table_info(knowledge)")
            }
            legacy_adds = [
                ("valid_from", "TEXT"),
                ("valid_until", "TEXT"),
                ("superseded_by", "INTEGER REFERENCES knowledge(id)"),
                ("data_layer", "TEXT DEFAULT 'knowledge'"),
                ("source_origin", "TEXT DEFAULT 'external'"),
                ("legal_basis", "TEXT"),
                ("consent_ref", "TEXT"),
            ]
            for col, typedef in legacy_adds:
                if col not in existing_cols:
                    try:
                        self._conn.execute(
                            f"ALTER TABLE knowledge ADD COLUMN {col} {typedef}"
                        )
                    except sqlite3.OperationalError:
                        pass
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Fresh DB — no knowledge table yet

        # Apply schema
        self._conn.executescript(SCHEMA_SQL)

        # Run migrations if needed
        try:
            row = self._conn.execute(
                "SELECT MAX(version) as v FROM schema_version"
            ).fetchone()
            current_version = row["v"] if row and row["v"] else 1
        except Exception:
            current_version = 1

        for ver in sorted(MIGRATIONS.keys()):
            if ver > current_version:
                for stmt in MIGRATIONS[ver].strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            self._conn.execute(stmt)
                        except sqlite3.OperationalError:
                            pass  # Column may already exist

        # Record schema version
        self._conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._ensure_db()
        return self._conn  # type: ignore

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Learn (Write) ──────────────────────────────────────────

    def learn(
        self,
        content: str,
        *,
        agent_id: Optional[str] = None,
        topic: str = "",
        summary: str = "",
        source_type: str | SourceType = "manual",
        source_ref: str = "",
        tags: str = "",
        confidence: float = 0.8,
        access_level: str | AccessLevel = "internal",
        trust_level: str | TrustLevel = "unverified",
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        client_ref: Optional[str] = None,
        project: Optional[str] = None,
        dedup: bool = True,
        legal_basis: Optional[str] = None,
        consent_ref: Optional[str] = None,
        data_layer: Optional[str | DataLayer] = None,
        source_origin: Optional[str | SourceOrigin] = None,
    ) -> int:
        """Store a new knowledge entry. Returns the entry ID.

        If dedup=True (default), skips insertion if identical content already exists.
        data_layer accepts string or DataLayer enum (identity/knowledge/team/operational/project).
        source_origin accepts string or SourceOrigin enum (external/generated/derived/observed).
        """
        agent = agent_id or self.agent_id

        # Ethics check (pre-learn hook)
        if self._ethics and self._ethics_mode != "off":
            verdict = self._ethics.check(content)
            if verdict.rejected and self._ethics_mode == "enforce":
                raise EthicsViolation(
                    f"Content rejected by ethics checker: {verdict.rules_triggered}"
                )
            if verdict.flagged or verdict.rejected:
                # Store verdict in audit log
                self._audit(
                    f"ethics_{verdict.verdict.lower()}",
                    "knowledge", 0, agent,
                    details=str(verdict.rules_triggered),
                )

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

        if dedup:
            existing = self.conn.execute(
                "SELECT id FROM knowledge WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if existing:
                return existing["id"]

        # Contradiction detection (pre-learn hook)
        contradiction_warning = None
        if self._contradiction_mode != "off":
            contradiction_warning = self._check_contradictions(
                content, topic=topic, agent_id=agent or self.agent_id,
                project=project or "", client_ref=client_ref,
            )

        now = datetime.now(tz=__import__('datetime').timezone.utc).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO knowledge
            (agent_id, topic, summary, content, source_type, source_ref, tags,
             confidence, access_level, trust_level, valid_from, valid_until,
             client_ref, project, content_hash, created_at, updated_at,
             legal_basis, consent_ref, data_layer, source_origin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent,
                topic,
                summary,
                content,
                str(source_type),
                source_ref,
                tags,
                confidence,
                str(access_level),
                str(trust_level),
                valid_from,
                valid_until,
                client_ref,
                project,
                content_hash,
                now,
                now,
                legal_basis,
                consent_ref,
                str(data_layer) if data_layer else "knowledge",
                str(source_origin) if source_origin else "external",
            ),
        )
        self.conn.commit()

        entry_id = cursor.lastrowid

        # Handle contradictions post-insert
        if contradiction_warning and contradiction_warning.has_conflict:
            if self._contradiction_mode == "auto" and contradiction_warning.superseded_ids:
                # Auto-supersede older entries
                for old_id in contradiction_warning.superseded_ids:
                    self.conn.execute(
                        "UPDATE knowledge SET superseded_by = ?, updated_at = ? WHERE id = ? AND superseded_by IS NULL",
                        (entry_id, now, old_id),
                    )
                    # Create provenance link
                    self.conn.execute(
                        "INSERT INTO source_links (source_id, target_id, link_type, confidence, notes) "
                        "VALUES (?, ?, 'supersedes', 0.9, ?)",
                        (entry_id, old_id, "; ".join(contradiction_warning.details[:3])),
                    )
                self.conn.commit()
                self._audit(
                    "auto_supersede", "knowledge", entry_id, agent,
                    details=f"superseded={contradiction_warning.superseded_ids}",
                )
            elif contradiction_warning.action == "flag":
                # Create contradiction links for review
                for old_id in contradiction_warning.conflicting_ids:
                    self.conn.execute(
                        "INSERT INTO source_links (source_id, target_id, link_type, confidence, notes) "
                        "VALUES (?, ?, 'contradicts', 0.7, ?)",
                        (entry_id, old_id, "; ".join(contradiction_warning.details[:3])),
                    )
                self.conn.commit()
                self._audit(
                    "contradiction_flagged", "knowledge", entry_id, agent,
                    details=f"conflicts_with={contradiction_warning.conflicting_ids}, "
                            f"severity={contradiction_warning.severity}",
                )
            else:
                # warn mode: just log, don't modify
                self._audit(
                    "contradiction_detected", "knowledge", entry_id, agent,
                    details=f"action={contradiction_warning.action}, "
                            f"conflicts={contradiction_warning.conflicting_ids}, "
                            f"details={'; '.join(contradiction_warning.details[:3])}",
                )

        # Audit
        self._audit("learn", "knowledge", entry_id, agent)

        return entry_id

    # ── Search (Read) ──────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        agent_id: Optional[str] = None,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        point_in_time: Optional[str] = None,
    ) -> list[SearchResult]:
        """Search knowledge using FTS5 full-text search.

        Args:
            query: Search query (supports FTS5 syntax: AND, OR, NOT, phrases)
            limit: Maximum results to return
            agent_id: Filter by agent
            topic: Filter by topic
            project: Filter by project
            client_ref: Filter by client (isolation)
            point_in_time: ISO date for temporal query ("what was valid at time X?")
        """
        # Build FTS query — auto-add OR between words for broader matching
        conditions = []
        params: list = []

        # Convert natural language query to FTS5 syntax
        # "GIL threading" → "GIL OR threading" (broader, more intuitive)
        words = query.strip().split()
        if len(words) > 1 and " OR " not in query and " AND " not in query and '"' not in query:
            fts_query = " OR ".join(w.replace("'", "''") for w in words)
        else:
            fts_query = query.replace("'", "''")

        # Additional filters via JOIN
        where_parts = []
        if agent_id:
            where_parts.append("k.agent_id = ?")
            params.append(agent_id)
        if topic:
            where_parts.append("k.topic = ?")
            params.append(topic)
        if project:
            where_parts.append("k.project = ?")
            params.append(project)
        if client_ref:
            where_parts.append("k.client_ref = ?")
            params.append(client_ref)
        if point_in_time:
            where_parts.append(
                "(k.valid_from IS NULL OR k.valid_from <= ?)"
            )
            params.append(point_in_time)
            where_parts.append(
                "(k.valid_until IS NULL OR k.valid_until >= ?)"
            )
            params.append(point_in_time)

        where_clause = (" AND " + " AND ".join(where_parts)) if where_parts else ""

        sql = f"""
            SELECT k.*, rank
            FROM knowledge_fts
            JOIN knowledge k ON k.id = knowledge_fts.rowid
            WHERE knowledge_fts MATCH ?{where_clause}
            ORDER BY rank
            LIMIT ?
        """
        params = [fts_query] + params + [limit]

        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Fallback to LIKE search if FTS query syntax is invalid
            return self._search_like(query, limit)

        results = []
        for row in rows:
            entry = self._row_to_entry(row)
            score = abs(row["rank"]) if row["rank"] else 0.0
            snippet = (entry.summary or entry.content[:200])
            results.append(SearchResult(entry=entry, score=score, snippet=snippet))

        return results

    def _search_like(self, query: str, limit: int) -> list[SearchResult]:
        """Fallback LIKE search when FTS syntax is invalid."""
        pattern = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM knowledge WHERE content LIKE ? OR summary LIKE ? LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall()
        results = []
        for row in rows:
            entry = self._row_to_entry(row)
            results.append(SearchResult(entry=entry, score=0.5, snippet=entry.content[:200]))
        return results

    # ── Entity operations ──────────────────────────────────────

    def get_entity(self, name: str) -> Optional[dict]:
        """Look up an entity by name and return its knowledge connections."""
        entity = self.conn.execute(
            "SELECT * FROM entities WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if not entity:
            return None

        # Get connected knowledge entries
        mentions = self.conn.execute(
            """SELECT k.* FROM knowledge k
               JOIN entity_mentions em ON em.entry_id = k.id
               WHERE em.entity_id = ?""",
            (entity["id"],),
        ).fetchall()

        return {
            "entity": dict(entity),
            "knowledge": [dict(m) for m in mentions],
        }

    # ── Stats ──────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return database statistics."""
        result = {}
        for table in ["knowledge", "team_knowledge", "personality", "entities",
                       "entity_mentions", "knowledge_relations", "audit_log",
                       "session_summaries", "tasks", "artifacts", "source_links"]:
            try:
                row = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                result[table] = row["cnt"]
            except sqlite3.OperationalError:
                result[table] = 0

        # Topic distribution
        topics = self.conn.execute(
            "SELECT topic, COUNT(*) as cnt FROM knowledge GROUP BY topic ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        result["top_topics"] = {r["topic"]: r["cnt"] for r in topics}

        # Agent distribution
        agents = self.conn.execute(
            "SELECT agent_id, COUNT(*) as cnt FROM knowledge GROUP BY agent_id ORDER BY cnt DESC"
        ).fetchall()
        result["agents"] = {r["agent_id"]: r["cnt"] for r in agents}

        return result

    # ── Task Management ──────────────────────────────────────

    def create_task(
        self,
        title: str,
        *,
        description: str = "",
        status: str = "todo",
        project: Optional[str] = None,
        assigned_to: Optional[str] = None,
        priority: int = 0,
        tags: str = "",
        due_date: Optional[str] = None,
        parent_id: Optional[int] = None,
        client_ref: Optional[str] = None,
    ) -> int:
        """Create a new task. Returns the task ID."""
        cursor = self.conn.execute(
            """INSERT INTO tasks
            (title, description, status, project, assigned_to, priority,
             tags, due_date, parent_id, client_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, status, project, assigned_to, priority,
             tags, due_date, parent_id, client_ref),
        )
        self.conn.commit()
        task_id = cursor.lastrowid
        self._audit("task_create", "tasks", task_id, assigned_to or self.agent_id)
        return task_id

    def update_task(self, task_id: int, **kwargs) -> bool:
        """Update task fields. Returns True if task was found.

        Supported fields: title, description, status, project, assigned_to,
        priority, tags, due_date, client_ref.
        Automatically sets completed_at when status changes to 'done'.
        """
        allowed = {"title", "description", "status", "project", "assigned_to",
                    "priority", "tags", "due_date", "client_ref"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        # Auto-set completed_at
        if updates.get("status") == "done":
            updates["completed_at"] = __import__('datetime').datetime.now(
                tz=__import__('datetime').timezone.utc
            ).isoformat()

        updates["updated_at"] = __import__('datetime').datetime.now(
            tz=__import__('datetime').timezone.utc
        ).isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]

        cursor = self.conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()
        if cursor.rowcount > 0:
            self._audit("task_update", "tasks", task_id, self.agent_id)
        return cursor.rowcount > 0

    def list_tasks(
        self,
        *,
        status: Optional[str] = None,
        project: Optional[str] = None,
        assigned_to: Optional[str] = None,
        client_ref: Optional[str] = None,
        parent_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List tasks with optional filters."""
        where_parts = []
        params: list = []

        if status:
            where_parts.append("status = ?")
            params.append(status)
        if project:
            where_parts.append("project = ?")
            params.append(project)
        if assigned_to:
            where_parts.append("assigned_to = ?")
            params.append(assigned_to)
        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)
        if parent_id is not None:
            where_parts.append("parent_id = ?")
            params.append(parent_id)

        where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        rows = self.conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def search_tasks(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across tasks."""
        words = query.strip().split()
        if len(words) > 1 and " OR " not in query:
            fts_query = " OR ".join(w.replace("'", "''") for w in words)
        else:
            fts_query = query.replace("'", "''")

        try:
            rows = self.conn.execute(
                """SELECT t.*, rank FROM tasks_fts
                   JOIN tasks t ON t.id = tasks_fts.rowid
                   WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE title LIKE ? OR description LIKE ? LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Artifact Management ────────────────────────────────────

    def create_artifact(
        self,
        name: str,
        *,
        artifact_type: str = "file",
        path: Optional[str] = None,
        status: str = "draft",
        source_origin: str = "generated",
        project: Optional[str] = None,
        task_id: Optional[int] = None,
        client_ref: Optional[str] = None,
        mime_type: Optional[str] = None,
        size_bytes: Optional[int] = None,
        checksum: Optional[str] = None,
    ) -> int:
        """Create an artifact record. Returns the artifact ID."""
        cursor = self.conn.execute(
            """INSERT INTO artifacts
            (name, artifact_type, path, status, source_origin, project,
             task_id, client_ref, mime_type, size_bytes, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, artifact_type, path, status, source_origin, project,
             task_id, client_ref, mime_type, size_bytes, checksum),
        )
        self.conn.commit()
        art_id = cursor.lastrowid
        self._audit("artifact_create", "artifacts", art_id, self.agent_id)
        return art_id

    def list_artifacts(
        self,
        *,
        project: Optional[str] = None,
        task_id: Optional[int] = None,
        status: Optional[str] = None,
        client_ref: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List artifacts with optional filters."""
        where_parts = []
        params: list = []
        if project:
            where_parts.append("project = ?")
            params.append(project)
        if task_id is not None:
            where_parts.append("task_id = ?")
            params.append(task_id)
        if status:
            where_parts.append("status = ?")
            params.append(status)
        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)

        where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        rows = self.conn.execute(
            f"SELECT * FROM artifacts {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Source Links (Provenance) ──────────────────────────────

    def link_source(
        self,
        source_id: int,
        target_id: int,
        link_type: str = "based_on",
        confidence: float = 0.8,
        notes: str = "",
    ) -> int:
        """Create a provenance link between knowledge entries.

        source_id: the entry that IS the source
        target_id: the entry that USES/DERIVES from the source
        link_type: based_on, cites, derived_from, supersedes, contradicts
        """
        cursor = self.conn.execute(
            """INSERT INTO source_links (source_id, target_id, link_type, confidence, notes)
            VALUES (?, ?, ?, ?, ?)""",
            (source_id, target_id, link_type, confidence, notes),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_sources(self, entry_id: int) -> list[dict]:
        """Get all sources for a knowledge entry (what is it based on?)."""
        rows = self.conn.execute(
            """SELECT sl.*, k.content, k.topic, k.source_ref
               FROM source_links sl
               JOIN knowledge k ON k.id = sl.source_id
               WHERE sl.target_id = ?""",
            (entry_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_derived(self, entry_id: int) -> list[dict]:
        """Get all entries derived from this source (what depends on it?)."""
        rows = self.conn.execute(
            """SELECT sl.*, k.content, k.topic
               FROM source_links sl
               JOIN knowledge k ON k.id = sl.target_id
               WHERE sl.source_id = ?""",
            (entry_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Provenance (auditable source tracking) ────────────────

    def add_provenance(
        self,
        knowledge_id: int,
        source_type: str = "chat",
        source_channel: str | None = None,
        source_session: str | None = None,
        source_message_idx: int | None = None,
        source_message_id: str | None = None,
        source_sender: str | None = None,
        source_sender_id: str | None = None,
        source_timestamp: str | None = None,
        source_url: str | None = None,
        source_file: str | None = None,
        source_excerpt: str | None = None,
        confidence: float = 0.8,
        notes: str = "",
    ) -> int:
        """Add an auditable provenance record for a knowledge entry.

        Supports N:M — call multiple times for multi-source entries.
        source_type: chat|file|url|api|manual|tool
        source_channel: telegram|discord|signal|whatsapp|web|voice|heartbeat
        """
        cursor = self.conn.execute(
            """INSERT INTO provenance (
                knowledge_id, source_type, source_channel, source_session,
                source_message_idx, source_message_id,
                source_sender, source_sender_id, source_timestamp,
                source_url, source_file, source_excerpt,
                confidence, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                knowledge_id, source_type, source_channel, source_session,
                source_message_idx, source_message_id,
                source_sender, source_sender_id, source_timestamp,
                source_url, source_file, source_excerpt,
                confidence, notes,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_provenance(self, knowledge_id: int) -> list[dict]:
        """Get all provenance records for a knowledge entry."""
        rows = self.conn.execute(
            "SELECT * FROM provenance WHERE knowledge_id = ? ORDER BY created_at",
            (knowledge_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_provenance_by_channel(self, channel: str, limit: int = 50) -> list[dict]:
        """Get provenance records filtered by channel."""
        rows = self.conn.execute(
            """SELECT p.*, k.topic, k.summary
               FROM provenance p
               JOIN knowledge k ON k.id = p.knowledge_id
               WHERE p.source_channel = ?
               ORDER BY p.created_at DESC LIMIT ?""",
            (channel, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Task ↔ Knowledge Links ────────────────────────────────

    def link_task_knowledge(self, task_id: int, entry_id: int, relation: str = "related") -> None:
        """Link a task to a knowledge entry."""
        self.conn.execute(
            "INSERT OR IGNORE INTO task_knowledge (task_id, entry_id, relation) VALUES (?, ?, ?)",
            (task_id, entry_id, relation),
        )
        self.conn.commit()

    def get_task_knowledge(self, task_id: int) -> list[dict]:
        """Get all knowledge entries linked to a task."""
        rows = self.conn.execute(
            """SELECT k.*, tk.relation FROM knowledge k
               JOIN task_knowledge tk ON tk.entry_id = k.id
               WHERE tk.task_id = ?""",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Data Layer operations ─────────────────────────────────

    def query_layer(
        self,
        layer: str | DataLayer,
        *,
        query: Optional[str] = None,
        client_ref: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query knowledge entries within a specific data layer.

        Enforces layer isolation: identity layer entries require explicit access.
        """
        where_parts = ["data_layer = ?"]
        params: list = [layer]

        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)
        if project:
            where_parts.append("project = ?")
            params.append(project)

        if query:
            # Use FTS within layer
            return [
                r.__dict__ if hasattr(r, '__dict__') else r
                for r in self.search(
                    query, limit=limit, client_ref=client_ref, project=project
                )
                if True  # post-filter by layer below
            ]

        where = "WHERE " + " AND ".join(where_parts)
        rows = self.conn.execute(
            f"SELECT * FROM knowledge {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def layer_stats(self) -> dict:
        """Get entry counts and size per data layer."""
        rows = self.conn.execute(
            """SELECT
                COALESCE(data_layer, 'knowledge') as layer,
                COUNT(*) as count,
                SUM(LENGTH(content)) as total_bytes,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM knowledge
            GROUP BY COALESCE(data_layer, 'knowledge')
            ORDER BY count DESC"""
        ).fetchall()

        result = {}
        for r in rows:
            d = dict(r)
            result[d["layer"]] = {
                "count": d["count"],
                "total_bytes": d["total_bytes"] or 0,
                "oldest": d["oldest"],
                "newest": d["newest"],
            }

        # Ensure all layers are represented
        for layer in ["identity", "knowledge", "team", "operational", "project"]:
            if layer not in result:
                result[layer] = {"count": 0, "total_bytes": 0, "oldest": None, "newest": None}

        return result

    def consolidate_summaries(
        self,
        *,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        group_by: str = "week",
    ) -> list[dict]:
        """Aggregate knowledge entries into time-bucketed summaries.

        Groups entries by week (default) or day, returning summary statistics
        and content samples for each bucket. Useful for weekly reports,
        memory consolidation, and trend analysis.

        Args:
            start_date: ISO date string (inclusive), e.g. "2026-03-01"
            end_date: ISO date string (inclusive), e.g. "2026-03-13"
            topic: Filter by topic
            project: Filter by project
            client_ref: Filter by client reference
            group_by: "week" (default) or "day"

        Returns:
            List of dicts with keys: period, count, topics, layers,
            total_bytes, oldest, newest, sample_entries
        """
        if group_by == "week":
            date_expr = "strftime('%Y-W%W', created_at)"
        elif group_by == "day":
            date_expr = "strftime('%Y-%m-%d', created_at)"
        else:
            date_expr = "strftime('%Y-W%W', created_at)"

        where_parts = ["1=1"]
        params: list = []

        if start_date:
            where_parts.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            where_parts.append("created_at <= ? || 'T23:59:59'")
            params.append(end_date)
        if topic:
            where_parts.append("topic = ?")
            params.append(topic)
        if project:
            where_parts.append("project = ?")
            params.append(project)
        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)

        where_sql = " AND ".join(where_parts)

        # Get aggregated stats per period
        rows = self.conn.execute(
            f"""SELECT
                {date_expr} as period,
                COUNT(*) as count,
                GROUP_CONCAT(DISTINCT topic) as topics,
                GROUP_CONCAT(DISTINCT data_layer) as layers,
                SUM(LENGTH(content)) as total_bytes,
                MIN(created_at) as oldest,
                MAX(created_at) as newest
            FROM knowledge
            WHERE {where_sql}
            GROUP BY {date_expr}
            ORDER BY period DESC""",
            params,
        ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            period = d["period"]

            # Get sample entries (first 3) for this period
            samples = self.conn.execute(
                f"""SELECT id, content, topic, data_layer, confidence, created_at
                FROM knowledge
                WHERE {where_sql} AND {date_expr} = ?
                ORDER BY confidence DESC, created_at DESC
                LIMIT 3""",
                params + [period],
            ).fetchall()

            results.append({
                "period": period,
                "count": d["count"],
                "topics": d["topics"].split(",") if d["topics"] else [],
                "layers": d["layers"].split(",") if d["layers"] else [],
                "total_bytes": d["total_bytes"] or 0,
                "oldest": d["oldest"],
                "newest": d["newest"],
                "sample_entries": [
                    {
                        "id": s["id"],
                        "content": s["content"][:200],
                        "topic": s["topic"],
                        "layer": s["data_layer"],
                        "confidence": s["confidence"],
                    }
                    for s in samples
                ],
            })

        return results

    def export_layer(
        self,
        layer: str | DataLayer,
        *,
        client_ref: Optional[str] = None,
        confirm_identity: bool = False,
    ) -> list[dict]:
        """Export all entries from a data layer.

        Identity layer export requires confirm_identity=True (extra protection).
        """
        if layer == "identity" and not confirm_identity:
            raise PermissionError(
                "Identity layer export requires confirm_identity=True. "
                "This layer contains sensitive personality and preference data."
            )

        where_parts = ["data_layer = ?"]
        params: list = [layer]
        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)

        where = "WHERE " + " AND ".join(where_parts)
        rows = self.conn.execute(
            f"SELECT * FROM knowledge {where} ORDER BY created_at", params
        ).fetchall()

        self._audit(
            "export_layer", "knowledge", 0, self.agent_id,
            details=f"layer={layer}, count={len(rows)}, client={client_ref}",
        )

        return [dict(r) for r in rows]

    # ── Associative Memory ─────────────────────────────────────

    def related(self, entry_id: int, *, limit: int = 10, min_score: float = 0.05) -> list:
        """Find entries related to a given entry ("intuition").

        Uses multi-signal scoring: content similarity, topic/tag/project overlap,
        temporal proximity, provenance links, and task connections.
        """
        from uaml.core.associative import AssociativeEngine
        engine = AssociativeEngine(self)
        return engine.find_related(entry_id, limit=limit, min_score=min_score)

    def contextual_recall(self, context: str, *, limit: int = 5, min_score: float = 0.05) -> list:
        """Proactive recall based on situational context.

        Given a text (e.g., conversation topic), finds relevant knowledge
        entries — without an explicit query. This is "intuition".
        """
        from uaml.core.associative import AssociativeEngine
        engine = AssociativeEngine(self)
        return engine.contextual_recall(context, limit=limit, min_score=min_score)

    def capture_reasoning(
        self,
        decision: str,
        *,
        reasoning: str = "",
        evidence_ids: Optional[list[int]] = None,
        agent_id: Optional[str] = None,
        context: str = "",
        confidence: float = 0.8,
    ) -> int:
        """Capture a reasoning trace — record why a decision was made.

        Links the decision to evidence entries and records the reasoning chain.
        Critical for audit trail, explainability, and trust.

        Args:
            decision: The decision that was made
            reasoning: Why this decision was made
            evidence_ids: IDs of knowledge entries that informed the decision
            agent_id: Which agent made the decision
            context: Situational context
            confidence: Confidence in the decision (0.0-1.0)

        Returns:
            Trace ID
        """
        from uaml.core.reasoning import ReasoningTracer
        tracer = ReasoningTracer(self)
        trace_id = tracer.record(
            decision=decision,
            reasoning=reasoning,
            evidence_ids=evidence_ids or [],
            agent_id=agent_id or self.agent_id,
            context=context,
            confidence=confidence,
        )
        return trace_id

    def auto_capture_reasoning(self, text: str, *, agent_id: Optional[str] = None) -> Optional[int]:
        """Automatically detect and capture reasoning from text.

        Scans text for reasoning patterns (because, therefore, decided, etc.)
        and creates a trace if found.

        Returns trace_id if reasoning was detected, None otherwise.
        """
        from uaml.core.reasoning import ReasoningTracer
        tracer = ReasoningTracer(self)
        return tracer.auto_extract(text, agent_id=agent_id or self.agent_id)

    def get_reasoning_traces(self, *, limit: int = 10, agent_id: Optional[str] = None) -> list:
        """Get recent reasoning traces."""
        from uaml.core.reasoning import ReasoningTracer
        tracer = ReasoningTracer(self)
        return tracer.list_traces(limit=limit, agent_id=agent_id)

    def purge(
        self,
        *,
        older_than_days: Optional[int] = None,
        data_layer: Optional[str] = None,
        client_ref: Optional[str] = None,
        project: Optional[str] = None,
        confidence_below: Optional[float] = None,
        tags: Optional[str] = None,
        dry_run: bool = True,
    ) -> dict:
        """Selectively purge knowledge entries.

        By default runs in dry_run mode (preview only).
        Set dry_run=False to actually delete.

        Args:
            older_than_days: Delete entries older than N days
            data_layer: Delete only from this layer
            client_ref: Delete only for this client
            project: Delete only for this project
            confidence_below: Delete entries below this confidence
            tags: Delete entries matching this tag
            dry_run: If True, only count what would be deleted

        Returns:
            Dict with counts and status
        """
        conditions = []
        params: list = []

        if older_than_days is not None:
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
            conditions.append("created_at < ?")
            params.append(cutoff)

        if data_layer:
            conditions.append("data_layer = ?")
            params.append(data_layer)

        if client_ref:
            conditions.append("client_ref = ?")
            params.append(client_ref)

        if project:
            conditions.append("project = ?")
            params.append(project)

        if confidence_below is not None:
            conditions.append("confidence < ?")
            params.append(confidence_below)

        if tags:
            conditions.append("tags LIKE ?")
            params.append(f"%{tags}%")

        if not conditions:
            return {"error": "No purge criteria specified", "deleted": 0, "status": "refused"}

        where = " AND ".join(conditions)

        # Never purge identity layer without explicit request
        if data_layer != "identity":
            where = f"({where}) AND (data_layer != 'identity' OR data_layer IS NULL)"

        # Count
        count = self._conn.execute(
            f"SELECT COUNT(*) FROM knowledge WHERE {where}", params
        ).fetchone()[0]

        if dry_run:
            return {"deleted": 0, "would_delete": count, "status": "dry_run", "criteria": conditions}

        # Execute deletion
        self._conn.execute(f"DELETE FROM knowledge WHERE {where}", params)
        self._conn.commit()

        # Audit
        self._audit("purge", "knowledge", 0, self.agent_id,
                    f"Purged {count} entries: {conditions}")

        return {"deleted": count, "status": "completed", "criteria": conditions}

    def delete_entry(self, entry_id: int) -> bool:
        """Delete a single knowledge entry by ID.

        Returns True if entry was deleted, False if not found.
        """
        # Check if entry exists
        row = self._conn.execute(
            "SELECT id, data_layer FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()

        if not row:
            return False

        # Delete related data
        self._conn.execute("DELETE FROM source_links WHERE source_id = ? OR target_id = ?", (entry_id, entry_id))
        self._conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
        self._conn.commit()

        self._audit("delete", "knowledge", entry_id, self.agent_id)
        return True

    def backfill_sources(self, *, dry_run: bool = True) -> dict:
        """Backfill missing source_origin and source_type on existing entries.

        Infers values from existing metadata (tags, source_ref, data_layer).
        """
        # Find entries missing source metadata
        missing = self._conn.execute(
            """SELECT id, content, tags, source_ref, data_layer, source_type, source_origin
            FROM knowledge
            WHERE (source_origin IS NULL OR source_origin = '')
               OR (source_type IS NULL OR source_type = '')"""
        ).fetchall()

        updates = []
        for row in missing:
            entry = dict(row)
            new_origin = entry.get("source_origin") or ""
            new_type = entry.get("source_type") or ""
            tags = entry.get("tags", "") or ""
            source_ref = entry.get("source_ref", "") or ""
            layer = entry.get("data_layer", "") or ""

            # Infer source_origin
            if not new_origin:
                if "tool:" in tags or "tool_result" in tags:
                    new_origin = "derived"
                elif "session:" in tags or "chat" in tags:
                    new_origin = "observed"
                elif "search" in tags or "web" in tags:
                    new_origin = "external"
                elif layer == "operational":
                    new_origin = "observed"
                elif layer == "identity":
                    new_origin = "generated"
                else:
                    new_origin = "external"

            # Infer source_type
            if not new_type:
                if "tool:" in tags:
                    new_type = "tool_result"
                elif "session:" in tags:
                    new_type = "conversation"
                elif source_ref and ("http" in source_ref or "://" in source_ref):
                    new_type = "web"
                elif "decision" in tags:
                    new_type = "analysis"
                else:
                    new_type = "manual"

            updates.append({
                "id": entry["id"],
                "source_origin": new_origin,
                "source_type": new_type,
            })

        if dry_run:
            return {
                "status": "dry_run",
                "would_update": len(updates),
                "total_missing": len(missing),
                "sample": updates[:5],
            }

        # Apply updates
        for u in updates:
            self._conn.execute(
                "UPDATE knowledge SET source_origin = ?, source_type = ? WHERE id = ?",
                (u["source_origin"], u["source_type"], u["id"]),
            )
        self._conn.commit()

        return {
            "status": "completed",
            "updated": len(updates),
        }

    def context_summary(
        self,
        *,
        size: str = "standard",
        topic: Optional[str] = None,
        project: Optional[str] = None,
        max_chars: Optional[int] = None,
    ) -> dict:
        """Generate a context summary at specified size tier.

        Produces summaries at different verbosity levels for LLM context injection:
        - micro: ~200 chars — key facts only
        - compact: ~500 chars — core knowledge
        - standard: ~2000 chars — balanced context
        - full: ~8000 chars — comprehensive

        Args:
            size: "micro" | "compact" | "standard" | "full"
            topic: Filter by topic
            project: Filter by project
            max_chars: Override character limit

        Returns:
            Dict with summary text, entry count, and size metadata
        """
        size_limits = {
            "micro": 200,
            "compact": 500,
            "standard": 2000,
            "full": 8000,
        }
        char_limit = max_chars or size_limits.get(size, 2000)

        # Build query
        where = ["1=1"]
        params: list = []
        if topic:
            where.append("topic = ?")
            params.append(topic)
        if project:
            where.append("project = ?")
            params.append(project)

        where_sql = " AND ".join(where)

        # Get entries ordered by confidence (most confident first)
        rows = self._conn.execute(
            f"""SELECT content, topic, summary, confidence, data_layer
            FROM knowledge WHERE {where_sql}
            ORDER BY confidence DESC, created_at DESC""",
            params,
        ).fetchall()

        if not rows:
            return {
                "size": size,
                "char_limit": char_limit,
                "text": "",
                "entries_used": 0,
                "entries_total": 0,
            }

        # Build summary text within char limit
        parts = []
        chars_used = 0
        entries_used = 0

        for row in rows:
            # Use summary for micro/compact, content for standard/full
            if size in ("micro", "compact"):
                text = row["summary"] or row["content"][:80]
            else:
                text = row["content"]

            entry_text = text.strip()
            if not entry_text:
                continue

            # Check if adding this would exceed limit
            addition = f"• {entry_text}\n"
            if chars_used + len(addition) > char_limit:
                if entries_used == 0:
                    # At least include one truncated entry
                    parts.append(f"• {entry_text[:char_limit - 10]}…\n")
                    entries_used = 1
                break

            parts.append(addition)
            chars_used += len(addition)
            entries_used += 1

        return {
            "size": size,
            "char_limit": char_limit,
            "text": "".join(parts),
            "entries_used": entries_used,
            "entries_total": len(rows),
            "chars": chars_used,
        }

    def proactive_recall(
        self,
        context: str,
        *,
        limit: int = 5,
        min_score: float = 0.1,
        min_confidence: float = 0.5,
        layers: Optional[list[str]] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        include_rules: bool = True,
        include_lessons: bool = True,
    ) -> dict:
        """Proactive memory recall — "what should I remember right now?"

        Combines associative recall, policy-aware search, and incident rules
        to surface relevant memories and warnings without being explicitly asked.
        This is UAML's "intuition" feature.

        Args:
            context: Current context text (conversation, task description, etc.)
            limit: Maximum entries to return
            min_score: Minimum relevance score (0.0-1.0)
            min_confidence: Minimum confidence of returned entries
            layers: Optional list of data layers to search
            project: Optional project filter
            client_ref: Optional client filter
            include_rules: Include matching incident rules as warnings
            include_lessons: Include relevant lessons from past incidents

        Returns:
            dict with keys: memories, rules, lessons, context_summary
        """
        result = {
            "memories": [],
            "rules": [],
            "lessons": [],
            "context_summary": {
                "context_length": len(context),
                "total_found": 0,
            },
        }

        # 1. Associative recall (cross-memory linking)
        try:
            assoc_results = self.contextual_recall(
                context, limit=limit * 2, min_score=min_score
            )
            for ar in assoc_results[:limit]:
                entry = ar if isinstance(ar, dict) else {"score": 0, "entry": ar}
                result["memories"].append(entry)
        except Exception:
            pass  # Graceful degradation if associative engine unavailable

        # 2. Standard search with filters
        search_results = self.search(
            context[:500],  # Truncate long contexts for search
            limit=limit,
            project=project,
            client_ref=client_ref,
        )

        # Merge search results (avoid duplicates by ID)
        seen_ids = {m.get("id", m.get("entry", {}).get("id")) for m in result["memories"]
                     if isinstance(m, dict)}
        for sr in search_results:
            if sr.entry.id not in seen_ids and sr.entry.confidence >= min_confidence:
                result["memories"].append({
                    "id": sr.entry.id,
                    "content": sr.entry.content,
                    "topic": sr.entry.topic,
                    "score": sr.score,
                    "confidence": sr.entry.confidence,
                    "data_layer": sr.entry.data_layer,
                    "source": "search",
                })
                seen_ids.add(sr.entry.id)

        # Filter by layers if specified
        if layers:
            result["memories"] = [
                m for m in result["memories"]
                if m.get("data_layer", m.get("layer", "")) in layers
            ]

        # Trim to limit
        result["memories"] = result["memories"][:limit]

        # 3. Check incident rules
        if include_rules:
            try:
                from uaml.reasoning.incidents import IncidentPipeline
                pipeline = IncidentPipeline(self)
                matching_rules = pipeline.check_rules(context)
                result["rules"] = matching_rules[:5]
            except Exception:
                pass

        # 4. Get relevant lessons
        if include_lessons:
            try:
                from uaml.reasoning.incidents import IncidentPipeline
                pipeline = IncidentPipeline(self)
                all_lessons = pipeline.get_lessons()
                # Filter lessons relevant to context
                context_lower = context.lower()
                relevant = []
                for lesson in all_lessons:
                    title_words = set(lesson.title.lower().split())
                    context_words = set(context_lower.split())
                    overlap = title_words & context_words
                    overlap -= {"the", "a", "an", "is", "are", "to", "of", "in", "for", "and", "or"}
                    if len(overlap) >= 2:
                        relevant.append(lesson.to_dict())
                result["lessons"] = relevant[:3]
            except Exception:
                pass

        result["context_summary"]["total_found"] = (
            len(result["memories"]) + len(result["rules"]) + len(result["lessons"])
        )

        # Audit
        try:
            self._audit(
                "proactive_recall",
                details={
                    "context_length": len(context),
                    "memories": len(result["memories"]),
                    "rules": len(result["rules"]),
                    "lessons": len(result["lessons"]),
                },
            )
        except Exception:
            pass

        return result

    # ── Temporal queries ───────────────────────────────────────

    def point_in_time(self, query: str, date: str, **kwargs) -> list[SearchResult]:
        """Search knowledge valid at a specific point in time.

        This is the killer feature for legal/compliance domains.
        Example: "What privacy law applied on 2024-01-15?"
        """
        return self.search(query, point_in_time=date, **kwargs)

    # ── Contradiction Detection ──────────────────────────────────

    def _check_contradictions(
        self,
        content: str,
        *,
        topic: str = "",
        agent_id: str = "",
        project: str = "",
        client_ref: Optional[str] = None,
    ) -> Optional[ContradictionWarning]:
        """Run contradiction check against existing knowledge.

        Returns ContradictionWarning if conflicts found, None otherwise.
        Lazily initializes the ContradictionChecker on first use.
        """
        try:
            if self._contradiction_checker is None:
                from uaml.core.contradiction import ContradictionChecker as CC
                self._contradiction_checker = CC(self)

            result = self._contradiction_checker.check(
                content, topic=topic, agent_id=agent_id,
                project=project, client_ref=client_ref,
            )

            if result.has_conflict:
                return ContradictionWarning(
                    action=result.action,
                    details=result.details,
                    conflicting_ids=result.conflicting_ids,
                    superseded_ids=result.supersede_ids,
                    severity=result.severity,
                )
        except Exception:
            pass  # Contradiction check should never break main learn flow

        return None

    def get_contradictions(self, entry_id: int) -> list[dict]:
        """Get all entries that contradict a given entry (via source_links)."""
        rows = self.conn.execute(
            """SELECT sl.*, k.content, k.topic, k.created_at as entry_created
               FROM source_links sl
               JOIN knowledge k ON k.id = sl.source_id
               WHERE sl.target_id = ? AND sl.link_type = 'contradicts'
               UNION ALL
               SELECT sl.*, k.content, k.topic, k.created_at as entry_created
               FROM source_links sl
               JOIN knowledge k ON k.id = sl.target_id
               WHERE sl.source_id = ? AND sl.link_type = 'contradicts'""",
            (entry_id, entry_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_superseded(self, entry_id: Optional[int] = None) -> list[dict]:
        """Get entries that have been superseded.

        If entry_id is given, get what superseded that specific entry.
        If None, get all superseded entries.
        """
        if entry_id:
            rows = self.conn.execute(
                "SELECT * FROM knowledge WHERE id = ? AND superseded_by IS NOT NULL",
                (entry_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id, topic, content, superseded_by, created_at, updated_at "
                "FROM knowledge WHERE superseded_by IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 100",
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Internals ──────────────────────────────────────────────

    def _row_to_entry(self, row: sqlite3.Row) -> KnowledgeEntry:
        """Convert a database row to a KnowledgeEntry."""
        d = dict(row)
        return KnowledgeEntry(
            id=d.get("id"),
            content=d.get("content", ""),
            agent_id=d.get("agent_id", "default"),
            topic=d.get("topic", ""),
            summary=d.get("summary", ""),
            source_type=d.get("source_type", "manual"),
            source_ref=d.get("source_ref", ""),
            tags=d.get("tags", ""),
            confidence=d.get("confidence", 0.8),
            access_level=d.get("access_level", "internal"),
            trust_level=d.get("trust_level", "unverified"),
            valid_from=d.get("valid_from"),
            valid_until=d.get("valid_until"),
            client_ref=d.get("client_ref"),
            project=d.get("project"),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    # ── GDPR Compliance ──────────────────────────────────────────

    def grant_consent(
        self,
        client_ref: str,
        purpose: str,
        granted_by: str,
        *,
        scope: str = "all",
        evidence: str = "",
        notes: str = "",
    ) -> int:
        """Record a consent grant (GDPR Art. 7). Returns consent ID."""
        cursor = self.conn.execute(
            """INSERT INTO consents (client_ref, purpose, scope, granted_by, evidence, notes)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (client_ref, purpose, scope, granted_by, evidence, notes),
        )
        self.conn.commit()
        consent_id = cursor.lastrowid
        self._audit("grant_consent", "consents", consent_id, self.agent_id,
                     details=f"client={client_ref}, purpose={purpose}")
        return consent_id

    def revoke_consent(self, consent_id: int, revoked_by: str) -> None:
        """Revoke a consent (GDPR Art. 7(3)). Does NOT delete data — just marks consent as revoked."""
        now = __import__('datetime').datetime.now(tz=__import__('datetime').timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE consents SET revoked_at = ?, revoked_by = ? WHERE id = ?",
            (now, revoked_by, consent_id),
        )
        self.conn.commit()
        self._audit("revoke_consent", "consents", consent_id, self.agent_id,
                     details=f"revoked_by={revoked_by}")

    def list_consents(self, client_ref: str, *, active_only: bool = True) -> list[dict]:
        """List consents for a client."""
        if active_only:
            rows = self.conn.execute(
                "SELECT * FROM consents WHERE client_ref = ? AND revoked_at IS NULL ORDER BY granted_at DESC",
                (client_ref,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM consents WHERE client_ref = ? ORDER BY granted_at DESC",
                (client_ref,),
            ).fetchall()
        return [dict(r) for r in rows]

    def access_report(self, client_ref: str) -> dict:
        """Generate GDPR Art. 15 access report — everything we know about a client.

        Returns a comprehensive report of all data associated with a client_ref.
        """
        report = {
            "client_ref": client_ref,
            "generated_at": __import__('datetime').datetime.now(
                tz=__import__('datetime').timezone.utc
            ).isoformat(),
            "knowledge": [],
            "tasks": [],
            "artifacts": [],
            "consents": [],
            "audit_entries": 0,
        }

        # Knowledge entries
        rows = self.conn.execute(
            "SELECT * FROM knowledge WHERE client_ref = ? ORDER BY created_at",
            (client_ref,),
        ).fetchall()
        report["knowledge"] = [dict(r) for r in rows]

        # Tasks
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE client_ref = ? ORDER BY created_at",
            (client_ref,),
        ).fetchall()
        report["tasks"] = [dict(r) for r in rows]

        # Artifacts
        rows = self.conn.execute(
            "SELECT * FROM artifacts WHERE client_ref = ? ORDER BY created_at",
            (client_ref,),
        ).fetchall()
        report["artifacts"] = [dict(r) for r in rows]

        # Consents
        report["consents"] = self.list_consents(client_ref, active_only=False)

        # Audit count (how many operations touched this client's data)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action LIKE ?",
            (f"%client={client_ref}%",),
        ).fetchone()[0]
        report["audit_entries"] = count

        report["summary"] = {
            "total_knowledge": len(report["knowledge"]),
            "total_tasks": len(report["tasks"]),
            "total_artifacts": len(report["artifacts"]),
            "active_consents": sum(1 for c in report["consents"] if c.get("revoked_at") is None),
            "revoked_consents": sum(1 for c in report["consents"] if c.get("revoked_at") is not None),
        }

        self._audit("access_report", "mixed", 0, self.agent_id,
                     details=f"client={client_ref}")

        return report

    # ── Policy-aware recall ─────────────────────────────────

    def policy_recall(
        self,
        query: str,
        *,
        query_class: str = "operational",
        model_profile: str = "cloud_standard",
        risk_level: str = "low",
        agent_id: Optional[str] = None,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        point_in_time: Optional[str] = None,
    ) -> dict:
        """Policy-governed recall — integrates search with context budgeting.

        Resolves recall tier, output profile, and token budget before searching.
        Returns both the policy decision and the search results, limited by budget.

        Args:
            query: Search query text
            query_class: One of QueryClass values (casual, factual, operational, planning, strategic, audit)
            model_profile: One of ModelProfile values (cloud_fast, cloud_standard, etc.)
            risk_level: One of RiskLevel values (low, medium, high)
            agent_id, topic, project, client_ref, point_in_time: Standard search filters

        Returns:
            dict with 'policy' (PolicyDecision as dict) and 'results' (list of SearchResult)
        """
        from uaml.core.policy import (
            QueryClass,
            ModelProfile,
            RiskLevel,
            RecallTier,
            resolve_policy,
        )

        # Resolve policy
        qc = QueryClass(query_class)
        mp = ModelProfile(model_profile)
        rl = RiskLevel(risk_level)
        decision = resolve_policy(qc, mp, rl)

        # If recall tier is NONE, return empty results
        if decision.recall_tier == RecallTier.NONE:
            self._audit("policy_recall", "knowledge", 0, agent_id or self.agent_id,
                        details=f"tier=none|query={query[:50]}")
            return {
                "policy": {
                    "recall_tier": decision.recall_tier.value,
                    "output_profile": decision.output_profile.value,
                    "response_scope": decision.response_scope.value,
                    "budget_tokens": decision.budget_tokens,
                    "provenance_mode": decision.provenance_mode.value,
                },
                "results": [],
            }

        # Map recall tier to result limit
        tier_limits = {
            RecallTier.MICRO: 3,
            RecallTier.STANDARD: 7,
            RecallTier.FULL: 15,
        }
        limit = tier_limits.get(decision.recall_tier, 5)

        # Search with budget-appropriate limit
        results = self.search(
            query,
            limit=limit,
            agent_id=agent_id,
            topic=topic,
            project=project,
            client_ref=client_ref,
            point_in_time=point_in_time,
        )

        # Truncate results to fit token budget
        budget_remaining = decision.budget_tokens
        filtered_results = []
        for r in results:
            # SearchResult wraps a KnowledgeEntry
            content = r.entry.content if hasattr(r, 'entry') else str(r)
            # Rough token estimate: 1 token ≈ 4 chars
            estimated_tokens = len(content) // 4
            if budget_remaining >= estimated_tokens:
                filtered_results.append(r)
                budget_remaining -= estimated_tokens
            elif budget_remaining > 50:
                # Include but note truncation needed
                filtered_results.append(r)
                break

        # Audit the recall operation
        self._audit("policy_recall", "knowledge", 0, agent_id or self.agent_id,
                    details=f"tier={decision.recall_tier.value}|budget={decision.budget_tokens}|results={len(filtered_results)}|query={query[:50]}")

        return {
            "policy": {
                "recall_tier": decision.recall_tier.value,
                "output_profile": decision.output_profile.value,
                "response_scope": decision.response_scope.value,
                "budget_tokens": decision.budget_tokens,
                "provenance_mode": decision.provenance_mode.value,
            },
            "results": filtered_results,
        }

    def _audit(self, action: str, table: str, target_id: int, agent_id: str, details: str = "") -> None:
        """Record an audit log entry."""
        try:
            self.conn.execute(
                "INSERT INTO audit_log (agent_id, action, target_table, target_id) VALUES (?, ?, ?, ?)",
                (agent_id, f"{action}{'|' + details if details else ''}", table, target_id),
            )
            self.conn.commit()
        except Exception:
            pass  # Audit should never break main operations

    def focus_recall(
        self,
        query: str,
        *,
        focus_config: Optional["FocusEngineConfig"] = None,
        model_context_window: int = 128000,
        agent_id: Optional[str] = None,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        point_in_time: Optional[str] = None,
    ) -> dict:
        """Focus Engine recall — intelligent context selection with measurable rules.

        Integrates search with Focus Engine output filter for:
        - Token budget management
        - Temporal decay scoring
        - Sensitivity enforcement
        - Deduplication
        - Tiered recall (summaries → details → raw)

        This is the recommended recall method for production use.
        Falls back to policy_recall if no focus_config is provided.

        Args:
            query: Search query text
            focus_config: FocusEngineConfig (if None, uses default conservative preset)
            model_context_window: Model's total context window size
            agent_id, topic, project, client_ref, point_in_time: Search filters

        Returns:
            dict with 'focus_result' (stats), 'records' (selected data),
            'token_report' (usage), and 'decisions' (audit trail)
        """
        from uaml.core.focus_config import FocusEngineConfig, load_preset
        from uaml.core.focus_engine import FocusEngine, RecallCandidate

        if focus_config is None:
            focus_config = load_preset("conservative")

        # Search with generous limit — Focus Engine will filter
        max_candidates = min(focus_config.output_filter.max_records * 3, 50)
        results = self.search(
            query,
            limit=max_candidates,
            agent_id=agent_id,
            topic=topic,
            project=project,
            client_ref=client_ref,
            point_in_time=point_in_time,
        )

        # Convert SearchResults to RecallCandidates
        candidates = []
        for r in results:
            entry = r.entry
            candidates.append(RecallCandidate(
                entry_id=entry.id,
                content=entry.content,
                summary=entry.summary or None,
                relevance_score=r.score,
                created_at=entry.created_at if hasattr(entry, 'created_at') else None,
                sensitivity=getattr(entry, 'sensitivity', 1),
                category=entry.topic or "",
                metadata={
                    "agent_id": entry.agent_id,
                    "project": getattr(entry, 'project', ''),
                    "confidence": entry.confidence,
                },
            ))

        # Run Focus Engine
        engine = FocusEngine(focus_config)
        focus_result = engine.process(
            candidates,
            model_context_window=model_context_window,
            query_context=query,
        )

        # Generate token report
        token_report = engine.get_token_usage_report(focus_result)

        # Audit
        self._audit(
            "focus_recall", "knowledge", 0, agent_id or self.agent_id,
            details=(
                f"budget={token_report.budget}|used={token_report.used}"
                f"|selected={focus_result.total_selected}"
                f"|rejected={focus_result.total_rejected}"
                f"|tier={focus_result.recall_tier_used}"
                f"|query={query[:50]}"
            ),
        )

        return {
            "records": [
                {
                    "entry_id": rec.entry_id,
                    "content": rec.content,
                    "summary": rec.summary,
                    "relevance_score": rec.relevance_score,
                    "tokens_estimate": rec.tokens_estimate,
                    "category": rec.category,
                }
                for rec in focus_result.records
            ],
            "token_report": {
                "budget": token_report.budget,
                "used": token_report.used,
                "remaining": token_report.remaining,
                "records_selected": token_report.records_selected,
                "records_rejected": token_report.records_rejected,
                "avg_tokens_per_record": token_report.avg_tokens_per_record,
                "estimated_cost_usd": token_report.estimated_cost_usd,
                "recall_tier": token_report.recall_tier,
            },
            "decisions": [
                {
                    "entry_id": d.entry_id,
                    "included": d.included,
                    "reason": d.reason,
                    "final_score": round(d.final_score, 4),
                    "tokens_used": d.tokens_used,
                }
                for d in focus_result.decisions
            ],
            "total_candidates": focus_result.total_candidates,
            "total_selected": focus_result.total_selected,
            "utilization_pct": round(focus_result.utilization_pct, 1),
        }
