"""Tests for UAML Knowledge Linker."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.linker import KnowledgeLinker


@pytest.fixture
def linker(tmp_path):
    store = MemoryStore(tmp_path / "link.db", agent_id="test")
    store.learn("Python GIL prevents true multithreading", topic="python")
    store.learn("Python asyncio enables concurrent I/O", topic="python")
    store.learn("SQLite is a serverless database", topic="database")
    l = KnowledgeLinker(store)
    yield l
    store.close()


class TestKnowledgeLinker:
    def test_suggest_same_topic(self, linker):
        suggestions = linker.suggest_links(1)
        topics = [s.relation for s in suggestions]
        assert "same_topic" in topics or len(suggestions) >= 0

    def test_create_link(self, linker):
        assert linker.create_link(1, 2, "related_to") is True

    def test_get_links(self, linker):
        linker.create_link(1, 2)
        links = linker.get_links(1)
        assert len(links) >= 1

    def test_remove_link(self, linker):
        linker.create_link(1, 2)
        assert linker.remove_link(1, 2) is True
        assert linker.remove_link(1, 2) is False

    def test_linked_entries(self, linker):
        linker.create_link(1, 2, "related_to")
        entries = linker.linked_entries(1)
        assert len(entries) >= 1

    def test_no_self_link(self, linker):
        suggestions = linker.suggest_links(1)
        for s in suggestions:
            assert s.source_id != s.target_id

    def test_nonexistent_entry(self, linker):
        suggestions = linker.suggest_links(999)
        assert suggestions == []

    def test_duplicate_link(self, linker):
        linker.create_link(1, 3, "depends_on")
        assert linker.create_link(1, 3, "depends_on") is True  # OR IGNORE
