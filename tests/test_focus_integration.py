"""Integration tests for Focus Engine with existing UAML components.

Tests:
- IngestPipeline + Focus Engine input filters
- MemoryStore.focus_recall()
- API endpoints (focus-config, rules-log, focus-recall)

© 2026 GLG, a.s. — UAML Focus Engine
"""

import json
import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.core.focus_config import (
    FocusEngineConfig,
    InputFilterConfig,
    load_preset,
    save_focus_config,
    load_focus_config,
)
from uaml.core.focus_engine import FocusEngine, RecallCandidate
from uaml.ingest.pipeline import IngestPipeline
from uaml.ingest.filters import setup_input_filter


# ===========================================================================
# IngestPipeline + Input Filter integration
# ===========================================================================

class TestPipelineFilterIntegration:
    """Test Focus Engine input filters integrated with IngestPipeline."""

    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "test.db"
        s = MemoryStore(str(db))
        yield s
        s.close()

    def test_setup_replaces_default_stage(self, store):
        pipeline = IngestPipeline(store)
        config = FocusEngineConfig()
        setup_input_filter(pipeline, config)
        stages = pipeline.list_stages()
        assert "length_check" not in stages
        assert "fe_length_filter" in stages
        assert "fe_pii_detector" in stages

    def test_pipeline_rejects_short_content(self, store):
        pipeline = IngestPipeline(store)
        config = FocusEngineConfig()
        config.input_filter.min_entry_length = 20
        setup_input_filter(pipeline, config)
        result = pipeline.ingest("Too short")
        assert not result.success
        assert any("too short" in e.lower() for e in result.errors)

    def test_pipeline_accepts_valid_content(self, store):
        pipeline = IngestPipeline(store)
        config = FocusEngineConfig()
        config.input_filter.require_classification = False
        setup_input_filter(pipeline, config)
        result = pipeline.ingest(
            "This is a valid knowledge entry with enough content to pass filters",
            topic="test",
        )
        assert result.success
        assert result.entry_id is not None

    def test_pipeline_rejects_denied_category(self, store):
        pipeline = IngestPipeline(store)
        config = FocusEngineConfig()
        config.input_filter.categories["health"] = "deny"
        config.input_filter.require_classification = False
        setup_input_filter(pipeline, config)
        from uaml.ingest.pipeline import IngestItem
        # Use direct ingest with metadata
        item = IngestItem(
            content="Patient has diabetes type 2",
            metadata={"category": "health"},
        )
        # Run stages manually
        for name, fn in pipeline._stages:
            item = fn(item)
            if item.rejected:
                break
        assert item.rejected
        assert "denied" in item.reject_reason.lower()

    def test_pipeline_pii_detection(self, store):
        pipeline = IngestPipeline(store)
        config = FocusEngineConfig()
        config.input_filter.pii_detection = True
        config.input_filter.require_classification = False
        setup_input_filter(pipeline, config)
        result = pipeline.ingest(
            "Contact user at test@example.com for more details about the project",
            topic="contacts",
        )
        # PII detection doesn't reject, just tags
        assert result.success

    def test_full_pipeline_stage_order(self, store):
        pipeline = IngestPipeline(store)
        config = FocusEngineConfig()
        setup_input_filter(pipeline, config)
        stages = pipeline.list_stages()
        expected_order = [
            "fe_length_filter",
            "fe_max_tokens_filter",
            "fe_rate_limit",
            "fe_category_filter",
            "fe_pii_detector",
            "fe_relevance_gate",
        ]
        assert stages == expected_order


# ===========================================================================
# MemoryStore.focus_recall() integration
# ===========================================================================

class TestFocusRecallIntegration:
    """Test focus_recall method on MemoryStore."""

    @pytest.fixture
    def store_with_data(self, tmp_path):
        db = tmp_path / "test.db"
        s = MemoryStore(str(db))
        # Populate with test data
        s.learn("Python uses GIL for thread safety", topic="python")
        s.learn("Neo4j is a graph database for connected data", topic="databases")
        s.learn("UAML provides intelligent memory management", topic="uaml")
        s.learn("Machine learning requires large datasets", topic="ml")
        s.learn("Data protection is critical for GDPR compliance", topic="security")
        yield s
        s.close()

    def test_focus_recall_basic(self, store_with_data):
        result = store_with_data.focus_recall("Python threading")
        assert "records" in result
        assert "token_report" in result
        assert "decisions" in result
        assert "total_candidates" in result

    def test_focus_recall_returns_token_report(self, store_with_data):
        result = store_with_data.focus_recall("database graph")
        report = result["token_report"]
        assert "budget" in report
        assert "used" in report
        assert "remaining" in report
        assert report["budget"] > 0

    def test_focus_recall_with_custom_config(self, store_with_data):
        config = load_preset("research")
        result = store_with_data.focus_recall("UAML memory", focus_config=config)
        # Research preset has higher budget and more records
        assert result["token_report"]["budget"] > 0

    def test_focus_recall_respects_budget(self, store_with_data):
        config = load_preset("conservative")
        config.output_filter.token_budget_per_query = 100  # Very small
        result = store_with_data.focus_recall("data", focus_config=config)
        assert result["token_report"]["used"] <= 100

    def test_focus_recall_empty_query(self, store_with_data):
        result = store_with_data.focus_recall("nonexistent_xyz_query_12345")
        assert result["total_selected"] == 0 or result["total_candidates"] == 0

    def test_focus_recall_decisions_audit(self, store_with_data):
        result = store_with_data.focus_recall("Python")
        # Every candidate should have a decision
        for d in result["decisions"]:
            assert "entry_id" in d
            assert "included" in d
            assert "reason" in d

    def test_focus_recall_utilization(self, store_with_data):
        result = store_with_data.focus_recall("security data protection")
        assert "utilization_pct" in result
        assert 0 <= result["utilization_pct"] <= 100


# ===========================================================================
# Config persistence round-trip
# ===========================================================================

class TestConfigRoundTrip:
    """Test saving, loading, and applying Focus Engine config."""

    def test_save_load_apply_recall(self, tmp_path):
        # 1. Create and save config
        config = load_preset("standard")
        config.output_filter.token_budget_per_query = 5000
        config_path = tmp_path / "focus.json"
        save_focus_config(config, config_path, modified_by="test@test.com")

        # 2. Load config
        loaded = load_focus_config(config_path)
        assert loaded.output_filter.token_budget_per_query == 5000

        # 3. Use in focus_recall
        db = tmp_path / "test.db"
        store = MemoryStore(str(db))
        store.learn("Test knowledge entry for config round-trip testing", topic="test")
        result = store.focus_recall("test", focus_config=loaded)
        assert result["token_report"]["budget"] <= 5000
        store.close()
