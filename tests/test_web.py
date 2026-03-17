"""Tests for UAML Web Dashboard."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from urllib.request import urlopen, Request

import pytest

from uaml.core.store import MemoryStore
from uaml.web.app import UAMLWebApp, UAMLRequestHandler


@pytest.fixture
def app():
    """Create app with in-memory store and background server."""
    a = UAMLWebApp(db_path=":memory:")
    # Add some test data
    a.store.learn("Python is great for AI", topic="programming", tags="python,ai", data_layer="knowledge")
    a.store.learn("Neo4j is a graph database", topic="database", tags="neo4j,graph", data_layer="knowledge")
    a.store.learn("Team standup notes", topic="meeting", tags="meeting", data_layer="team")
    a.store.learn("Server config backup", topic="ops", data_layer="operational")
    server = a.serve_background(port=0)  # Random port
    port = server.server_address[1]
    time.sleep(0.1)
    yield a, port
    server.shutdown()
    a.store.close()


def get(port, path):
    """HTTP GET helper."""
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


def post_json(port, path, data):
    """HTTP POST JSON helper."""
    conn = HTTPConnection("127.0.0.1", port)
    body = json.dumps(data).encode()
    conn.request("POST", path, body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    result = resp.read().decode()
    conn.close()
    return resp.status, json.loads(result)


# ─── Page Tests ───────────────────────────────────────────

class TestPages:
    def test_dashboard(self, app):
        _, port = app
        status, body = get(port, "/")
        assert status == 200
        assert "Dashboard" in body
        assert "UAML" in body

    def test_knowledge_page(self, app):
        _, port = app
        status, body = get(port, "/knowledge")
        assert status == 200
        assert "Knowledge" in body

    def test_tasks_page(self, app):
        _, port = app
        status, body = get(port, "/tasks")
        assert status == 200
        assert "Tasks" in body

    def test_graph_page(self, app):
        _, port = app
        status, body = get(port, "/graph")
        assert status == 200
        assert "Graph" in body

    def test_timeline_page(self, app):
        _, port = app
        status, body = get(port, "/timeline")
        assert status == 200
        assert "Timeline" in body

    def test_compliance_page(self, app):
        _, port = app
        status, body = get(port, "/compliance")
        assert status == 200
        assert "Compliance" in body

    def test_export_page(self, app):
        _, port = app
        status, body = get(port, "/export")
        assert status == 200
        assert "Export" in body

    def test_settings_page(self, app):
        _, port = app
        status, body = get(port, "/settings")
        assert status == 200
        assert "Settings" in body

    def test_404(self, app):
        _, port = app
        status, _ = get(port, "/nonexistent")
        assert status == 404

    def test_static_css(self, app):
        _, port = app
        status, body = get(port, "/static/css/style.css")
        assert status == 200
        assert "var(--bg)" in body

    def test_static_js(self, app):
        _, port = app
        status, body = get(port, "/static/js/app.js")
        assert status == 200
        assert "escapeHtml" in body


# ─── API Tests ────────────────────────────────────────────

class TestAPI:
    def test_health(self, app):
        _, port = app
        status, body = get(port, "/api/health")
        assert status == 200
        data = json.loads(body)
        assert data["status"] == "ok"

    def test_stats(self, app):
        _, port = app
        status, body = get(port, "/api/stats")
        assert status == 200
        data = json.loads(body)
        assert data["knowledge"] == 4
        assert "layers" in data

    def test_knowledge_list(self, app):
        _, port = app
        status, body = get(port, "/api/knowledge")
        assert status == 200
        data = json.loads(body)
        assert data["count"] == 4

    def test_knowledge_search(self, app):
        _, port = app
        status, body = get(port, "/api/knowledge?q=python")
        assert status == 200
        data = json.loads(body)
        assert data["count"] >= 1
        assert "python" in data["entries"][0]["content"].lower()

    def test_knowledge_layer_filter(self, app):
        _, port = app
        status, body = get(port, "/api/knowledge?layer=team")
        assert status == 200
        data = json.loads(body)
        assert all(e["data_layer"] == "team" for e in data["entries"])

    def test_knowledge_detail(self, app):
        _, port = app
        status, body = get(port, "/api/knowledge/1")
        assert status == 200
        data = json.loads(body)
        assert "content" in data

    def test_knowledge_detail_404(self, app):
        _, port = app
        status, body = get(port, "/api/knowledge/99999")
        assert status == 404

    def test_timeline(self, app):
        _, port = app
        status, body = get(port, "/api/timeline?limit=10")
        assert status == 200
        data = json.loads(body)
        assert len(data["items"]) <= 10

    def test_layers(self, app):
        _, port = app
        status, body = get(port, "/api/layers")
        assert status == 200
        data = json.loads(body)
        assert len(data["layers"]) >= 2

    def test_create_knowledge(self, app):
        _, port = app
        status, data = post_json(port, "/api/knowledge", {
            "content": "New entry via API",
            "topic": "test",
            "data_layer": "knowledge",
        })
        assert status == 201
        assert data["id"] > 0

    def test_create_knowledge_no_content(self, app):
        _, port = app
        status, data = post_json(port, "/api/knowledge", {"topic": "test"})
        assert status == 400

    def test_search_post(self, app):
        _, port = app
        status, data = post_json(port, "/api/search", {"query": "graph", "limit": 3})
        assert status == 200
        assert "results" in data
