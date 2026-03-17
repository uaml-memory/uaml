# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Exporter — selective export of knowledge, tasks, and artifacts.

Supports filtering by data layer, topic, project, client, agent, and date range.
Output format: JSONL (one JSON object per line) — streaming-friendly, easy to pipe.

Security rules:
- IDENTITY layer export requires explicit --confirm-identity flag
- Client data export logs to audit trail
- Every export is audited

Usage:
    from uaml.io import Exporter

    exporter = Exporter(store)
    exporter.export_knowledge("output.jsonl", topic="python")
    exporter.export_all("full_backup.jsonl")
    exporter.export_tasks("tasks.jsonl", project="uaml")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Optional

from uaml.core.store import MemoryStore


class Exporter:
    """Export data from UAML memory store.

    Supports selective export with multiple filter dimensions.
    All exports are recorded in the audit log.
    """

    def __init__(self, store: MemoryStore):
        self.store = store

    def export_knowledge(
        self,
        output: str | Path | IO,
        *,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        agent_id: Optional[str] = None,
        data_layer: Optional[str] = None,
        tags: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        exclude_identity: bool = True,
        confirm_identity: bool = False,
        limit: int = 0,
    ) -> int:
        """Export knowledge entries to JSONL file.

        Returns the number of exported entries.

        Args:
            output: File path or file-like object
            topic: Filter by topic
            project: Filter by project
            client_ref: Filter by client (isolation)
            agent_id: Filter by agent
            data_layer: Filter by data layer (identity/knowledge/team/operational/project)
            tags: Filter by tag (substring match)
            since: Export only entries created after this date (ISO)
            until: Export only entries created before this date (ISO)
            exclude_identity: Skip IDENTITY layer entries (default: True for safety)
            confirm_identity: Must be True to export IDENTITY layer
            limit: Max entries (0 = unlimited)
        """
        # Safety: IDENTITY layer requires explicit confirmation
        if data_layer == "identity" and not confirm_identity:
            raise PermissionError(
                "IDENTITY layer export requires confirm_identity=True. "
                "Identity data is sensitive and should only be exported for backup/restore."
            )

        where_parts = []
        params: list = []

        if topic:
            where_parts.append("topic = ?")
            params.append(topic)
        if project:
            where_parts.append("project = ?")
            params.append(project)
        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)
        if agent_id:
            where_parts.append("agent_id = ?")
            params.append(agent_id)
        if data_layer:
            where_parts.append("data_layer = ?")
            params.append(data_layer)
        if tags:
            where_parts.append("tags LIKE ?")
            params.append(f"%{tags}%")
        if since:
            where_parts.append("created_at >= ?")
            params.append(since)
        if until:
            where_parts.append("created_at <= ?")
            params.append(until)
        if exclude_identity and data_layer != "identity":
            where_parts.append("(data_layer IS NULL OR data_layer != 'identity')")

        where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""

        rows = self.store.conn.execute(
            f"SELECT * FROM knowledge {where} ORDER BY id {limit_clause}",
            params,
        ).fetchall()

        count = self._write_jsonl(output, rows, "knowledge")

        # Audit
        self.store._audit(
            "export_knowledge", "knowledge", count, self.store.agent_id,
            details=f"filters={self._filter_summary(topic=topic, project=project, client_ref=client_ref, data_layer=data_layer)}"
        )

        return count

    def export_tasks(
        self,
        output: str | Path | IO,
        *,
        status: Optional[str] = None,
        project: Optional[str] = None,
        assigned_to: Optional[str] = None,
        client_ref: Optional[str] = None,
        limit: int = 0,
    ) -> int:
        """Export tasks to JSONL file. Returns count."""
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

        where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""

        rows = self.store.conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY id {limit_clause}", params
        ).fetchall()

        count = self._write_jsonl(output, rows, "task")

        self.store._audit("export_tasks", "tasks", count, self.store.agent_id)
        return count

    def export_artifacts(
        self,
        output: str | Path | IO,
        *,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        limit: int = 0,
    ) -> int:
        """Export artifacts to JSONL file. Returns count."""
        where_parts = []
        params: list = []

        if project:
            where_parts.append("project = ?")
            params.append(project)
        if client_ref:
            where_parts.append("client_ref = ?")
            params.append(client_ref)

        where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""

        rows = self.store.conn.execute(
            f"SELECT * FROM artifacts {where} ORDER BY id {limit_clause}", params
        ).fetchall()

        count = self._write_jsonl(output, rows, "artifact")
        self.store._audit("export_artifacts", "artifacts", count, self.store.agent_id)
        return count

    def export_all(
        self,
        output: str | Path | IO,
        *,
        confirm_identity: bool = False,
        client_ref: Optional[str] = None,
    ) -> dict:
        """Export everything to a single JSONL file.

        Returns dict with counts per type.
        """
        counts = {}

        # Use append mode for file paths
        if isinstance(output, (str, Path)):
            path = Path(output)
            # Clear file first
            path.write_text("")

            counts["knowledge"] = self.export_knowledge(
                output, exclude_identity=not confirm_identity,
                confirm_identity=confirm_identity, client_ref=client_ref,
            )
            counts["tasks"] = self.export_tasks(output, client_ref=client_ref)
            counts["artifacts"] = self.export_artifacts(output, client_ref=client_ref)
        else:
            counts["knowledge"] = self.export_knowledge(
                output, exclude_identity=not confirm_identity,
                confirm_identity=confirm_identity, client_ref=client_ref,
            )
            counts["tasks"] = self.export_tasks(output, client_ref=client_ref)
            counts["artifacts"] = self.export_artifacts(output, client_ref=client_ref)

        # Export source links and task-knowledge links
        links = self.store.conn.execute("SELECT * FROM source_links ORDER BY id").fetchall()
        tk_links = self.store.conn.execute("SELECT * FROM task_knowledge").fetchall()

        if isinstance(output, (str, Path)):
            with open(output, "a") as f:
                for row in links:
                    f.write(json.dumps({"_type": "source_link", **dict(row)}, ensure_ascii=False) + "\n")
                for row in tk_links:
                    f.write(json.dumps({"_type": "task_knowledge", **dict(row)}, ensure_ascii=False) + "\n")

        counts["source_links"] = len(links)
        counts["task_knowledge"] = len(tk_links)
        counts["total"] = sum(counts.values())

        return counts

    def _write_jsonl(self, output: str | Path | IO, rows: list, entry_type: str) -> int:
        """Write rows as JSONL to output. Returns count."""
        lines = []
        for row in rows:
            obj = {"_type": entry_type, **dict(row)}
            lines.append(json.dumps(obj, ensure_ascii=False))

        if isinstance(output, (str, Path)):
            mode = "a" if Path(output).exists() and Path(output).stat().st_size > 0 else "w"
            with open(output, mode) as f:
                for line in lines:
                    f.write(line + "\n")
        else:
            for line in lines:
                output.write(line + "\n")

        return len(lines)

    def export_signed(
        self,
        output: str | Path,
        *,
        confirm_identity: bool = False,
        client_ref: Optional[str] = None,
    ) -> dict:
        """Export with integrity signature (SHA-256 hash manifest).

        Creates the JSONL export plus a .sha256 manifest file for
        tamper detection on import.
        """
        import hashlib

        path = Path(output)
        counts = self.export_all(
            path, confirm_identity=confirm_identity, client_ref=client_ref,
        )

        # Compute SHA-256 of export file
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)

        manifest = {
            "file": path.name,
            "sha256": sha.hexdigest(),
            "entries": counts,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "agent_id": self.store.agent_id,
            "format": "jsonl",
            "version": "1.0",
        }

        manifest_path = path.with_suffix(path.suffix + ".sha256")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        counts["manifest"] = str(manifest_path)
        counts["sha256"] = sha.hexdigest()
        return counts

    def export_encrypted(
        self,
        output: str | Path,
        *,
        pqc_keypair=None,
        confirm_identity: bool = False,
        client_ref: Optional[str] = None,
    ) -> dict:
        """Export with PQC encryption (ML-KEM-768).

        Creates an encrypted export file that can only be decrypted
        with the corresponding private key.
        """
        import tempfile

        path = Path(output)

        # Export to temp file first
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as tmp:
            tmp_path = Path(tmp.name)

        try:
            counts = self.export_signed(
                tmp_path, confirm_identity=confirm_identity, client_ref=client_ref,
            )

            # Encrypt with PQC
            from uaml.crypto.pqc import PQCKeyPair, PQCFileEncryptor
            if not pqc_keypair:
                pqc_keypair = PQCKeyPair.generate(key_id="export")

            encryptor = PQCFileEncryptor(pqc_keypair)
            meta = encryptor.encrypt_file(tmp_path, path)

            # Also encrypt manifest
            manifest_path = tmp_path.with_suffix(tmp_path.suffix + ".sha256")
            if manifest_path.exists():
                encryptor.encrypt_file(
                    manifest_path, path.with_suffix(path.suffix + ".sha256.enc"),
                )
                manifest_path.unlink()

            counts["encrypted"] = True
            counts["algorithm"] = "ML-KEM-768"
            counts["key_id"] = pqc_keypair.key_id
            return counts
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _filter_summary(self, **kwargs) -> str:
        """Create a summary string of active filters."""
        active = {k: v for k, v in kwargs.items() if v is not None}
        if not active:
            return "all"
        return ",".join(f"{k}={v}" for k, v in active.items())
