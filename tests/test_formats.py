"""Tests for UAML Export Formats."""

from __future__ import annotations

import json
import pytest

from uaml.core.store import MemoryStore
from uaml.io.formats import ExportFormatter


@pytest.fixture
def formatter(tmp_path):
    store = MemoryStore(tmp_path / "fmt.db", agent_id="test")
    store.learn("Python is great for AI", topic="python", confidence=0.9, tags="lang,ai")
    store.learn("SQLite is fast and reliable", topic="database", confidence=0.8, tags="db")
    store.learn("UAML provides memory", topic="uaml", confidence=0.95, data_layer="knowledge")

    fmt = ExportFormatter(store)
    yield fmt
    store.close()


class TestExportFormats:
    def test_to_json(self, formatter):
        result = formatter.to_json()
        data = json.loads(result)
        assert data["count"] == 3
        assert len(data["entries"]) == 3

    def test_to_json_filtered(self, formatter):
        result = formatter.to_json(topic="python")
        data = json.loads(result)
        assert data["count"] == 1

    def test_to_jsonl(self, formatter):
        result = formatter.to_jsonl()
        lines = result.strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # Each line must be valid JSON

    def test_to_csv(self, formatter):
        result = formatter.to_csv()
        lines = result.strip().split("\n")
        assert len(lines) == 4  # header + 3 entries
        assert "topic" in lines[0]

    def test_to_csv_empty(self, tmp_path):
        store = MemoryStore(tmp_path / "empty.db", agent_id="test")
        fmt = ExportFormatter(store)
        assert fmt.to_csv() == ""
        store.close()

    def test_to_markdown(self, formatter):
        result = formatter.to_markdown()
        assert "# UAML Knowledge Export" in result
        assert "**Entries:** 3" in result
        assert "python" in result.lower()

    def test_to_markdown_no_content(self, formatter):
        result = formatter.to_markdown(include_content=False)
        assert "# UAML Knowledge Export" in result

    def test_to_dict_list(self, formatter):
        result = formatter.to_dict_list()
        assert len(result) == 3
        assert all(isinstance(r, dict) for r in result)

    def test_summary_report(self, formatter):
        result = formatter.summary_report()
        assert "Knowledge Base Summary" in result
        assert "Total entries" in result
        assert "By Topic" in result

    def test_confidence_filter(self, formatter):
        result = formatter.to_json(min_confidence=0.85)
        data = json.loads(result)
        assert data["count"] == 2  # Only 0.9 and 0.95

    def test_layer_filter(self, formatter):
        result = formatter.to_json(data_layer="knowledge")
        data = json.loads(result)
        assert data["count"] >= 1
