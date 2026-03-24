"""Tests for UAML REST API Server."""

import json
import threading
import time
import urllib.request
import urllib.error

import pytest

from uaml.core.store import MemoryStore
from uaml.api.server import APIServer


@pytest.fixture(scope="module")
def api_server():
    """Start API server in background thread."""
    store = MemoryStore(":memory:", agent_id="test-agent")
    # Seed data
    store.learn("Python is a programming language", topic="python", project="uaml")
    store.learn("SQLite uses B-tree indexes", topic="databases", project="uaml")
    store.learn("Neo4j is a graph database", topic="databases", project="graph")
    store.create_task("Build API", project="uaml", priority=1)
    store.create_task("Write docs", project="uaml", assigned_to="cyril")
    store.create_artifact("readme.md", artifact_type="document", project="uaml")

    server = APIServer(store, port=18780)
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    time.sleep(0.3)  # Wait for server to start
    yield "http://127.0.0.1:18780"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def _post(url: str, data: dict) -> tuple[int, dict]:
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _put(url: str, data: dict) -> tuple[int, dict]:
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="PUT", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _delete(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestHealth:
    def test_health(self, api_server):
        data = _get(f"{api_server}/api/v1/health")
        assert data["status"] == "ok"
        assert "timestamp" in data


class TestStats:
    def test_stats(self, api_server):
        data = _get(f"{api_server}/api/v1/stats")
        assert data["knowledge"] == 3
        assert data["tasks"] == 2


class TestKnowledge:
    def test_search_all(self, api_server):
        data = _get(f"{api_server}/api/v1/knowledge")
        assert data["count"] == 3

    def test_search_by_query(self, api_server):
        data = _get(f"{api_server}/api/v1/knowledge?q=Python")
        assert data["count"] >= 1
        assert any("Python" in r.get("content", "") for r in data["results"])

    def test_search_by_topic(self, api_server):
        data = _get(f"{api_server}/api/v1/knowledge?topic=databases")
        assert data["count"] == 2

    def test_search_by_project(self, api_server):
        data = _get(f"{api_server}/api/v1/knowledge?project=graph")
        assert data["count"] >= 1

    def test_get_by_id(self, api_server):
        data = _get(f"{api_server}/api/v1/knowledge/1")
        assert "content" in data
        assert "sources" in data

    def test_get_nonexistent(self, api_server):
        try:
            _get(f"{api_server}/api/v1/knowledge/9999")
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_create_knowledge(self, api_server):
        status, data = _post(f"{api_server}/api/v1/knowledge", {
            "content": "REST APIs use HTTP methods",
            "topic": "web",
            "project": "uaml",
        })
        assert status == 201
        assert data["status"] == "created"

    def test_create_without_content(self, api_server):
        status, data = _post(f"{api_server}/api/v1/knowledge", {"topic": "empty"})
        assert status == 400

    def test_delete_knowledge(self, api_server):
        # Create then delete
        status, created = _post(f"{api_server}/api/v1/knowledge", {
            "content": "Temporary entry to delete",
        })
        assert status == 201
        del_status, del_data = _delete(f"{api_server}/api/v1/knowledge/{created['id']}")
        assert del_status == 200
        assert del_data["status"] == "deleted"


class TestTasks:
    def test_list_all(self, api_server):
        data = _get(f"{api_server}/api/v1/tasks")
        assert data["count"] == 2

    def test_list_by_project(self, api_server):
        data = _get(f"{api_server}/api/v1/tasks?project=uaml")
        assert data["count"] == 2

    def test_get_by_id(self, api_server):
        data = _get(f"{api_server}/api/v1/tasks/1")
        assert "title" in data
        assert "linked_knowledge" in data

    def test_create_task(self, api_server):
        status, data = _post(f"{api_server}/api/v1/tasks", {
            "title": "New API task",
            "project": "uaml",
            "priority": 2,
        })
        assert status == 201
        assert data["status"] == "created"

    def test_create_without_title(self, api_server):
        status, data = _post(f"{api_server}/api/v1/tasks", {"project": "x"})
        assert status == 400

    def test_update_task(self, api_server):
        status, data = _put(f"{api_server}/api/v1/tasks/1", {
            "status": "in_progress",
        })
        assert status == 200
        assert data["status"] == "updated"

    def test_delete_task(self, api_server):
        # Create then delete
        status, created = _post(f"{api_server}/api/v1/tasks", {"title": "To delete"})
        del_status, del_data = _delete(f"{api_server}/api/v1/tasks/{created['id']}")
        assert del_status == 200


class TestArtifacts:
    def test_list(self, api_server):
        data = _get(f"{api_server}/api/v1/artifacts")
        assert data["count"] >= 1

    def test_create(self, api_server):
        status, data = _post(f"{api_server}/api/v1/artifacts", {
            "name": "report.pdf",
            "artifact_type": "document",
            "project": "uaml",
        })
        assert status == 201


class TestGraph:
    def test_get_graph(self, api_server):
        data = _get(f"{api_server}/api/v1/graph/1")
        assert "node" in data
        assert "sources" in data
        assert "derived" in data

    def test_graph_nonexistent(self, api_server):
        try:
            _get(f"{api_server}/api/v1/graph/9999")
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404


class TestTimeline:
    def test_timeline_all(self, api_server):
        data = _get(f"{api_server}/api/v1/timeline")
        assert data["count"] > 0
        assert all("type" in e for e in data["events"])

    def test_timeline_knowledge_only(self, api_server):
        data = _get(f"{api_server}/api/v1/timeline?type=knowledge")
        assert all(e["type"] == "knowledge" for e in data["events"])

    def test_timeline_tasks_only(self, api_server):
        data = _get(f"{api_server}/api/v1/timeline?type=task")
        assert all(e["type"] == "task" for e in data["events"])


class TestExportBackup:
    def test_export(self, api_server):
        status, data = _post(f"{api_server}/api/v1/export", {"topic": "python"})
        assert status == 200
        assert data["exported"] >= 1

    def test_backup(self, api_server):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            status, data = _post(f"{api_server}/api/v1/backup", {"target": d})
            assert status == 200
            assert "backup_id" in data


class TestNotFound:
    def test_unknown_path(self, api_server):
        try:
            _get(f"{api_server}/api/v1/nonexistent")
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
