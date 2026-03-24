"""Tests for UAML Context Builder."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.context import ContextBuilder, ContextWindow


@pytest.fixture
def builder(tmp_path):
    store = MemoryStore(tmp_path / "ctx.db", agent_id="test")
    store.learn("Python's GIL prevents true multithreading in CPython", topic="python", confidence=0.9)
    store.learn("SQLite is a serverless database engine", topic="database", confidence=0.85)
    store.learn("Asyncio provides cooperative multitasking", topic="python", confidence=0.8)
    store.learn("PostgreSQL supports JSONB columns", topic="database", confidence=0.7)
    b = ContextBuilder(store)
    yield b
    store.close()


class TestContextBuilder:
    def test_build_basic(self, builder):
        ctx = builder.build("python threading")
        assert isinstance(ctx, ContextWindow)
        assert ctx.count > 0

    def test_text_output(self, builder):
        ctx = builder.build("python")
        text = ctx.text
        assert len(text) > 0
        assert "---" in text or ctx.count == 1

    def test_token_budget(self, builder):
        ctx = builder.build("python", max_tokens=50)
        assert ctx.token_estimate <= 60  # small budget with some overhead

    def test_max_entries(self, builder):
        ctx = builder.build("python", max_entries=1)
        assert ctx.count <= 1

    def test_confidence_filter(self, builder):
        ctx = builder.build("python", min_confidence=0.85)
        for e in ctx.entries:
            assert e.confidence >= 0.85

    def test_topic_filter(self, builder):
        ctx = builder.build("database", topics=["database"])
        for e in ctx.entries:
            assert e.topic == "database"

    def test_empty_query(self, builder):
        ctx = builder.build("")
        assert isinstance(ctx, ContextWindow)

    def test_deduplication(self, builder):
        # Add duplicate content
        builder.store.learn("Python's GIL prevents true multithreading in CPython", topic="python")
        ctx = builder.build("python GIL", deduplicate=True)
        contents = [e.content for e in ctx.entries]
        # Should have fewer entries than without dedup
        ctx_no_dedup = builder.build("python GIL", deduplicate=False)
        assert ctx.count <= ctx_no_dedup.count

    def test_context_window_empty(self):
        ctx = ContextWindow()
        assert ctx.count == 0
        assert ctx.text == ""

    def test_data_layer_filter(self, builder):
        ctx = builder.build("python", data_layers=["knowledge"])
        assert isinstance(ctx, ContextWindow)
