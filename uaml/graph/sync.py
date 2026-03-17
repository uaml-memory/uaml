# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Neo4j Sync Engine — bidirectional sync between SQLite and Neo4j.

Syncs knowledge entries, entities, relationships, and reasoning traces
from UAML MemoryStore to a Neo4j knowledge graph.

Usage:
    from uaml.graph.sync import Neo4jSync

    sync = Neo4jSync(store, bolt_url="bolt://localhost:7687")
    stats = sync.push_all()       # SQLite → Neo4j
    stats = sync.push_since(ts)   # Incremental push
    stats = sync.pull_entities()  # Neo4j → SQLite (enrichment)

Optional dependency: pip install uaml[graph]  (requires neo4j driver)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol, Sequence

from ..core.store import MemoryStore


# ─── Neo4j Driver Protocol ───────────────────────────────────────────

class Neo4jDriverProtocol(Protocol):
    """Protocol for Neo4j driver-like objects."""

    def session(self, **kwargs) -> Any: ...
    def close(self) -> None: ...


class Neo4jSessionProtocol(Protocol):
    """Protocol for Neo4j session-like objects."""

    def run(self, query: str, **kwargs) -> Any: ...
    def close(self) -> None: ...
    def __enter__(self) -> "Neo4jSessionProtocol": ...
    def __exit__(self, *args) -> None: ...


# ─── Sync Stats ───────────────────────────────────────────────────────

@dataclass
class SyncStats:
    """Statistics from a sync operation."""
    nodes_created: int = 0
    nodes_updated: int = 0
    relationships_created: int = 0
    relationships_updated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def total_ops(self) -> int:
        return self.nodes_created + self.nodes_updated + self.relationships_created + self.relationships_updated

    def to_dict(self) -> dict:
        return {
            "nodes_created": self.nodes_created,
            "nodes_updated": self.nodes_updated,
            "relationships_created": self.relationships_created,
            "relationships_updated": self.relationships_updated,
            "errors": self.errors,
            "duration_ms": round(self.duration_ms, 1),
            "total_ops": self.total_ops,
        }


# ─── Node type mapping ───────────────────────────────────────────────

# Maps UAML data_layer to Neo4j node labels
LAYER_LABELS = {
    "identity": "IdentityEntry",
    "knowledge": "KnowledgeEntry",
    "team": "TeamEntry",
    "operational": "OperationalEntry",
    "project": "ProjectEntry",
}

# Maps source_type to Neo4j source node labels
SOURCE_LABELS = {
    "chat": "ChatSource",
    "research": "ResearchSource",
    "document": "DocumentSource",
    "web_page": "WebSource",
    "manual": "ManualSource",
    "log": "LogSource",
    "api": "APISource",
}


# ─── Cypher Templates ────────────────────────────────────────────────

MERGE_KNOWLEDGE = """
MERGE (k:Knowledge {uaml_id: $uaml_id})
SET k.content = $content,
    k.topic = $topic,
    k.tags = $tags,
    k.confidence = $confidence,
    k.data_layer = $data_layer,
    k.source_origin = $source_origin,
    k.source_type = $source_type,
    k.source_ref = $source_ref,
    k.agent_id = $agent_id,
    k.valid_from = $valid_from,
    k.valid_until = $valid_until,
    k.created_at = $created_at,
    k.updated_at = $updated_at,
    k.synced_at = datetime()
SET k:{label}
RETURN k.uaml_id AS id
"""

MERGE_TASK = """
MERGE (t:Task {uaml_id: $uaml_id})
SET t.title = $title,
    t.status = $status,
    t.priority = $priority,
    t.project = $project,
    t.agent_id = $agent_id,
    t.created_at = $created_at,
    t.updated_at = $updated_at,
    t.synced_at = datetime()
RETURN t.uaml_id AS id
"""

MERGE_REASONING = """
MERGE (r:ReasoningTrace {uaml_id: $uaml_id})
SET r.decision = $decision,
    r.reasoning = $reasoning,
    r.context = $context,
    r.confidence = $confidence,
    r.agent_id = $agent_id,
    r.project = $project,
    r.created_at = $created_at,
    r.synced_at = datetime()
RETURN r.uaml_id AS id
"""

