# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML REST API Server — HTTP interface for dashboards and external integrations.

Zero external dependencies (stdlib http.server + json).
Designed as the single access point for presentation layers.
Dashboard reads from this API, never directly from SQLite.

Endpoints:
    GET  /api/v1/knowledge          — search knowledge (query, topic, project, layer, client)
    GET  /api/v1/knowledge/:id      — get single entry
    POST /api/v1/knowledge          — learn new entry
    DEL  /api/v1/knowledge/:id      — forget entry

    GET  /api/v1/tasks              — list/search tasks (status, project, assigned, client)
    GET  /api/v1/tasks/:id          — get single task
    POST /api/v1/tasks              — create task
    PUT  /api/v1/tasks/:id          — update task
    DEL  /api/v1/tasks/:id          — delete task

    GET  /api/v1/artifacts          — list artifacts (project, client)
    POST /api/v1/artifacts          — create artifact

    GET  /api/v1/graph/:entity_id   — get entity with relations
    GET  /api/v1/timeline           — temporal view across all data
    GET  /api/v1/stats              — database statistics
    GET  /api/v1/health             — health check

    POST /api/v1/export             — export data (with filters)
    POST /api/v1/backup             — trigger backup

Usage:
    from uaml.api import APIServer
    from uaml.core.store import MemoryStore

    store = MemoryStore("memory.db")
    server = APIServer(store, port=8780)
    server.serve()
