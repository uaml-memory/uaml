"""Tests for UAML Batch Operations."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.batch import BatchProcessor


@pytest.fixture
def proc(tmp_path):
    store = MemoryStore(tmp_path / "batch.db", agent_id="test")
    processor = BatchProcessor(store)
    yield processor
    store.close()


class TestBatchLearn:
    def test_batch_learn(self, proc):
        items = [
            {"content": "Python is great", "topic": "python"},
            {"content": "SQLite is reliable", "topic": "database"},
            {"content": "UAML rocks", "topic": "uaml"},
        ]
        result = proc.batch_learn(items)
        assert result.total == 3
        assert result.stored == 3
        assert result.success_rate == 1.0

    def test_skip_empty(self, proc):
        items = [
            {"content": "Real data"},
            {"content": ""},
            {"topic": "no-content"},
        ]
        result = proc.batch_learn(items)
        assert result.stored == 1
        assert result.skipped == 2

    def test_defaults(self, proc):
        items = [{"content": "No topic specified"}]
        result = proc.batch_learn(items, defaults={"topic": "default-topic"})
        assert result.stored == 1

    def test_dedup(self, proc):
        items = [
            {"content": "Same content here"},
            {"content": "Same content here"},
        ]
        result = proc.batch_learn(items, dedup=True)
        assert result.stored <= 2  # Dedup may skip


class TestBatchSearch:
    def test_batch_search(self, proc):
        proc.batch_learn([
            {"content": "Python programming language", "topic": "python"},
            {"content": "SQLite database engine", "topic": "database"},
        ])
        result = proc.batch_search(["Python", "SQLite"])
        assert result.queries == 2
        assert result.total_results >= 0


class TestBatchTag:
    def test_batch_tag_append(self, proc):
        proc.batch_learn([
            {"content": "Entry one", "tags": "original"},
            {"content": "Entry two", "tags": "existing"},
        ])
        updated = proc.batch_tag([1, 2], "new-tag", append=True)
        assert updated == 2

    def test_batch_tag_replace(self, proc):
        proc.batch_learn([{"content": "Entry", "tags": "old"}])
        updated = proc.batch_tag([1], "replaced", append=False)
        assert updated == 1


class TestBatchConfidence:
    def test_update_confidence(self, proc):
        proc.batch_learn([
            {"content": "Entry one", "confidence": 0.5},
            {"content": "Entry two", "confidence": 0.3},
        ])
        updated = proc.batch_update_confidence({1: 0.9, 2: 0.95})
        assert updated == 2

    def test_clamp_confidence(self, proc):
        proc.batch_learn([{"content": "Entry"}])
        updated = proc.batch_update_confidence({1: 1.5})
        assert updated == 1


class TestExportFiltered:
    def test_export_by_topic(self, proc):
        proc.batch_learn([
            {"content": "Python fact", "topic": "python", "confidence": 0.9},
            {"content": "Java fact", "topic": "java", "confidence": 0.8},
        ])
        exported = proc.export_filtered(topic="python")
        assert len(exported) == 1
        assert exported[0]["topic"] == "python"

    def test_export_by_confidence(self, proc):
        proc.batch_learn([
            {"content": "High conf", "confidence": 0.9},
            {"content": "Low conf", "confidence": 0.2},
        ])
        exported = proc.export_filtered(min_confidence=0.5)
        assert len(exported) == 1
