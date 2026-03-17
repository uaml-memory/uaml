# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Local Knowledge Graph — SQLite-based entity-relationship graph.

Provides a lightweight knowledge graph without Neo4j dependency.
Entities are linked to knowledge entries, relationships tracked
between entities.

Usage:
    from uaml.graph.local import LocalGraph

    graph = LocalGraph(store)
    graph.add_entity("Python", "language", properties={"version": "3.12"})
    graph.add_entity("UAML", "project")
    graph.add_relation("UAML", "uses", "Python")
    neighbors = graph.neighbors("UAML")
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class GraphEntity:
    """An entity in the knowledge graph."""
    name: str
    entity_type: str
    properties: dict = field(default_factory=dict)
    entry_ids: list[int] = field(default_factory=list)


@dataclass
class GraphRelation:
    """A directed relationship between entities."""
    source: str
    relation: str
    target: str
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)


class LocalGraph:
    """SQLite-based local knowledge graph."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._conn = store._conn
        self._ensure_tables()

    def _ensure_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS graph_entities (
                name TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL DEFAULT '',
                properties TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS graph_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                relation TEXT NOT NULL,
                target TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source, relation, target)
            );

            CREATE TABLE IF NOT EXISTS graph_entity_links (
                entity_name TEXT NOT NULL,
                entry_id INTEGER NOT NULL,
                PRIMARY KEY (entity_name, entry_id)
            );

            CREATE INDEX IF NOT EXISTS idx_graph_rel_source ON graph_relations(source);
            CREATE INDEX IF NOT EXISTS idx_graph_rel_target ON graph_relations(target);
            CREATE INDEX IF NOT EXISTS idx_graph_rel_type ON graph_relations(relation);
        """)

    def add_entity(
        self,
        name: str,
        entity_type: str = "",
        *,
        properties: Optional[dict] = None,
        entry_ids: Optional[list[int]] = None,
    ) -> None:
        """Add or update an entity."""
        import json
        props = json.dumps(properties or {})
        now = datetime.now(timezone.utc).isoformat()

        self._conn.execute(
            """INSERT INTO graph_entities (name, entity_type, properties, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   entity_type = excluded.entity_type,
                   properties = excluded.properties,
                   updated_at = excluded.updated_at""",
            (name, entity_type, props, now, now),
        )

        if entry_ids:
            for eid in entry_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO graph_entity_links (entity_name, entry_id) VALUES (?, ?)",
                    (name, eid),
                )

        self._conn.commit()

    def get_entity(self, name: str) -> Optional[GraphEntity]:
        """Get an entity by name."""
        import json
        row = self._conn.execute(
            "SELECT * FROM graph_entities WHERE name = ?", (name,)
        ).fetchone()

        if not row:
            return None

        links = self._conn.execute(
            "SELECT entry_id FROM graph_entity_links WHERE entity_name = ?",
            (name,),
        ).fetchall()

        return GraphEntity(
            name=row["name"],
            entity_type=row["entity_type"],
            properties=json.loads(row["properties"]) if row["properties"] else {},
            entry_ids=[l["entry_id"] for l in links],
        )

    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        *,
        weight: float = 1.0,
        metadata: Optional[dict] = None,
    ) -> None:
        """Add a directed relation between entities."""
        import json
        meta = json.dumps(metadata or {})

        self._conn.execute(
            """INSERT INTO graph_relations (source, relation, target, weight, metadata)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source, relation, target) DO UPDATE SET
                   weight = excluded.weight,
                   metadata = excluded.metadata""",
            (source, relation, target, weight, meta),
        )
        self._conn.commit()

    def neighbors(
        self,
        entity: str,
        *,
        relation: Optional[str] = None,
        direction: str = "both",
    ) -> list[GraphRelation]:
        """Find neighboring entities.

        Args:
            entity: Entity name
            relation: Filter by relation type
            direction: "outgoing", "incoming", or "both"
        """
        results = []

        if direction in ("outgoing", "both"):
            where = "source = ?"
            params: list = [entity]
            if relation:
                where += " AND relation = ?"
                params.append(relation)
            rows = self._conn.execute(
                f"SELECT * FROM graph_relations WHERE {where}", params
            ).fetchall()
            for r in rows:
                results.append(GraphRelation(
                    source=r["source"], relation=r["relation"],
                    target=r["target"], weight=r["weight"],
                ))

        if direction in ("incoming", "both"):
            where = "target = ?"
            params = [entity]
            if relation:
                where += " AND relation = ?"
                params.append(relation)
            rows = self._conn.execute(
                f"SELECT * FROM graph_relations WHERE {where}", params
            ).fetchall()
            for r in rows:
                results.append(GraphRelation(
                    source=r["source"], relation=r["relation"],
                    target=r["target"], weight=r["weight"],
                ))

        return results

    def shortest_path(
        self,
        start: str,
        end: str,
        *,
        max_depth: int = 5,
    ) -> Optional[list[str]]:
        """Find shortest path between two entities using BFS."""
        if start == end:
            return [start]

        visited = {start}
        queue = [(start, [start])]

        while queue:
            current, path = queue.pop(0)
            if len(path) > max_depth:
                break

            for rel in self.neighbors(current, direction="outgoing"):
                if rel.target == end:
                    return path + [end]
                if rel.target not in visited:
                    visited.add(rel.target)
                    queue.append((rel.target, path + [rel.target]))

        return None

    def entity_count(self) -> int:
        """Count total entities."""
        row = self._conn.execute("SELECT COUNT(*) as c FROM graph_entities").fetchone()
        return row["c"] if row else 0

    def relation_count(self) -> int:
        """Count total relations."""
        row = self._conn.execute("SELECT COUNT(*) as c FROM graph_relations").fetchone()
        return row["c"] if row else 0

    def stats(self) -> dict:
        """Graph statistics."""
        return {
            "entities": self.entity_count(),
            "relations": self.relation_count(),
            "entity_types": [
                r["entity_type"] for r in
                self._conn.execute(
                    "SELECT DISTINCT entity_type FROM graph_entities WHERE entity_type != ''"
                ).fetchall()
            ],
            "relation_types": [
                r["relation"] for r in
                self._conn.execute(
                    "SELECT DISTINCT relation FROM graph_relations"
                ).fetchall()
            ],
        }

    def remove_entity(self, name: str) -> bool:
        """Remove an entity and all its relations."""
        self._conn.execute("DELETE FROM graph_entity_links WHERE entity_name = ?", (name,))
        self._conn.execute("DELETE FROM graph_relations WHERE source = ? OR target = ?", (name, name))
        cursor = self._conn.execute("DELETE FROM graph_entities WHERE name = ?", (name,))
        self._conn.commit()
        return cursor.rowcount > 0