"""

from __future__ import annotations

import json
import re
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from uaml.core.store import MemoryStore


class APIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for UAML REST API."""

    store: MemoryStore  # Set by APIServer

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

            # Route matching
            if path == "/api/v1/health":
                self._json_response({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})

            elif path == "/api/v1/stats":
                self._json_response(self.store.stats())

            elif path == "/api/v1/layers":
                self._json_response(self.store.layer_stats())

            elif re.match(r"^/api/v1/layers/(\w+)$", path):
                layer = re.match(r"^/api/v1/layers/(\w+)$", path).group(1)
                self._handle_query_layer(layer, params)

            elif path == "/api/v1/focus-config":
                self._handle_get_focus_config()

            elif path == "/api/v1/focus-config/presets":
                self._handle_get_presets()

            elif path == "/api/v1/focus-config/params":
                self._handle_get_param_specs()

            elif path == "/api/v1/rules-log":
                self._handle_get_rules_log(params)

            elif path == "/api/v1/rules-log/stats":
                self._handle_get_rules_stats()

            elif path == "/api/v1/knowledge":
                self._handle_search_knowledge(params)

            elif re.match(r"^/api/v1/knowledge/(\d+)$", path):
                entry_id = int(re.match(r"^/api/v1/knowledge/(\d+)$", path).group(1))
                self._handle_get_knowledge(entry_id)

            elif path == "/api/v1/tasks":
                self._handle_list_tasks(params)

            elif re.match(r"^/api/v1/tasks/(\d+)$", path):
                task_id = int(re.match(r"^/api/v1/tasks/(\d+)$", path).group(1))
                self._handle_get_task(task_id)

            elif path == "/api/v1/artifacts":
                self._handle_list_artifacts(params)

            elif re.match(r"^/api/v1/graph/(\d+)$", path):
                entity_id = int(re.match(r"^/api/v1/graph/(\d+)$", path).group(1))
                self._handle_graph(entity_id)

            elif path == "/api/v1/timeline":
                self._handle_timeline(params)

            else:
                self._json_response({"error": "Not found", "path": path}, status=404)

        except Exception as e:
            self._json_response({"error": str(e), "trace": traceback.format_exc()}, status=500)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            body = self._read_body()

            if path == "/api/v1/knowledge":
                self._handle_create_knowledge(body)

            elif path == "/api/v1/tasks":
                self._handle_create_task(body)

            elif path == "/api/v1/artifacts":
                self._handle_create_artifact(body)

            elif path == "/api/v1/export":
                self._handle_export(body)

            elif path == "/api/v1/backup":
                self._handle_backup(body)

            elif path == "/api/v1/focus-recall":
                self._handle_focus_recall(body)

            else:
                self._json_response({"error": "Not found"}, status=404)

        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def do_PUT(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            body = self._read_body()

            if path == "/api/v1/focus-config":
                self._handle_put_focus_config(body)

            elif re.match(r"^/api/v1/tasks/(\d+)$", path):
                task_id = int(re.match(r"^/api/v1/tasks/(\d+)$", path).group(1))
                self._handle_update_task(task_id, body)
            else:
                self._json_response({"error": "Not found"}, status=404)

        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def do_DELETE(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if re.match(r"^/api/v1/knowledge/(\d+)$", path):
                entry_id = int(re.match(r"^/api/v1/knowledge/(\d+)$", path).group(1))
                self._handle_delete_knowledge(entry_id)

            elif re.match(r"^/api/v1/tasks/(\d+)$", path):
                task_id = int(re.match(r"^/api/v1/tasks/(\d+)$", path).group(1))
                self._handle_delete_task(task_id)

            else:
                self._json_response({"error": "Not found"}, status=404)

        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    # ── Knowledge handlers ──

    def _handle_search_knowledge(self, params: dict):
        query = params.get("q", params.get("query", ""))
        topic = params.get("topic", "")
        project = params.get("project", "")
        client_ref = params.get("client", "")
        data_layer = params.get("layer", "")
        limit = int(params.get("limit", "20"))

        if query:
            raw_results = self.store.search(
                query,
                topic=topic or None,
                limit=limit,
                client_ref=client_ref or None,
                project=project or None,
            )
            results = [
                {"id": r.entry.id, "content": r.entry.content, "topic": r.entry.topic,
                 "project": r.entry.project, "summary": r.entry.summary, "tags": r.entry.tags,
                 "confidence": r.entry.confidence, "data_layer": str(r.entry.data_layer.value) if r.entry.data_layer else None,
                 "created_at": r.entry.created_at, "score": r.score}
                for r in raw_results
            ]
        else:
            # List all (no FTS query)
            where_parts = []
            params_list: list = []
            if topic:
                where_parts.append("topic = ?")
                params_list.append(topic)
            if project:
                where_parts.append("project = ?")
                params_list.append(project)
            if client_ref:
                where_parts.append("client_ref = ?")
                params_list.append(client_ref)
            if data_layer:
                where_parts.append("data_layer = ?")
                params_list.append(data_layer)

            where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
            rows = self.store.conn.execute(
                f"SELECT * FROM knowledge {where} ORDER BY id DESC LIMIT ?",
                params_list + [limit],
            ).fetchall()
            results = [dict(r) for r in rows]

        # Filter by data_layer if FTS search was used
        if data_layer and query:
            results = [r for r in results if r.get("data_layer") == data_layer]

        self._json_response({
            "results": results,
            "count": len(results),
            "query": query,
            "filters": {k: v for k, v in {
                "topic": topic, "project": project,
                "client": client_ref, "layer": data_layer,
            }.items() if v},
        })

    def _handle_get_knowledge(self, entry_id: int):
        row = self.store.conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
        ).fetchone()
        if row:
            entry = dict(row)
            # Get source links
            sources = self.store.get_sources(entry_id)
            derived = self.store.get_derived(entry_id)
            entry["sources"] = sources
            entry["derived_from_this"] = derived
            self._json_response(entry)
        else:
            self._json_response({"error": "Not found"}, status=404)

    def _handle_create_knowledge(self, body: dict):
        content = body.get("content", "")
        if not content:
            self._json_response({"error": "content is required"}, status=400)
            return

        try:
            entry_id = self.store.learn(
                content,
                topic=body.get("topic", ""),
                summary=body.get("summary", ""),
                source_type=body.get("source_type", "manual"),
                source_ref=body.get("source_ref", ""),
                tags=body.get("tags", ""),
                confidence=body.get("confidence", 0.8),
                access_level=body.get("access_level", "internal"),
                client_ref=body.get("client_ref"),
                project=body.get("project"),
            )
            self._json_response({"id": entry_id, "status": "created"}, status=201)
        except Exception as e:
            self._json_response({"error": str(e)}, status=422)

    def _handle_delete_knowledge(self, entry_id: int):
        self.store.conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
        self.store.conn.commit()
        self.store._audit("delete", "knowledge", entry_id, self.store.agent_id)
        self._json_response({"id": entry_id, "status": "deleted"})

    # ── Task handlers ──

    def _handle_list_tasks(self, params: dict):
        status = params.get("status", "")
        project = params.get("project", "")
        assigned = params.get("assigned", params.get("assigned_to", ""))
        client_ref = params.get("client", "")
        query = params.get("q", "")
        limit = int(params.get("limit", "50"))

        if query:
            tasks = self.store.search_tasks(query, limit=limit)
        else:
            tasks = self.store.list_tasks(
                status=status or None,
                project=project or None,
                assigned_to=assigned or None,
                client_ref=client_ref or None,
                limit=limit,
            )

        self._json_response({
            "tasks": tasks,
            "count": len(tasks),
            "filters": {k: v for k, v in {
                "status": status, "project": project,
                "assigned": assigned, "client": client_ref, "q": query,
            }.items() if v},
        })

    def _handle_get_task(self, task_id: int):
        row = self.store.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row:
            task = dict(row)
            # Get linked knowledge
            knowledge = self.store.get_task_knowledge(task_id)
            task["linked_knowledge"] = knowledge
            self._json_response(task)
        else:
            self._json_response({"error": "Not found"}, status=404)

    def _handle_create_task(self, body: dict):
        title = body.get("title", "")
        if not title:
            self._json_response({"error": "title is required"}, status=400)
            return

        task_id = self.store.create_task(
            title=title,
            description=body.get("description", ""),
            status=body.get("status", "todo"),
            project=body.get("project"),
            assigned_to=body.get("assigned_to"),
            priority=body.get("priority", 0),
            tags=body.get("tags", ""),
            due_date=body.get("due_date"),
            parent_id=body.get("parent_id"),
            client_ref=body.get("client_ref"),
        )
        self._json_response({"id": task_id, "status": "created"}, status=201)

    def _handle_update_task(self, task_id: int, body: dict):
        self.store.update_task(task_id, **body)
        self._json_response({"id": task_id, "status": "updated"})

    def _handle_delete_task(self, task_id: int):
        self.store.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.store.conn.commit()
        self._json_response({"id": task_id, "status": "deleted"})

    # ── Artifact handlers ──

    def _handle_list_artifacts(self, params: dict):
        project = params.get("project", "")
        client_ref = params.get("client", "")
        limit = int(params.get("limit", "50"))

        artifacts = self.store.list_artifacts(
            project=project or None,
            client_ref=client_ref or None,
            limit=limit,
        )
        self._json_response({"artifacts": artifacts, "count": len(artifacts)})

    def _handle_create_artifact(self, body: dict):
        name = body.get("name", "")
        if not name:
            self._json_response({"error": "name is required"}, status=400)
            return

        artifact_id = self.store.create_artifact(
            name=name,
            artifact_type=body.get("artifact_type", "file"),
            path=body.get("path"),
            status=body.get("status", "draft"),
            source_origin=body.get("source_origin", "generated"),
            project=body.get("project"),
            task_id=body.get("task_id"),
            client_ref=body.get("client_ref"),
            mime_type=body.get("mime_type"),
            size_bytes=body.get("size_bytes"),
            checksum=body.get("checksum"),
        )
        self._json_response({"id": artifact_id, "status": "created"}, status=201)

    # ── Layer handler ──

    def _handle_query_layer(self, layer: str, params: dict):
        """Query entries within a specific data layer."""
        valid_layers = {"identity", "knowledge", "team", "operational", "project"}
        if layer not in valid_layers:
            self._json_response({"error": f"Invalid layer: {layer}", "valid": list(valid_layers)}, status=400)
            return

        client_ref = params.get("client", "")
        project = params.get("project", "")
        limit = int(params.get("limit", "50"))

        try:
            entries = self.store.query_layer(
                layer,
                client_ref=client_ref or None,
                project=project or None,
                limit=limit,
            )
            self._json_response({"layer": layer, "entries": entries, "count": len(entries)})
        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    # ── Graph handler ──

    def _handle_graph(self, entity_id: int):
        """Get entity with all its relations for visualization."""
        row = self.store.conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            self._json_response({"error": "Not found"}, status=404)
            return

        entry = dict(row)
        sources = self.store.get_sources(entity_id)
        derived = self.store.get_derived(entity_id)

        # Get task links
        task_links = self.store.conn.execute(
            "SELECT tk.*, t.title as task_title FROM task_knowledge tk "
            "JOIN tasks t ON tk.task_id = t.id WHERE tk.entry_id = ?",
            (entity_id,)
        ).fetchall()

        self._json_response({
            "node": entry,
            "sources": sources,
            "derived": derived,
            "task_links": [dict(r) for r in task_links],
        })

    # ── Timeline handler ──

    def _handle_timeline(self, params: dict):
        """Temporal view across all data types."""
        since = params.get("since", "")
        until = params.get("until", "")
        limit = int(params.get("limit", "50"))
        data_type = params.get("type", "")  # knowledge, task, all

        events = []

        if data_type in ("", "all", "knowledge"):
            where = "WHERE 1=1"
            qparams: list = []
            if since:
                where += " AND created_at >= ?"
                qparams.append(since)
            if until:
                where += " AND created_at <= ?"
                qparams.append(until)

            rows = self.store.conn.execute(
                f"SELECT id, content, topic, project, created_at, data_layer "
                f"FROM knowledge {where} ORDER BY created_at DESC LIMIT ?",
                qparams + [limit],
            ).fetchall()
            for r in rows:
                events.append({"type": "knowledge", **dict(r)})

        if data_type in ("", "all", "task"):
            where = "WHERE 1=1"
            qparams = []
            if since:
                where += " AND created_at >= ?"
                qparams.append(since)
            if until:
                where += " AND created_at <= ?"
                qparams.append(until)

            rows = self.store.conn.execute(
                f"SELECT id, title, status, project, created_at, assigned_to "
                f"FROM tasks {where} ORDER BY created_at DESC LIMIT ?",
                qparams + [limit],
            ).fetchall()
            for r in rows:
                events.append({"type": "task", **dict(r)})

        # Sort by created_at descending
        events.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        events = events[:limit]

        self._json_response({"events": events, "count": len(events)})

    # ── Export/Backup handlers ──

    def _handle_export(self, body: dict):
        """Trigger selective export via API."""
        from uaml.io import Exporter
        import tempfile

        exporter = Exporter(self.store)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            count = exporter.export_knowledge(
                f,
                topic=body.get("topic"),
                project=body.get("project"),
                client_ref=body.get("client"),
                data_layer=body.get("layer"),
            )
            self._json_response({
                "exported": count,
                "file": f.name,
                "format": "jsonl",
            })

    def _handle_backup(self, body: dict):
        """Trigger backup via API."""
        from uaml.io.backup import BackupManager

        target = body.get("target", "/tmp/uaml_backup")
        label = body.get("label", "")
        mgr = BackupManager(self.store)
        manifest = mgr.backup_full(target, label=label)
        self._json_response(manifest.to_dict())

    # ── Helpers ──

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    # ── Focus Engine handlers ──

    def _handle_get_focus_config(self):
        """GET /api/v1/focus-config — get current Focus Engine configuration."""
        from uaml.core.focus_config import FocusEngineConfig, load_focus_config
        config_path = getattr(self, '_focus_config_path', None)
        if config_path and Path(config_path).exists():
            try:
                config = load_focus_config(config_path)
                self._json_response(config.to_dict())
            except Exception as e:
                self._json_response({"error": str(e)}, status=500)
        else:
            # Return default config
            self._json_response(FocusEngineConfig().to_dict())

    def _handle_put_focus_config(self, body: dict):
        """PUT /api/v1/focus-config — update Focus Engine configuration.

        Human-only endpoint. Changes are logged to Rules Change Log.
        """
        from uaml.core.focus_config import (
            FocusEngineConfig,
            load_focus_config,
            save_focus_config,
            _dict_to_config,
        )
        from uaml.core.rules_changelog import RulesChangeLog, RuleChange

        try:
            new_config = _dict_to_config(body.get("config", body))
            errors = new_config.validate()
            if errors:
                self._json_response(
                    {"error": "Validation failed", "details": errors},
                    status=400,
                )
                return

            # Load old config for diff
            config_path = getattr(self, '_focus_config_path', 'focus_config.json')
            old_config = None
            if Path(config_path).exists():
                try:
                    old_config = load_focus_config(config_path)
                except Exception:
                    pass

            # Save new config
            user = body.get("user", "unknown")
            reason = body.get("reason", "")
            save_focus_config(new_config, config_path, modified_by=user)

            # Log changes to Rules Change Log
            if old_config:
                changelog_path = getattr(self, '_rules_changelog_path', 'rules_changelog.db')
                changelog = RulesChangeLog(changelog_path)
                try:
                    old_dict = old_config.to_dict()
                    new_dict = new_config.to_dict()
                    self._log_config_diff(changelog, old_dict, new_dict, user, reason)
                finally:
                    changelog.close()

            self._json_response({"status": "ok", "config": new_config.to_dict()})

        except Exception as e:
            self._json_response({"error": str(e)}, status=500)

    def _log_config_diff(self, changelog, old: dict, new: dict, user: str, reason: str, prefix: str = ""):
        """Recursively find and log config differences."""
        from uaml.core.rules_changelog import RuleChange
        for key in set(list(old.keys()) + list(new.keys())):
            path = f"{prefix}.{key}" if prefix else key
            old_val = old.get(key)
            new_val = new.get(key)
            if isinstance(old_val, dict) and isinstance(new_val, dict):
                self._log_config_diff(changelog, old_val, new_val, user, reason, path)
            elif old_val != new_val:
                changelog.log_change(RuleChange(
                    user=user,
                    rule_path=path,
                    old_value=old_val,
                    new_value=new_val,
                    reason=reason,
                ))

    def _handle_get_presets(self):
        """GET /api/v1/focus-config/presets — list available presets."""
        from uaml.core.focus_config import PRESETS
        self._json_response({
            name: config.to_dict() for name, config in PRESETS.items()
        })

    def _handle_get_param_specs(self):
        """GET /api/v1/focus-config/params — get parameter specifications.

        Returns all parameter specs with types, ranges, defaults,
        and descriptions. Designed for UI rendering.
        """
        from uaml.core.focus_config import get_all_param_specs
        specs = get_all_param_specs()
        result = {}
        for section, params in specs.items():
            result[section] = {
                name: {
                    "type": spec.type,
                    "default": spec.default,
                    "min": spec.min_val,
                    "max": spec.max_val,
                    "description": spec.description,
                    "unit": spec.unit,
                    "certification_relevant": spec.certification_relevant,
                }
                for name, spec in params.items()
            }
        self._json_response(result)

    def _handle_get_rules_log(self, params: dict):
        """GET /api/v1/rules-log — get rules change history."""
        from uaml.core.rules_changelog import RulesChangeLog
        changelog_path = getattr(self, '_rules_changelog_path', 'rules_changelog.db')
        changelog = RulesChangeLog(changelog_path)
        try:
            history = changelog.get_history(
                rule_path=params.get("rule_path"),
                user=params.get("user"),
                limit=int(params.get("limit", 50)),
                offset=int(params.get("offset", 0)),
            )
            self._json_response([
                {
                    "change_id": c.change_id,
                    "timestamp": c.timestamp,
                    "user": c.user,
                    "rule_path": c.rule_path,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "reason": c.reason,
                    "expected_impact": c.expected_impact,
                    "actual_impact": c.actual_impact,
                    "evaluation_status": c.evaluation_status,
                }
                for c in history
            ])
        finally:
            changelog.close()

    def _handle_get_rules_stats(self):
        """GET /api/v1/rules-log/stats — get rules change statistics."""
        from uaml.core.rules_changelog import RulesChangeLog
        changelog_path = getattr(self, '_rules_changelog_path', 'rules_changelog.db')
        changelog = RulesChangeLog(changelog_path)
        try:
            self._json_response(changelog.get_stats())
        finally:
            changelog.close()

    def _handle_focus_recall(self, body: dict):
        """POST /api/v1/focus-recall — intelligent recall with Focus Engine."""
        from uaml.core.focus_config import FocusEngineConfig, load_focus_config, _dict_to_config
        query = body.get("query", "")
        if not query:
            self._json_response({"error": "query is required"}, status=400)
            return

        # Load config
        focus_config = None
        config_path = getattr(self, '_focus_config_path', None)
        if config_path and Path(config_path).exists():
            try:
                focus_config = load_focus_config(config_path)
            except Exception:
                pass

        result = self.store.focus_recall(
            query,
            focus_config=focus_config,
            model_context_window=body.get("model_context_window", 128000),
            agent_id=body.get("agent_id"),
            topic=body.get("topic"),
            project=body.get("project"),
            client_ref=body.get("client_ref"),
        )
        self._json_response(result)

    def _json_response(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


class APIServer:
    """UAML REST API Server.

    Usage:
        server = APIServer(store, port=8780)
        server.serve()  # blocks
    """

    def __init__(self, store: MemoryStore, host: str = "127.0.0.1", port: int = 8780):
        self.store = store
        self.host = host
        self.port = port

    def serve(self):
        """Start the HTTP server (blocking)."""
        handler = type("Handler", (APIHandler,), {"store": self.store})
        server = HTTPServer((self.host, self.port), handler)
        print(f"UAML API server running on http://{self.host}:{self.port}/")
        server.serve_forever()

    def create_app(self) -> type:
        """Return the handler class for embedding in other servers."""
        return type("Handler", (APIHandler,), {"store": self.store})
