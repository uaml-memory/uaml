"""Tests for UAML Knowledge Summarizer."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.summarizer import KnowledgeSummarizer


@pytest.fixture
def summarizer(tmp_path):
    store = MemoryStore(tmp_path / "sum.db", agent_id="test")
    store.learn("Python's GIL prevents true multithreading. It serializes bytecode execution.", topic="python", confidence=0.9)
    store.learn("Asyncio provides cooperative multitasking for I/O-bound tasks.", topic="python", confidence=0.8)
    store.learn("SQLite is serverless and uses a single file. Great for embedded use.", topic="database", confidence=0.85)
    s = KnowledgeSummarizer(store)
    yield s
    store.close()


class TestKnowledgeSummarizer:
    def test_topic_summary(self, summarizer):
        ts = summarizer.topic_summary("python")
        assert ts.entry_count == 2
        assert ts.avg_confidence > 0.8

    def test_key_points(self, summarizer):
        ts = summarizer.topic_summary("python")
        assert len(ts.key_points) > 0

    def test_to_text(self, summarizer):
        ts = summarizer.topic_summary("python")
        text = ts.to_text()
        assert "python" in text
        assert "entries" in text

    def test_empty_topic(self, summarizer):
        ts = summarizer.topic_summary("nonexistent")
        assert ts.entry_count == 0
        assert ts.key_points == []

    def test_store_overview(self, summarizer):
        overview = summarizer.store_overview()
        assert overview.total_entries == 3
        assert len(overview.topics) >= 2

    def test_overview_markdown(self, summarizer):
        md = summarizer.store_overview().to_markdown()
        assert "Knowledge Store Overview" in md

    def test_compress_entry(self, summarizer):
        text = summarizer.compress_entry(1)
        assert len(text) > 0

    def test_compress_nonexistent(self, summarizer):
        assert summarizer.compress_entry(999) == ""
