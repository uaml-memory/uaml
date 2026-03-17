# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Importer — import knowledge, tasks, and artifacts from JSONL.

Re-applies ethics checks on imported content (enforce mode).
Deduplicates against existing entries.
All imports are audited.

Usage:
    from uaml.io import Importer

    importer = Importer(store)
    stats = importer.import_file("backup.jsonl")
    print(f"Imported: {stats}")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Optional

from uaml.core.store import MemoryStore


class ImportStats:
    """Track import statistics."""

    def __init__(self):
        self.imported = 0
        self.skipped_dedup = 0
        self.skipped_ethics = 0
        self.errors = 0
        self.by_type: dict[str, int] = {}

    def __repr__(self):
        return (
            f"ImportStats(imported={self.imported}, "
            f"skipped_dedup={self.skipped_dedup}, "
            f"skipped_ethics={self.skipped_ethics}, "
            f"errors={self.errors})"
        )

    def to_dict(self) -> dict:
        return {
            "imported": self.imported,
            "skipped_dedup": self.skipped_dedup,
            "skipped_ethics": self.skipped_ethics,
            "errors": self.errors,
            "by_type": self.by_type,
        }


class Importer:
    """Import data into UAML memory store from JSONL.

    Features:
    - Deduplication against existing entries
    - Ethics re-check on imported content (if checker configured)
    - Audit trail for all imports
    - Supports knowledge, tasks, artifacts, source_links, task_knowledge
    """

    def __init__(self, store: MemoryStore, remap_ids: bool = True):
        """
        Args:
            store: Target MemoryStore
            remap_ids: If True, assign new IDs (default for merge imports)
        """
        self.store = store
        self.remap_ids = remap_ids
        self._id_map: dict[str, dict[int, int]] = {
            "knowledge": {},
            "task": {},
            "artifact": {},
        }

    def import_file(
        self,
        input_path: str | Path,
        *,
        override_agent: Optional[str] = None,
        override_project: Optional[str] = None,
        override_client: Optional[str] = None,
    ) -> ImportStats:
        """Import from a JSONL file.

        Args:
            input_path: Path to JSONL file
            override_agent: Override agent_id on all imported entries
            override_project: Override project on all imported entries
            override_client: Override client_ref on all imported entries
        """
        stats = ImportStats()

        with open(input_path) as f:
            # First pass: knowledge, tasks, artifacts (to build ID map)
            lines = f.readlines()

        # Sort: knowledge first, then tasks, then artifacts, then links
        type_order = {"knowledge": 0, "task": 1, "artifact": 2, "source_link": 3, "task_knowledge": 4}
        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                entries.append(obj)
            except json.JSONDecodeError:
                stats.errors += 1

        entries.sort(key=lambda x: type_order.get(x.get("_type", ""), 99))

        for obj in entries:
            entry_type = obj.pop("_type", "knowledge")

            # Apply overrides
            if override_agent and "agent_id" in obj:
                obj["agent_id"] = override_agent
            if override_project and "project" in obj:
                obj["project"] = override_project
            if override_client and "client_ref" in obj:
                obj["client_ref"] = override_client

            try:
                if entry_type == "knowledge":
                    self._import_knowledge(obj, stats)
                elif entry_type == "task":
                    self._import_task(obj, stats)
                elif entry_type == "artifact":
                    self._import_artifact(obj, stats)
                elif entry_type == "source_link":
                    self._import_source_link(obj, stats)
                elif entry_type == "task_knowledge":
                    self._import_task_knowledge(obj, stats)
                else:
                    stats.errors += 1
            except Exception:
                stats.errors += 1

        # Audit
        self.store._audit(
            "import", "mixed", stats.imported, self.store.agent_id,
            details=str(stats.to_dict()),
        )

        return stats

    def _import_knowledge(self, obj: dict, stats: ImportStats) -> None:
        """Import a knowledge entry with dedup and ethics check."""
        old_id = obj.pop("id", None)
        obj.pop("rank", None)  # Remove FTS rank if present

        content = obj.get("content", "")
        if not content:
            stats.errors += 1
            return

        # Ethics check via store (if checker configured)
        try:
            new_id = self.store.learn(
                content,
                topic=obj.get("topic", ""),
                summary=obj.get("summary", ""),
                source_type=obj.get("source_type", "manual"),
                source_ref=obj.get("source_ref", ""),
                tags=obj.get("tags", ""),
                confidence=obj.get("confidence", 0.8),
                access_level=obj.get("access_level", "internal"),
                trust_level=obj.get("trust_level", "unverified"),
                valid_from=obj.get("valid_from"),
                valid_until=obj.get("valid_until"),
                client_ref=obj.get("client_ref"),
                project=obj.get("project"),
                agent_id=obj.get("agent_id"),
                dedup=True,
            )
        except Exception as e:
            if "EthicsViolation" in type(e).__name__:
                stats.skipped_ethics += 1
                return
            raise

        # Check if dedup happened (learn returns existing ID)
        if old_id and new_id != old_id:
            # Could be dedup or new entry
            pass

        if old_id:
            self._id_map["knowledge"][old_id] = new_id

        stats.imported += 1
        stats.by_type["knowledge"] = stats.by_type.get("knowledge", 0) + 1

    def _import_task(self, obj: dict, stats: ImportStats) -> None:
        """Import a task."""
        old_id = obj.pop("id", None)
        obj.pop("rank", None)

        new_id = self.store.create_task(
            title=obj.get("title", "Untitled"),
            description=obj.get("description", ""),
            status=obj.get("status", "todo"),
            project=obj.get("project"),
            assigned_to=obj.get("assigned_to"),
            priority=obj.get("priority", 0),
            tags=obj.get("tags", ""),
            due_date=obj.get("due_date"),
            parent_id=obj.get("parent_id"),
            client_ref=obj.get("client_ref"),
        )

        if old_id:
            self._id_map["task"][old_id] = new_id

        stats.imported += 1
        stats.by_type["task"] = stats.by_type.get("task", 0) + 1

    def _import_artifact(self, obj: dict, stats: ImportStats) -> None:
        """Import an artifact."""
        old_id = obj.pop("id", None)

        # Remap task_id if needed
        task_id = obj.get("task_id")
        if task_id and task_id in self._id_map.get("task", {}):
            task_id = self._id_map["task"][task_id]

        new_id = self.store.create_artifact(
            name=obj.get("name", "unknown"),
            artifact_type=obj.get("artifact_type", "file"),
            path=obj.get("path"),
            status=obj.get("status", "draft"),
            source_origin=obj.get("source_origin", "generated"),
            project=obj.get("project"),
            task_id=task_id,
            client_ref=obj.get("client_ref"),
            mime_type=obj.get("mime_type"),
            size_bytes=obj.get("size_bytes"),
            checksum=obj.get("checksum"),
        )

        if old_id:
            self._id_map["artifact"][old_id] = new_id

        stats.imported += 1
        stats.by_type["artifact"] = stats.by_type.get("artifact", 0) + 1

    def _import_source_link(self, obj: dict, stats: ImportStats) -> None:
        """Import a source link with ID remapping."""
        source_id = self._id_map.get("knowledge", {}).get(obj.get("source_id", 0), obj.get("source_id"))
        target_id = self._id_map.get("knowledge", {}).get(obj.get("target_id", 0), obj.get("target_id"))

        if source_id and target_id:
            self.store.link_source(
                source_id, target_id,
                link_type=obj.get("link_type", "based_on"),
                confidence=obj.get("confidence", 0.8),
                notes=obj.get("notes", ""),
            )
            stats.imported += 1
            stats.by_type["source_link"] = stats.by_type.get("source_link", 0) + 1

    def _import_task_knowledge(self, obj: dict, stats: ImportStats) -> None:
        """Import a task-knowledge link with ID remapping."""
        task_id = self._id_map.get("task", {}).get(obj.get("task_id", 0), obj.get("task_id"))
        entry_id = self._id_map.get("knowledge", {}).get(obj.get("entry_id", 0), obj.get("entry_id"))

        if task_id and entry_id:
            self.store.link_task_knowledge(
                task_id, entry_id,
                relation=obj.get("relation", "related"),
            )
            stats.imported += 1
            stats.by_type["task_knowledge"] = stats.by_type.get("task_knowledge", 0) + 1
