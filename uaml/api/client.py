# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML REST API Client — Python SDK for the UAML API server.

Zero external dependencies (stdlib urllib).

Usage:
    from uaml.api import UAMLClient

    client = UAMLClient("http://127.0.0.1:8780")
    
    # Search knowledge
    results = client.search("Python GIL")
    
    # Learn
    entry_id = client.learn("New knowledge", topic="python")
    
    # Tasks
    task_id = client.create_task("Build feature", project="myapp")
    tasks = client.list_tasks(status="todo")
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional


class UAMLClientError(Exception):
    """Raised when the API returns an error."""

    def __init__(self, message: str, status: int = 0, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


class UAMLClient:
    """Python client for the UAML REST API.

    All methods return parsed JSON dicts. Raises UAMLClientError on errors.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8780", timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ── Knowledge ──

    def search(
        self,
        query: str = "",
        *,
        topic: str = "",
        project: str = "",
        client_ref: str = "",
        layer: str = "",
        limit: int = 20,
    ) -> dict:
        """Search knowledge entries."""
        params = {"limit": str(limit)}
        if query:
            params["q"] = query
        if topic:
            params["topic"] = topic
        if project:
            params["project"] = project
        if client_ref:
            params["client"] = client_ref
        if layer:
            params["layer"] = layer
        return self._get("/api/v1/knowledge", params)

    def get_knowledge(self, entry_id: int) -> dict:
        """Get a single knowledge entry with source links."""
        return self._get(f"/api/v1/knowledge/{entry_id}")

    def learn(
        self,
        content: str,
        *,
        topic: str = "",
        summary: str = "",
        source_type: str = "manual",
        source_ref: str = "",
        tags: str = "",
        confidence: float = 0.8,
        access_level: str = "internal",
        client_ref: Optional[str] = None,
        project: Optional[str] = None,
    ) -> dict:
        """Store new knowledge via API."""
        body = {
            "content": content,
            "topic": topic,
            "summary": summary,
            "source_type": source_type,
            "source_ref": source_ref,
            "tags": tags,
            "confidence": confidence,
            "access_level": access_level,
        }
        if client_ref:
            body["client_ref"] = client_ref
        if project:
            body["project"] = project
        return self._post("/api/v1/knowledge", body)

    def delete_knowledge(self, entry_id: int) -> dict:
        """Delete a knowledge entry."""
        return self._delete(f"/api/v1/knowledge/{entry_id}")

    # ── Tasks ──

    def list_tasks(
        self,
        *,
        status: str = "",
        project: str = "",
        assigned_to: str = "",
        client_ref: str = "",
        query: str = "",
        limit: int = 50,
    ) -> dict:
        """List or search tasks."""
        params = {"limit": str(limit)}
        if status:
            params["status"] = status
        if project:
            params["project"] = project
        if assigned_to:
            params["assigned"] = assigned_to
        if client_ref:
            params["client"] = client_ref
        if query:
            params["q"] = query
        return self._get("/api/v1/tasks", params)

    def get_task(self, task_id: int) -> dict:
        """Get a single task with linked knowledge."""
        return self._get(f"/api/v1/tasks/{task_id}")

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
        client_ref: Optional[str] = None,
    ) -> dict:
        """Create a new task."""
        body: dict[str, Any] = {
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "tags": tags,
        }
        if project:
            body["project"] = project
        if assigned_to:
            body["assigned_to"] = assigned_to
        if due_date:
            body["due_date"] = due_date
        if client_ref:
            body["client_ref"] = client_ref
        return self._post("/api/v1/tasks", body)

    def update_task(self, task_id: int, **kwargs) -> dict:
        """Update a task's fields."""
        return self._put(f"/api/v1/tasks/{task_id}", kwargs)

    def delete_task(self, task_id: int) -> dict:
        """Delete a task."""
        return self._delete(f"/api/v1/tasks/{task_id}")

    # ── Artifacts ──

    def list_artifacts(
        self, *, project: str = "", client_ref: str = "", limit: int = 50
    ) -> dict:
        """List artifacts."""
        params = {"limit": str(limit)}
        if project:
            params["project"] = project
        if client_ref:
            params["client"] = client_ref
        return self._get("/api/v1/artifacts", params)

    def create_artifact(self, name: str, **kwargs) -> dict:
        """Create a new artifact."""
        body = {"name": name, **kwargs}
        return self._post("/api/v1/artifacts", body)

    # ── Layers ──

    def layer_stats(self) -> dict:
        """Get per-layer statistics."""
        return self._get("/api/v1/layers")

    def query_layer(
        self, layer: str, *, project: str = "", client_ref: str = "", limit: int = 50
    ) -> dict:
        """Query entries within a specific data layer."""
        params = {"limit": str(limit)}
        if project:
            params["project"] = project
        if client_ref:
            params["client"] = client_ref
        return self._get(f"/api/v1/layers/{layer}", params)

    # ── Graph & Timeline ──

    def graph(self, entity_id: int) -> dict:
        """Get entity with all relations for visualization."""
        return self._get(f"/api/v1/graph/{entity_id}")

    def timeline(
        self, *, since: str = "", until: str = "", data_type: str = "", limit: int = 50
    ) -> dict:
        """Get temporal view across all data types."""
        params = {"limit": str(limit)}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if data_type:
            params["type"] = data_type
        return self._get("/api/v1/timeline", params)

    # ── Utility ──

    def stats(self) -> dict:
        """Get database statistics."""
        return self._get("/api/v1/stats")

    def health(self) -> dict:
        """Health check."""
        return self._get("/api/v1/health")

    def export(
        self,
        *,
        topic: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> dict:
        """Trigger server-side export."""
        body: dict[str, Any] = {}
        if topic:
            body["topic"] = topic
        if project:
            body["project"] = project
        if client_ref:
            body["client"] = client_ref
        if layer:
            body["layer"] = layer
        return self._post("/api/v1/export", body)

    # ── HTTP helpers ──

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url + path
        if params:
            qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
            url += "?" + qs
        return self._request("GET", url)

    def _post(self, path: str, body: dict) -> dict:
        url = self.base_url + path
        return self._request("POST", url, body)

    def _put(self, path: str, body: dict) -> dict:
        url = self.base_url + path
        return self._request("PUT", url, body)

    def _delete(self, path: str) -> dict:
        url = self.base_url + path
        return self._request("DELETE", url)

    def _request(self, method: str, url: str, body: dict | None = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            try:
                error_body = json.loads(body_text)
            except json.JSONDecodeError:
                error_body = {"raw": body_text}
            raise UAMLClientError(
                f"HTTP {e.code}: {error_body.get('error', body_text)}",
                status=e.code,
                body=error_body,
            )
        except urllib.error.URLError as e:
            raise UAMLClientError(f"Connection error: {e.reason}")
