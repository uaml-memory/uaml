"""Tests for UAML Ingest Pipeline."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.ingest.pipeline import IngestPipeline, IngestItem


@pytest.fixture
def pipeline(tmp_path):
    store = MemoryStore(tmp_path / "pipe.db", agent_id="test")
    p = IngestPipeline(store)
    yield p
    store.close()


class TestIngestPipeline:
    def test_basic_ingest(self, pipeline):
        result = pipeline.ingest("Valid knowledge content here", topic="test")
        assert result.success is True
        assert result.entry_id is not None

    def test_short_content_rejected(self, pipeline):
        result = pipeline.ingest("ab")
        assert result.success is False
        assert len(result.errors) > 0

    def test_empty_content_rejected(self, pipeline):
        result = pipeline.ingest("")
        assert result.success is False

    def test_custom_stage(self, pipeline):
        def require_topic(item):
            if not item.topic:
                item.rejected = True
                item.reject_reason = "Topic required"
            return item

        pipeline.add_stage("require_topic", require_topic)
        result = pipeline.ingest("Some content")
        assert result.success is False

    def test_stages_passed(self, pipeline):
        result = pipeline.ingest("Valid content here", topic="test")
        assert "length_check" in result.stages_passed

    def test_remove_stage(self, pipeline):
        assert pipeline.remove_stage("length_check") is True
        result = pipeline.ingest("ab")  # Would fail length check
        assert result.success is True

    def test_list_stages(self, pipeline):
        stages = pipeline.list_stages()
        assert "length_check" in stages

    def test_batch_ingest(self, pipeline):
        items = [
            {"content": "First valid item", "topic": "a"},
            {"content": "Second valid item", "topic": "b"},
            {"content": "x"},  # too short
        ]
        results = pipeline.ingest_batch(items)
        assert len(results) == 3
        assert results[0].success is True
        assert results[2].success is False

    def test_stage_error_handling(self, pipeline):
        def broken_stage(item):
            raise RuntimeError("Stage crashed")

        pipeline.add_stage("broken", broken_stage)
        result = pipeline.ingest("Valid content")
        assert result.success is False
        assert "broken" in result.stages_failed
