"""Tests for UAML REST API client — integration tests with in-process server."""

import tempfile
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest

from uaml.api.client import UAMLClient, UAMLClientError
from uaml.api.server import APIHandler
from uaml.core.store import MemoryStore


@pytest.fixture
def server_and_client():
    """Start an API server in a thread and return (store, client)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = MemoryStore(db_path, agent_id="test-api")

    # Seed data
    store.learn("Python uses reference counting for memory management", topic="python", tags="memory,gc")
    store.learn("Neo4j is a graph database using Cypher query language", topic="database", project="uaml")
    store.learn("GDPR requires explicit consent for personal data processing", topic="legal", client_ref="client-A")
    store.create_task("Implement MCP server", project="uaml", assigned_to="cyril")
    store.create_task("Write documentation", project="uaml", assigned_to="metod", status="in_progress")
    store.create_artifact("design.pdf", project="uaml", artifact_type="document")

    handler = type("Handler", (APIHandler,), {"store": store})
    server = HTTPServer(("127.0.0.1", 0), handler)  # port 0 = auto-assign
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)  # Let server start

    client = UAMLClient(f"http://127.0.0.1:{port}", timeout=5)

    yield store, client

    server.shutdown()
    store.close()
    Path(db_path).unlink(missing_ok=True)


class TestHealth:
    def test_health_check(self, server_and_client):
        _, client = server_and_client
        result = client.health()
        assert result["status"] == "ok"
        assert "timestamp" in result


class TestKnowledge:
    def test_search(self, server_and_client):
        _, client = server_and_client
        result = client.search("Python memory")
        assert result["count"] >= 1
        assert any("Python" in r.get("content", "") for r in result["results"])

    def test_search_with_topic(self, server_and_client):
        _, client = server_and_client
        result = client.search("", topic="legal")
        assert result["count"] >= 1

    def test_get_knowledge(self, server_and_client):
        _, client = server_and_client
        result = client.get_knowledge(1)
        assert "content" in result
        assert "Python" in result["content"]

    def test_get_knowledge_not_found(self, server_and_client):
        _, client = server_and_client
        with pytest.raises(UAMLClientError) as exc_info:
            client.get_knowledge(9999)
        assert exc_info.value.status == 404

    def test_learn(self, server_and_client):
        _, client = server_and_client
        result = client.learn(
            "SQLite FTS5 is excellent for full-text search",
            topic="database",
            tags="sqlite,fts",
        )
        assert result["status"] == "created"
        assert "id" in result

    def test_delete_knowledge(self, server_and_client):
        _, client = server_and_client
        # Create then delete
        created = client.learn("Temporary entry for deletion test purposes")
        entry_id = created["id"]
        result = client.delete_knowledge(entry_id)
        assert result["status"] == "deleted"


class TestTasks:
    def test_list_tasks(self, server_and_client):
        _, client = server_and_client
        result = client.list_tasks()
        assert result["count"] == 2

    def test_list_tasks_by_status(self, server_and_client):
        _, client = server_and_client
        result = client.list_tasks(status="in_progress")
        assert result["count"] >= 1

    def test_list_tasks_by_assigned(self, server_and_client):
        _, client = server_and_client
        result = client.list_tasks(assigned_to="cyril")
        assert result["count"] >= 1

    def test_get_task(self, server_and_client):
        _, client = server_and_client
        result = client.get_task(1)
        assert "title" in result

    def test_create_task(self, server_and_client):
        _, client = server_and_client
        result = client.create_task(
            "New API test task",
            project="uaml",
            assigned_to="cyril",
            priority=2,
        )
        assert result["status"] == "created"

    def test_update_task(self, server_and_client):
        _, client = server_and_client
        result = client.update_task(1, status="done")
        assert result["status"] == "updated"

    def test_delete_task(self, server_and_client):
        _, client = server_and_client
        created = client.create_task("Task to delete")
        result = client.delete_task(created["id"])
        assert result["status"] == "deleted"


class TestArtifacts:
    def test_list_artifacts(self, server_and_client):
        _, client = server_and_client
        result = client.list_artifacts()
        assert result["count"] >= 1

    def test_create_artifact(self, server_and_client):
        _, client = server_and_client
        result = client.create_artifact("test.py", artifact_type="code", project="uaml")
        assert result["status"] == "created"


class TestLayers:
    def test_layer_stats(self, server_and_client):
        _, client = server_and_client
        result = client.layer_stats()
        assert isinstance(result, dict)

    def test_query_layer(self, server_and_client):
        store, client = server_and_client
        # Add entry with explicit layer
        store.learn("Test knowledge entry", data_layer="knowledge")
        result = client.query_layer("knowledge")
        assert "entries" in result


class TestTimeline:
    def test_timeline(self, server_and_client):
        _, client = server_and_client
        result = client.timeline()
        assert "events" in result
        assert result["count"] > 0

    def test_timeline_by_type(self, server_and_client):
        _, client = server_and_client
        result = client.timeline(data_type="task")
        assert all(e["type"] == "task" for e in result["events"])


class TestStats:
    def test_stats(self, server_and_client):
        _, client = server_and_client
        result = client.stats()
        assert "knowledge" in result


class TestErrors:
    def test_connection_error(self):
        client = UAMLClient("http://127.0.0.1:1", timeout=1)
        with pytest.raises(UAMLClientError):
            client.health()
