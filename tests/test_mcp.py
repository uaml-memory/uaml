"""Tests for UAML MCP Server."""

import json
import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.mcp.server import handle_message, handle_tool, handle_resource, TOOLS, RESOURCES


@pytest.fixture
def store():
    """Create a temporary MemoryStore for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path)
    # Seed test data
    s.learn("Python's GIL prevents true multi-threading", topic="python", tags="concurrency,threading")
    s.learn("Neo4j uses Cypher query language", topic="database", tags="neo4j,graph")
    s.learn("GDPR requires data protection by design", topic="legal", tags="gdpr,privacy",
            valid_from="2018-05-25", client_ref="client-A")
    s.learn("Old privacy law was less strict", topic="legal", tags="privacy",
            valid_from="2000-01-01", valid_until="2018-05-24", client_ref="client-A")
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


class TestToolDefinitions:
    def test_tools_have_required_fields(self):
        for tool in TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_five_tools_defined(self):
        names = [t["name"] for t in TOOLS]
        assert "memory_search" in names
        assert "memory_learn" in names
        assert "memory_entity" in names
        assert "memory_stats" in names
        assert "memory_ethics_check" in names

    def test_resources_defined(self):
        uris = [r["uri"] for r in RESOURCES]
        assert "uaml://stats" in uris
        assert "uaml://schema" in uris


class TestToolHandlers:
    def test_search(self, store):
        result = handle_tool(store, "memory_search", {"query": "GIL threading"})
        assert result["count"] >= 1
        assert any("GIL" in r["content"] for r in result["results"])

    def test_search_temporal(self, store):
        result = handle_tool(store, "memory_search", {
            "query": "privacy",
            "at_time": "2020-01-01",
            "client_ref": "client-A"
        })
        # Should find the old privacy law (valid 2000-2018), not GDPR (valid from 2018-05-25)
        assert result["count"] >= 1

    def test_search_client_isolation(self, store):
        result = handle_tool(store, "memory_search", {
            "query": "privacy",
            "client_ref": "client-B"
        })
        # Client B should find nothing (data belongs to client A)
        assert result["count"] == 0

    def test_learn(self, store):
        result = handle_tool(store, "memory_learn", {
            "content": "Test knowledge entry from MCP",
            "topic": "test",
            "tags": "mcp,test"
        })
        assert "id" in result
        assert result["status"] == "stored"

    def test_learn_dedup(self, store):
        content = "Duplicate test entry"
        r1 = handle_tool(store, "memory_learn", {"content": content})
        r2 = handle_tool(store, "memory_learn", {"content": content})
        assert r1["id"] == r2["id"]  # Same ID = deduplication worked

    def test_stats(self, store):
        result = handle_tool(store, "memory_stats", {})
        assert "knowledge" in result
        assert result["knowledge"] >= 4  # We seeded 4 entries

    def test_entity_not_found(self, store):
        result = handle_tool(store, "memory_entity", {"name": "nonexistent"})
        assert "error" in result

    def test_ethics_check_approved(self, store):
        result = handle_tool(store, "memory_ethics_check", {"content": "Python uses dynamic typing"})
        assert result["verdict"] == "APPROVED"

    def test_ethics_check_rejected(self, store):
        result = handle_tool(store, "memory_ethics_check", {"content": "password=SuperSecret123456789"})
        assert result["verdict"] == "REJECTED"

    def test_focus_recall(self, store):
        result = handle_tool(store, "memory_focus_recall", {"query": "python"})
        assert "records" in result
        assert "token_report" in result
        assert "decisions" in result

    def test_focus_recall_with_preset(self, store):
        result = handle_tool(store, "memory_focus_recall", {
            "query": "python",
            "preset": "research",
        })
        assert result["token_report"]["budget"] > 0

    def test_focus_recall_with_budget(self, store):
        result = handle_tool(store, "memory_focus_recall", {
            "query": "python",
            "token_budget": 500,
        })
        assert result["token_report"]["used"] <= 500

    def test_unknown_tool(self, store):
        result = handle_tool(store, "unknown_tool", {})
        assert "error" in result


class TestResourceHandlers:
    def test_stats_resource(self, store):
        result = handle_resource(store, "uaml://stats")
        assert "knowledge" in result

    def test_schema_resource(self, store):
        result = handle_resource(store, "uaml://schema")
        assert "version" in result
        assert "tables" in result

    def test_unknown_resource(self, store):
        result = handle_resource(store, "uaml://unknown")
        assert "error" in result


class TestJSONRPC:
    def test_initialize(self, store):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = handle_message(store, msg)
        assert resp["id"] == 1
        assert "protocolVersion" in resp["result"]
        assert resp["result"]["serverInfo"]["name"] == "uaml"

    def test_tools_list(self, store):
        msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = handle_message(store, msg)
        assert len(resp["result"]["tools"]) == 10

    def test_tools_call(self, store):
        msg = {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "Neo4j"}}
        }
        resp = handle_message(store, msg)
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["count"] >= 1

    def test_resources_list(self, store):
        msg = {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}}
        resp = handle_message(store, msg)
        assert len(resp["result"]["resources"]) == 2

    def test_resources_read(self, store):
        msg = {
            "jsonrpc": "2.0", "id": 5, "method": "resources/read",
            "params": {"uri": "uaml://stats"}
        }
        resp = handle_message(store, msg)
        content = json.loads(resp["result"]["contents"][0]["text"])
        assert "knowledge" in content

    def test_ping(self, store):
        msg = {"jsonrpc": "2.0", "id": 6, "method": "ping", "params": {}}
        resp = handle_message(store, msg)
        assert resp["id"] == 6

    def test_unknown_method(self, store):
        msg = {"jsonrpc": "2.0", "id": 7, "method": "unknown/method", "params": {}}
        resp = handle_message(store, msg)
        assert "error" in resp

    def test_notification_no_response(self, store):
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = handle_message(store, msg)
        assert resp is None