LINK_EVIDENCE = """
MATCH (r:ReasoningTrace {uaml_id: $trace_id})
MATCH (k:Knowledge {uaml_id: $knowledge_id})
MERGE (r)-[e:USED_EVIDENCE]->(k)
SET e.role = $role
"""

LINK_RELATED = """
MATCH (a:Knowledge {uaml_id: $from_id})
MATCH (b:Knowledge {uaml_id: $to_id})
MERGE (a)-[r:RELATED_TO]->(b)
SET r.score = $score,
    r.method = $method
"""

LINK_TASK_KNOWLEDGE = """
MATCH (t:Task {uaml_id: $task_id})
MATCH (k:Knowledge {uaml_id: $knowledge_id})
MERGE (t)-[:REFERENCES]->(k)
"""

GET_ENRICHED = """
MATCH (k:Knowledge)
WHERE k.enriched = true AND k.synced_back = false
RETURN k.uaml_id AS id, k.content AS content, k.enriched_data AS data
LIMIT $limit
"""


# ─── Main Sync Engine ────────────────────────────────────────────────

class Neo4jSync:
    """Bidirectional sync between UAML MemoryStore and Neo4j.

    Supports:
    - Full push (all entries → Neo4j)
    - Incremental push (since timestamp)
    - Entity enrichment pull (Neo4j → SQLite)
    - Relationship sync
    - Batch operations with UNWIND
    """

    def __init__(
        self,
        store: MemoryStore,
        driver: Optional[Neo4jDriverProtocol] = None,
        bolt_url: str = "bolt://localhost:7687",
        auth: Optional[tuple[str, str]] = None,
        database: str = "neo4j",
        pqc_encrypt: bool = False,
        pqc_keypair=None,
    ):
        self.store = store
        self.database = database
        self._bolt_url = bolt_url
        self._pqc_encrypt = pqc_encrypt
        self._pqc_encryptor = None

        # Initialize PQC encryption if requested
        if pqc_encrypt:
            try:
                from uaml.crypto.pqc import PQCEncryptor
                if pqc_keypair:
                    self._pqc_encryptor = PQCEncryptor.from_keypair(pqc_keypair)
                else:
                    from uaml.crypto.pqc import PQCKeyPair
                    keypair = PQCKeyPair.generate(key_id="neo4j-sync")
                    self._pqc_encryptor = PQCEncryptor.from_keypair(keypair)
            except ImportError:
                import logging
                logging.getLogger(__name__).warning(
                    "PQC encryption requested but age-encryption not available. "
                    "Install with: pip install uaml[pqc]"
                )
                self._pqc_encrypt = False

        if driver is not None:
            self._driver = driver
        else:
            self._driver = self._connect(bolt_url, auth)

        self._ensure_sync_table()

    def _connect(self, url: str, auth: Optional[tuple[str, str]]) -> Neo4jDriverProtocol:
        """Connect to Neo4j using the official driver."""
        try:
            from neo4j import GraphDatabase
            if auth:
                return GraphDatabase.driver(url, auth=auth)
            return GraphDatabase.driver(url)
        except ImportError:
            raise ImportError(
                "neo4j driver not installed. Install with: pip install neo4j\n"
                "Or: pip install uaml[graph]"
            )

    def _ensure_sync_table(self) -> None:
        """Create sync tracking table."""
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS neo4j_sync (
                entry_type TEXT NOT NULL,
                entry_id INTEGER NOT NULL,
                synced_at TEXT NOT NULL DEFAULT (datetime('now')),
                neo4j_id TEXT,
                PRIMARY KEY (entry_type, entry_id)
            )
        """)
        self.store._conn.commit()

    def _run_cypher(self, query: str, params: dict) -> Any:
        """Execute a Cypher query."""
        with self._driver.session(database=self.database) as session:
            return session.run(query, **params)

    # ─── Push Operations ──────────────────────────────────────────

    def quality_gate(self, *, min_confidence: float = 0.3, require_topic: bool = False) -> dict:
        """Run quality checks before pushing to Neo4j.

        Validates data quality and returns a go/no-go assessment.
        """
        issues = []

        # Check for entries with very low confidence
        low_conf = self.store._conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE confidence < ?",
            (min_confidence,),
        ).fetchone()[0]
        total = self.store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

        if low_conf > 0:
            issues.append({
                "check": "confidence",
                "level": "warning",
                "message": f"{low_conf}/{total} entries below confidence {min_confidence}",
            })

        # Check for empty content
        empty = self.store._conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE content IS NULL OR content = ''"
        ).fetchone()[0]
        if empty > 0:
            issues.append({
                "check": "content",
                "level": "error",
                "message": f"{empty} entries with empty content",
            })

        # Check topic coverage
        if require_topic:
            no_topic = self.store._conn.execute(
                "SELECT COUNT(*) FROM knowledge WHERE topic IS NULL OR topic = ''"
            ).fetchone()[0]
            if no_topic > 0:
                issues.append({
                    "check": "topic",
                    "level": "warning",
                    "message": f"{no_topic} entries without topic",
                })

        # Check data layer classification
        unclassified = self.store._conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE data_layer IS NULL OR data_layer = ''"
        ).fetchone()[0]
        if unclassified > 0:
            issues.append({
                "check": "data_layer",
                "level": "info",
                "message": f"{unclassified} entries without data layer",
            })

        # Check for duplicate content
        dupes = self.store._conn.execute(
            "SELECT COUNT(*) FROM (SELECT content, COUNT(*) as cnt FROM knowledge GROUP BY content HAVING cnt > 1)"
        ).fetchone()[0]
        if dupes > 0:
            issues.append({
                "check": "duplicates",
                "level": "warning",
                "message": f"{dupes} duplicate content groups found",
            })

        has_errors = any(i["level"] == "error" for i in issues)

        return {
            "total_entries": total,
            "issues": issues,
            "issue_count": len(issues),
            "gate": "fail" if has_errors else "pass",
            "ready_for_sync": not has_errors,
        }

    def push_all(self) -> SyncStats:
        """Push all knowledge entries, tasks, and reasoning traces to Neo4j."""
        stats = SyncStats()
        t0 = time.perf_counter()

        stats = self._push_knowledge(stats)
        stats = self._push_tasks(stats)
        stats = self._push_reasoning(stats)

        stats.duration_ms = (time.perf_counter() - t0) * 1000
        return stats

    def push_since(self, since: str) -> SyncStats:
        """Incremental push — only entries created/updated after timestamp."""
        stats = SyncStats()
        t0 = time.perf_counter()

        stats = self._push_knowledge(stats, since=since)
        stats = self._push_tasks(stats, since=since)
        stats = self._push_reasoning(stats, since=since)

        stats.duration_ms = (time.perf_counter() - t0) * 1000
        return stats

    def _push_knowledge(self, stats: SyncStats, since: Optional[str] = None) -> SyncStats:
        """Push knowledge entries to Neo4j."""
        where = ""
        params: list = []
        if since:
            where = "WHERE created_at > ? OR updated_at > ?"
            params = [since, since]

        rows = self.store._conn.execute(
            f"SELECT * FROM knowledge {where} ORDER BY id", params
        ).fetchall()

        cols = [d[0] for d in self.store._conn.execute("SELECT * FROM knowledge LIMIT 0").description]

        for row in rows:
            entry = dict(zip(cols, row))
            label = LAYER_LABELS.get(entry.get("data_layer", ""), "KnowledgeEntry")

            try:
                # Encrypt content if PQC is enabled
                content = entry.get("content", "")
                if self._pqc_encrypt and self._pqc_encryptor and content:
                    import base64
                    encrypted = self._pqc_encryptor.encrypt(content.encode("utf-8"))
                    content = f"PQC:{base64.b64encode(encrypted).decode('ascii')}"

                cypher = MERGE_KNOWLEDGE.replace("{label}", label)
                self._run_cypher(cypher, {
                    "uaml_id": entry["id"],
                    "content": content,
                    "topic": entry.get("topic", ""),
                    "tags": entry.get("tags", ""),
                    "confidence": entry.get("confidence", 0.5),
                    "data_layer": entry.get("data_layer", "knowledge"),
                    "source_origin": entry.get("source_origin", ""),
                    "source_type": entry.get("source_type", ""),
                    "source_ref": entry.get("source_ref", ""),
                    "agent_id": entry.get("agent_id", ""),
                    "valid_from": entry.get("valid_from", ""),
                    "valid_until": entry.get("valid_until", ""),
                    "created_at": entry.get("created_at", ""),
                    "updated_at": entry.get("updated_at", ""),
                })

                # Track sync
                self.store._conn.execute(
                    "INSERT OR REPLACE INTO neo4j_sync (entry_type, entry_id, neo4j_id) VALUES (?, ?, ?)",
                    ("knowledge", entry["id"], str(entry["id"])),
                )
                stats.nodes_created += 1

            except Exception as e:
                stats.errors.append(f"knowledge:{entry['id']}: {e}")

        self.store._conn.commit()
        return stats

    def _push_tasks(self, stats: SyncStats, since: Optional[str] = None) -> SyncStats:
        """Push tasks to Neo4j."""
        # Check if tasks table exists
        table_check = self.store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if not table_check:
            return stats

        where = ""
        params: list = []
        if since:
            where = "WHERE created_at > ? OR updated_at > ?"
            params = [since, since]

        rows = self.store._conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY id", params
        ).fetchall()

        cols = [d[0] for d in self.store._conn.execute("SELECT * FROM tasks LIMIT 0").description]

        for row in rows:
            entry = dict(zip(cols, row))
            try:
                self._run_cypher(MERGE_TASK, {
                    "uaml_id": entry["id"],
                    "title": entry.get("title", ""),
                    "status": entry.get("status", "open"),
                    "priority": entry.get("priority", "medium"),
                    "project": entry.get("project", ""),
                    "agent_id": entry.get("agent_id", ""),
                    "created_at": entry.get("created_at", ""),
                    "updated_at": entry.get("updated_at", ""),
                })

                self.store._conn.execute(
                    "INSERT OR REPLACE INTO neo4j_sync (entry_type, entry_id, neo4j_id) VALUES (?, ?, ?)",
                    ("task", entry["id"], str(entry["id"])),
                )
                stats.nodes_created += 1

            except Exception as e:
                stats.errors.append(f"task:{entry['id']}: {e}")

        self.store._conn.commit()
        return stats

    def _push_reasoning(self, stats: SyncStats, since: Optional[str] = None) -> SyncStats:
        """Push reasoning traces to Neo4j."""
        table_check = self.store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reasoning_traces'"
        ).fetchone()
        if not table_check:
            return stats

        where = ""
        params: list = []
        if since:
            where = "WHERE created_at > ?"
            params = [since]

        rows = self.store._conn.execute(
            f"SELECT * FROM reasoning_traces {where} ORDER BY id", params
        ).fetchall()

        cols = [d[0] for d in self.store._conn.execute("SELECT * FROM reasoning_traces LIMIT 0").description]

        for row in rows:
            entry = dict(zip(cols, row))
            try:
                self._run_cypher(MERGE_REASONING, {
                    "uaml_id": entry["id"],
                    "decision": entry.get("decision", ""),
                    "reasoning": entry.get("reasoning", ""),
                    "context": entry.get("context", ""),
                    "confidence": entry.get("confidence", 0.5),
                    "agent_id": entry.get("agent_id", ""),
                    "project": entry.get("project", ""),
                    "created_at": entry.get("created_at", ""),
                })

                # Push evidence links
                evidence_rows = self.store._conn.execute(
                    "SELECT * FROM reasoning_evidence WHERE trace_id = ?",
                    (entry["id"],)
                ).fetchall()
                ev_cols = [d[0] for d in self.store._conn.execute("SELECT * FROM reasoning_evidence LIMIT 0").description]

                for ev_row in evidence_rows:
                    ev = dict(zip(ev_cols, ev_row))
                    try:
                        self._run_cypher(LINK_EVIDENCE, {
                            "trace_id": entry["id"],
                            "knowledge_id": ev["entry_id"],
                            "role": ev.get("role", "evidence"),
                        })
                        stats.relationships_created += 1
                    except Exception:
                        pass

                self.store._conn.execute(
                    "INSERT OR REPLACE INTO neo4j_sync (entry_type, entry_id, neo4j_id) VALUES (?, ?, ?)",
                    ("reasoning", entry["id"], str(entry["id"])),
                )
                stats.nodes_created += 1

            except Exception as e:
                stats.errors.append(f"reasoning:{entry['id']}: {e}")

        self.store._conn.commit()
        return stats

    # ─── Pull Operations ──────────────────────────────────────────

    def pull_entities(self, limit: int = 100) -> SyncStats:
        """Pull enriched entities from Neo4j back to SQLite.

        For entities that have been enriched in Neo4j (e.g., by entity
        extraction, manual annotation, or graph algorithms), sync the
        enrichment data back to the UAML store.
        """
        stats = SyncStats()
        t0 = time.perf_counter()

        try:
            result = self._run_cypher(GET_ENRICHED, {"limit": limit})
            for record in result:
                entry_id = record["id"]
                data = record.get("data", "{}")
                try:
                    # Update knowledge entry with enriched data
                    if isinstance(data, str):
                        enriched = json.loads(data)
                    else:
                        enriched = data

                    # Merge enriched tags/topics
                    if "tags" in enriched:
                        self.store._conn.execute(
                            "UPDATE knowledge SET tags = tags || ',' || ? WHERE id = ?",
                            (enriched["tags"], entry_id),
                        )
                    if "topic" in enriched:
                        self.store._conn.execute(
                            "UPDATE knowledge SET topic = ? WHERE id = ?",
                            (enriched["topic"], entry_id),
                        )
                    stats.nodes_updated += 1

                    # Mark as synced back in Neo4j
                    self._run_cypher(
                        "MATCH (k:Knowledge {uaml_id: $id}) SET k.synced_back = true",
                        {"id": entry_id},
                    )
                except Exception as e:
                    stats.errors.append(f"pull:{entry_id}: {e}")

            self.store._conn.commit()
        except Exception as e:
            stats.errors.append(f"pull_entities: {e}")

        stats.duration_ms = (time.perf_counter() - t0) * 1000
        return stats

    # ─── Relationship Sync ────────────────────────────────────────

    def push_associations(self, min_score: float = 0.3) -> SyncStats:
        """Push associative relationships to Neo4j.

        Uses the AssociativeEngine to find related entries and
        creates RELATED_TO relationships in Neo4j.
        """
        stats = SyncStats()
        t0 = time.perf_counter()

        try:
            from ..core.associative import AssociativeEngine
            engine = AssociativeEngine(self.store)
        except ImportError:
            stats.errors.append("AssociativeEngine not available")
            stats.duration_ms = (time.perf_counter() - t0) * 1000
            return stats

        # Get all entry IDs
        rows = self.store._conn.execute("SELECT id FROM knowledge").fetchall()

        for (entry_id,) in rows:
            try:
                related = engine.find_related(entry_id, limit=5, min_score=min_score)
                for r in related:
                    try:
                        self._run_cypher(LINK_RELATED, {
                            "from_id": entry_id,
                            "to_id": r.entry_id,
                            "score": r.score,
                            "method": "associative",
                        })
                        stats.relationships_created += 1
                    except Exception as e:
                        stats.errors.append(f"rel:{entry_id}->{r.entry_id}: {e}")
            except Exception:
                pass

        stats.duration_ms = (time.perf_counter() - t0) * 1000
        return stats

    # ─── Expert Graph Queries ─────────────────────────────────────

    def graph_search(self, query: str, *, limit: int = 10) -> list[dict]:
        """Search knowledge graph using Cypher full-text or keyword match.

        Returns nodes with their graph context (relationships, neighbors).
        """
        results = []
        try:
            rows = self._run_cypher(
                """MATCH (k:KnowledgeEntry)
                WHERE k.content CONTAINS $query OR k.topic CONTAINS $query
                    OR k.tags CONTAINS $query
                RETURN k.uaml_id AS id, k.content AS content, k.topic AS topic,
                       k.confidence AS confidence, k.data_layer AS layer
                ORDER BY k.confidence DESC
                LIMIT $limit""",
                {"query": query, "limit": limit},
            )
            if rows:
                for record in rows:
                    results.append(dict(record))
        except Exception:
            pass
        return results

    def graph_neighbors(self, entry_id: int, *, depth: int = 1, limit: int = 20) -> dict:
        """Get graph neighborhood of a knowledge entry.

        Returns the entry and its neighbors up to given depth.
        """
        result = {"center": None, "neighbors": [], "relationships": []}
        try:
            # Get center node
            center_rows = self._run_cypher(
                """MATCH (k:KnowledgeEntry {uaml_id: $id})
                RETURN k.uaml_id AS id, k.content AS content, k.topic AS topic""",
                {"id": entry_id},
            )
            if center_rows:
                result["center"] = dict(center_rows[0])

            # Get neighbors
            neighbor_rows = self._run_cypher(
                """MATCH (k:KnowledgeEntry {uaml_id: $id})-[r]-(n)
                RETURN n.uaml_id AS id, n.content AS content, n.topic AS topic,
                       type(r) AS rel_type, r.score AS score
                LIMIT $limit""",
                {"id": entry_id, "limit": limit},
            )
            if neighbor_rows:
                for record in neighbor_rows:
                    d = dict(record)
                    result["neighbors"].append({
                        "id": d.get("id"),
                        "content": d.get("content", "")[:200],
                        "topic": d.get("topic"),
                    })
                    result["relationships"].append({
                        "target_id": d.get("id"),
                        "type": d.get("rel_type"),
                        "score": d.get("score"),
                    })
        except Exception:
            pass
        return result

    def graph_path(self, from_id: int, to_id: int, *, max_depth: int = 4) -> list[dict]:
        """Find shortest path between two knowledge entries in the graph."""
        try:
            rows = self._run_cypher(
                """MATCH path = shortestPath(
                    (a:KnowledgeEntry {uaml_id: $from})-[*..%d]-(b:KnowledgeEntry {uaml_id: $to})
                )
                RETURN [n IN nodes(path) | {id: n.uaml_id, topic: n.topic}] AS nodes,
                       [r IN relationships(path) | {type: type(r), score: r.score}] AS rels""" % max_depth,
                {"from": from_id, "to": to_id},
            )
            if rows:
                record = rows[0]
                return [{"nodes": record["nodes"], "relationships": record["rels"]}]
        except Exception:
            pass
        return []

    def graph_clusters(self, *, min_size: int = 3, limit: int = 10) -> list[dict]:
        """Detect topic clusters in the knowledge graph.

        Returns groups of densely connected entries.
        """
        clusters = []
        try:
            rows = self._run_cypher(
                """MATCH (k:KnowledgeEntry)
                WITH k.topic AS topic, collect(k.uaml_id) AS ids, count(*) AS size
                WHERE size >= $min_size
                RETURN topic, ids, size
                ORDER BY size DESC
                LIMIT $limit""",
                {"min_size": min_size, "limit": limit},
            )
            if rows:
                for record in rows:
                    clusters.append(dict(record))
        except Exception:
            pass
        return clusters

    # ─── Status & Utilities ───────────────────────────────────────

    def sync_status(self) -> dict:
        """Get sync status — what's been synced and what's pending."""
        synced = {}
        for entry_type in ("knowledge", "task", "reasoning"):
            count = self.store._conn.execute(
                "SELECT COUNT(*) FROM neo4j_sync WHERE entry_type = ?",
                (entry_type,),
            ).fetchone()[0]
            synced[entry_type] = count

        total_knowledge = self.store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]

        task_check = self.store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        total_tasks = self.store._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] if task_check else 0

        trace_check = self.store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reasoning_traces'"
        ).fetchone()
        total_reasoning = self.store._conn.execute("SELECT COUNT(*) FROM reasoning_traces").fetchone()[0] if trace_check else 0

        return {
            "synced": synced,
            "pending": {
                "knowledge": total_knowledge - synced.get("knowledge", 0),
                "task": total_tasks - synced.get("task", 0),
                "reasoning": total_reasoning - synced.get("reasoning", 0),
            },
            "total": {
                "knowledge": total_knowledge,
                "task": total_tasks,
                "reasoning": total_reasoning,
            },
            "pqc_encryption": {
                "enabled": self._pqc_encrypt,
                "algorithm": "ML-KEM-768" if self._pqc_encrypt else None,
                "scope": "content" if self._pqc_encrypt else None,
            },
        }

    def close(self) -> None:
        """Close Neo4j driver connection."""
        if hasattr(self._driver, "close"):
            self._driver.close()
