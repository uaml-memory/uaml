"""Tests for Focus Engine — config, input filters, output engine, rules changelog.

Covers:
- FocusEngineConfig validation and presets
- Input filter stages (length, tokens, PII, category, rate limit, relevance)
- Output filter / Focus Engine (scoring, budget, dedup, tiers)
- Rules Change Log (CRUD, audit trail)
- Certification-relevant parameter extraction

© 2026 GLG, a.s. — UAML Focus Engine
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from uaml.core.focus_config import (
    CategoryAction,
    FocusEngineConfig,
    InputFilterConfig,
    OutputFilterConfig,
    AgentRulesConfig,
    ParamSpec,
    PRESETS,
    INPUT_FILTER_SPECS,
    OUTPUT_FILTER_SPECS,
    AGENT_RULES_SPECS,
    load_focus_config,
    save_focus_config,
    load_preset,
    get_all_param_specs,
)
from uaml.core.focus_engine import (
    FocusEngine,
    RecallCandidate,
    FocusResult,
)
from uaml.core.rules_changelog import (
    RulesChangeLog,
    RuleChange,
    ImpactMeasurement,
)
from uaml.ingest.filters import (
    create_length_filter,
    create_max_tokens_filter,
    create_pii_detector,
    create_category_filter,
    create_rate_limit_filter,
    create_relevance_gate,
    detect_pii,
    PIIDetectionResult,
)
from uaml.ingest.pipeline import IngestItem


# ===========================================================================
# Focus Config Tests
# ===========================================================================

class TestParamSpec:
    """Test parameter specification validation."""

    def test_validate_float_in_range(self):
        spec = ParamSpec(name="test", type="float", default=0.5, min_val=0.0, max_val=1.0)
        assert spec.validate(0.5) == (True, "")
        assert spec.validate(0.0) == (True, "")
        assert spec.validate(1.0) == (True, "")

    def test_validate_float_out_of_range(self):
        spec = ParamSpec(name="test", type="float", default=0.5, min_val=0.0, max_val=1.0)
        valid, msg = spec.validate(1.5)
        assert not valid
        assert "maximum" in msg

    def test_validate_float_below_range(self):
        spec = ParamSpec(name="test", type="float", default=0.5, min_val=0.0, max_val=1.0)
        valid, msg = spec.validate(-0.1)
        assert not valid
        assert "minimum" in msg

    def test_validate_int(self):
        spec = ParamSpec(name="test", type="int", default=10, min_val=1, max_val=100)
        assert spec.validate(50) == (True, "")
        valid, _ = spec.validate(0)
        assert not valid

    def test_validate_bool(self):
        spec = ParamSpec(name="test", type="bool", default=True)
        assert spec.validate(True) == (True, "")
        assert spec.validate(False) == (True, "")
        valid, _ = spec.validate(1)
        assert not valid

    def test_validate_wrong_type(self):
        spec = ParamSpec(name="test", type="float", default=0.5, min_val=0.0, max_val=1.0)
        valid, msg = spec.validate("not a float")
        assert not valid


class TestFocusEngineConfig:
    """Test FocusEngineConfig creation and validation."""

    def test_default_config_is_valid(self):
        config = FocusEngineConfig()
        errors = config.validate()
        assert errors == []

    def test_invalid_relevance_score(self):
        config = FocusEngineConfig()
        config.input_filter.min_relevance_score = 1.5
        errors = config.validate()
        assert len(errors) > 0
        assert any("max" in e.lower() for e in errors)

    def test_invalid_category_action(self):
        config = FocusEngineConfig()
        config.input_filter.categories["test"] = "invalid_action"
        errors = config.validate()
        assert len(errors) > 0
        assert any("invalid action" in e for e in errors)

    def test_valid_category_actions(self):
        config = FocusEngineConfig()
        config.input_filter.categories = {
            "personal": "allow",
            "financial": "encrypt",
            "health": "deny",
            "custom": "require_consent",
        }
        errors = config.validate()
        assert errors == []

    def test_certification_params(self):
        config = FocusEngineConfig()
        cert = config.certification_params()
        assert "input_filter.pii_detection" in cert
        assert "input_filter.require_classification" in cert
        assert "output_filter.token_budget_per_query" in cert
        assert "agent_rules.never_bypass_filter" in cert
        assert "agent_rules.log_all_recalls" in cert

    def test_to_dict_roundtrip(self):
        config = FocusEngineConfig()
        d = config.to_dict()
        assert isinstance(d, dict)
        assert "input_filter" in d
        assert "output_filter" in d
        assert "agent_rules" in d


class TestPresets:
    """Test built-in presets."""

    def test_all_presets_valid(self):
        for name, preset in PRESETS.items():
            errors = preset.validate()
            assert errors == [], f"Preset '{name}' has validation errors: {errors}"

    def test_load_preset(self):
        config = load_preset("conservative")
        assert config.output_filter.token_budget_per_query == 1500
        assert config.output_filter.recall_tier == 1

    def test_load_preset_standard(self):
        config = load_preset("standard")
        assert config.output_filter.token_budget_per_query == 3000
        assert config.output_filter.recall_tier == 2

    def test_load_preset_research(self):
        config = load_preset("research")
        assert config.output_filter.token_budget_per_query == 8000
        assert config.output_filter.recall_tier == 3

    def test_load_preset_unknown(self):
        with pytest.raises(KeyError):
            load_preset("nonexistent")

    def test_preset_is_deep_copy(self):
        p1 = load_preset("conservative")
        p2 = load_preset("conservative")
        p1.output_filter.token_budget_per_query = 9999
        assert p2.output_filter.token_budget_per_query == 1500


class TestConfigPersistence:
    """Test config save/load to JSON."""

    def test_save_load_json(self):
        config = FocusEngineConfig()
        config.input_filter.min_relevance_score = 0.42

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name

        try:
            save_focus_config(config, path, modified_by="test@test.com")
            loaded = load_focus_config(path)
            assert loaded.input_filter.min_relevance_score == 0.42
            assert loaded.modified_by == "test@test.com"
            assert loaded.last_modified != ""
        finally:
            os.unlink(path)

    def test_save_invalid_config_fails(self):
        config = FocusEngineConfig()
        config.input_filter.min_relevance_score = 5.0  # invalid

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            with pytest.raises(ValueError):
                save_focus_config(config, path)
        finally:
            os.unlink(path)

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_focus_config("/nonexistent/path.json")


class TestGetAllParamSpecs:
    """Test parameter spec retrieval."""

    def test_returns_all_sections(self):
        specs = get_all_param_specs()
        assert "input_filter" in specs
        assert "output_filter" in specs
        assert "agent_rules" in specs

    def test_specs_have_descriptions(self):
        specs = get_all_param_specs()
        for section, params in specs.items():
            for name, spec in params.items():
                assert spec.description, f"{section}.{name} has no description"


# ===========================================================================
# Input Filter Tests
# ===========================================================================

class TestLengthFilter:
    """Test min-length filter stage."""

    def test_accept_valid_length(self):
        config = InputFilterConfig(min_entry_length=10)
        f = create_length_filter(config)
        item = IngestItem(content="This is a valid length content for testing")
        result = f(item)
        assert not result.rejected

    def test_reject_too_short(self):
        config = InputFilterConfig(min_entry_length=10)
        f = create_length_filter(config)
        item = IngestItem(content="Short")
        result = f(item)
        assert result.rejected
        assert "too short" in result.reject_reason.lower()


class TestMaxTokensFilter:
    """Test max-tokens filter stage."""

    def test_accept_within_limit(self):
        config = InputFilterConfig(max_entry_tokens=100)
        f = create_max_tokens_filter(config)
        item = IngestItem(content="Short content")
        result = f(item)
        assert not result.rejected

    def test_reject_over_limit(self):
        config = InputFilterConfig(max_entry_tokens=10)
        f = create_max_tokens_filter(config)
        item = IngestItem(content="x" * 200)  # ~50 tokens
        result = f(item)
        assert result.rejected
        assert "too large" in result.reject_reason.lower()


class TestPIIDetector:
    """Test PII detection stage."""

    def test_detect_email(self):
        result = detect_pii("Contact me at test@example.com")
        assert result.has_pii
        assert "email" in result.detected_types

    def test_detect_phone(self):
        result = detect_pii("Call +420 123 456 789")
        assert result.has_pii

    def test_detect_czech_birth_number(self):
        result = detect_pii("Rodné číslo: 900101/1234")
        assert result.has_pii
        assert "czech_birth_number" in result.detected_types

    def test_no_pii(self):
        result = detect_pii("This is a clean text about programming")
        assert not result.has_pii

    def test_pii_stage_tags_metadata(self):
        config = InputFilterConfig(pii_detection=True)
        f = create_pii_detector(config)
        item = IngestItem(content="Email: test@example.com", metadata={})
        result = f(item)
        assert not result.rejected  # PII detection doesn't reject, only tags
        assert result.metadata.get("pii_detected") is True

    def test_pii_disabled(self):
        config = InputFilterConfig(pii_detection=False)
        f = create_pii_detector(config)
        item = IngestItem(content="Email: test@example.com", metadata={})
        result = f(item)
        assert "pii_detected" not in result.metadata


class TestCategoryFilter:
    """Test category enforcement stage."""

    def test_allow_permitted_category(self):
        config = InputFilterConfig(categories={"public": "allow"})
        f = create_category_filter(config)
        item = IngestItem(content="test", metadata={"category": "public"})
        result = f(item)
        assert not result.rejected

    def test_deny_forbidden_category(self):
        config = InputFilterConfig(categories={"health": "deny"})
        f = create_category_filter(config)
        item = IngestItem(content="test", metadata={"category": "health"})
        result = f(item)
        assert result.rejected
        assert "denied" in result.reject_reason.lower()

    def test_encrypt_marks_metadata(self):
        config = InputFilterConfig(categories={"financial": "encrypt"})
        f = create_category_filter(config)
        item = IngestItem(content="test", metadata={"category": "financial"})
        result = f(item)
        assert not result.rejected
        assert result.metadata.get("requires_encryption") is True

    def test_require_consent_without_consent(self):
        config = InputFilterConfig(categories={"personal": "require_consent"})
        f = create_category_filter(config)
        item = IngestItem(content="test", metadata={"category": "personal"})
        result = f(item)
        assert result.rejected
        assert "consent" in result.reject_reason.lower()

    def test_require_consent_with_consent(self):
        config = InputFilterConfig(categories={"personal": "require_consent"})
        f = create_category_filter(config)
        item = IngestItem(
            content="test",
            metadata={"category": "personal", "consent_given": True},
        )
        result = f(item)
        assert not result.rejected

    def test_missing_category_with_require(self):
        config = InputFilterConfig(require_classification=True)
        f = create_category_filter(config)
        item = IngestItem(content="test", metadata={})
        result = f(item)
        assert result.rejected
        assert "classification" in result.reject_reason.lower()


class TestRelevanceGate:
    """Test relevance score gate."""

    def test_accept_above_threshold(self):
        config = InputFilterConfig(min_relevance_score=0.5)
        f = create_relevance_gate(config)
        item = IngestItem(content="test", metadata={"relevance_score": 0.8})
        result = f(item)
        assert not result.rejected

    def test_reject_below_threshold(self):
        config = InputFilterConfig(min_relevance_score=0.5)
        f = create_relevance_gate(config)
        item = IngestItem(content="test", metadata={"relevance_score": 0.3})
        result = f(item)
        assert result.rejected
        assert "relevance" in result.reject_reason.lower()

    def test_no_score_passes(self):
        config = InputFilterConfig(min_relevance_score=0.5)
        f = create_relevance_gate(config)
        item = IngestItem(content="test", metadata={})
        result = f(item)
        assert not result.rejected  # No score = not evaluated


# ===========================================================================
# Focus Engine (Output Filter) Tests
# ===========================================================================

class TestFocusEngine:
    """Test Focus Engine output filtering."""

    def _make_candidate(
        self, entry_id=1, content="test content", relevance=0.8,
        sensitivity=1, created_at=None, summary=None,
    ) -> RecallCandidate:
        return RecallCandidate(
            entry_id=entry_id,
            content=content,
            summary=summary,
            relevance_score=relevance,
            created_at=created_at or "2026-03-14T12:00:00+00:00",
            sensitivity=sensitivity,
        )

    def test_empty_candidates(self):
        config = FocusEngineConfig()
        engine = FocusEngine(config)
        result = engine.process([])
        assert result.total_selected == 0
        assert result.total_candidates == 0

    def test_basic_selection(self):
        config = FocusEngineConfig()
        engine = FocusEngine(config)
        candidates = [self._make_candidate(i, f"Content {i}", 0.5 + i * 0.1) for i in range(3)]
        result = engine.process(candidates)
        assert result.total_selected == 3
        assert result.total_tokens_used > 0

    def test_relevance_filtering(self):
        config = FocusEngineConfig()
        config.output_filter.min_relevance_score = 0.5
        engine = FocusEngine(config)
        candidates = [
            self._make_candidate(1, "High relevance", 0.9),
            self._make_candidate(2, "Low relevance", 0.2),
        ]
        result = engine.process(candidates)
        assert result.total_selected == 1
        assert result.total_rejected >= 1

    def test_sensitivity_filtering(self):
        config = FocusEngineConfig()
        config.output_filter.sensitivity_threshold = 3
        engine = FocusEngine(config)
        candidates = [
            self._make_candidate(1, "Normal", sensitivity=2),
            self._make_candidate(2, "Sensitive", sensitivity=5),
        ]
        result = engine.process(candidates)
        assert result.total_selected == 1
        # Check the sensitive record was rejected
        rejected = [d for d in result.decisions if not d.included]
        assert any("sensitivity" in d.reason.lower() for d in rejected)

    def test_token_budget_enforcement(self):
        config = FocusEngineConfig()
        config.output_filter.token_budget_per_query = 50  # Very small budget
        engine = FocusEngine(config)
        candidates = [
            self._make_candidate(i, f"Content {'x' * 200} item {i}", 0.9)
            for i in range(5)
        ]
        result = engine.process(candidates)
        assert result.total_selected < 5
        assert result.total_tokens_used <= 50

    def test_max_records_limit(self):
        config = FocusEngineConfig()
        config.output_filter.max_records = 3
        engine = FocusEngine(config)
        candidates = [self._make_candidate(i, f"Content {i}", 0.9) for i in range(10)]
        result = engine.process(candidates)
        assert result.total_selected <= 3

    def test_context_percentage_limit(self):
        config = FocusEngineConfig()
        config.output_filter.token_budget_per_query = 100000
        config.output_filter.max_context_percentage = 10
        engine = FocusEngine(config)
        # With 128K context window, 10% = 12800 tokens
        candidates = [self._make_candidate(i, f"Content {i}", 0.9) for i in range(5)]
        result = engine.process(candidates, model_context_window=128000)
        # Budget should be capped at 12800, not 100000
        total_budget = result.total_tokens_used + result.budget_remaining
        assert total_budget <= 12800

    def test_token_usage_report(self):
        config = FocusEngineConfig()
        engine = FocusEngine(config)
        candidates = [self._make_candidate(1, "Test content", 0.9)]
        result = engine.process(candidates)
        report = engine.get_token_usage_report(result)
        assert report.budget > 0
        assert report.used >= 0
        assert report.estimated_cost_usd >= 0

    def test_tier_1_prefers_summary(self):
        config = FocusEngineConfig()
        config.output_filter.recall_tier = 1
        engine = FocusEngine(config)
        candidates = [self._make_candidate(
            1, "Very long raw content " * 100,
            relevance=0.9, summary="Short summary",
        )]
        result = engine.process(candidates)
        assert result.total_selected == 1

    def test_utilization_percentage(self):
        result = FocusResult(
            total_tokens_used=500,
            budget_remaining=1500,
        )
        assert abs(result.utilization_pct - 25.0) < 0.01


# ===========================================================================
# Rules Change Log Tests
# ===========================================================================

class TestRulesChangeLog:
    """Test Rules Change Log audit trail."""

    @pytest.fixture
    def changelog(self, tmp_path):
        db_path = tmp_path / "test_changelog.db"
        log = RulesChangeLog(db_path)
        yield log
        log.close()

    def test_log_change(self, changelog):
        change = RuleChange(
            user="test@test.com",
            rule_path="output_filter.token_budget_per_query",
            old_value=2000,
            new_value=4000,
            reason="Need more context",
            expected_impact={"tokens": "+100%", "quality": "+20%"},
        )
        change_id = changelog.log_change(change)
        assert change_id.startswith("RC-")

    def test_get_change(self, changelog):
        change = RuleChange(
            user="test@test.com",
            rule_path="output_filter.token_budget_per_query",
            old_value=2000,
            new_value=4000,
            reason="Need more context",
        )
        change_id = changelog.log_change(change)
        retrieved = changelog.get_change(change_id)
        assert retrieved is not None
        assert retrieved.old_value == 2000
        assert retrieved.new_value == 4000
        assert retrieved.user == "test@test.com"

    def test_get_history(self, changelog):
        for i in range(5):
            changelog.log_change(RuleChange(
                user="test@test.com",
                rule_path=f"param_{i}",
                old_value=i,
                new_value=i + 10,
            ))
        history = changelog.get_history(limit=3)
        assert len(history) == 3

    def test_filter_by_rule_path(self, changelog):
        changelog.log_change(RuleChange(
            user="test@test.com", rule_path="input_filter.pii_detection",
            old_value=True, new_value=False,
        ))
        changelog.log_change(RuleChange(
            user="test@test.com", rule_path="output_filter.token_budget",
            old_value=2000, new_value=3000,
        ))
        history = changelog.get_history(rule_path="input_filter.pii_detection")
        assert len(history) == 1

    def test_record_actual_impact(self, changelog):
        change = RuleChange(
            user="test@test.com",
            rule_path="output_filter.token_budget",
            old_value=2000, new_value=4000,
        )
        change_id = changelog.log_change(change)

        impact = ImpactMeasurement(
            measurement_period_start="2026-03-14",
            measurement_period_end="2026-03-21",
            avg_tokens_before=1850,
            avg_tokens_after=3200,
            quality_score_before=0.72,
            quality_score_after=0.81,
            cost_change="+€0.65/day",
            verdict="Quality +12.5%",
            recommendation="Consider reducing to 3000",
        )
        changelog.record_actual_impact(change_id, impact)

        retrieved = changelog.get_change(change_id)
        assert retrieved.evaluation_status == "evaluated"
        assert retrieved.actual_impact is not None
        assert retrieved.actual_impact["verdict"] == "Quality +12.5%"

    def test_get_stats(self, changelog):
        changelog.log_change(RuleChange(
            user="test@test.com", rule_path="test_param",
            old_value=1, new_value=2,
        ))
        stats = changelog.get_stats()
        assert stats["total_changes"] == 1
        assert stats["pending_evaluation"] == 1

    def test_export_json(self, changelog):
        changelog.log_change(RuleChange(
            user="test@test.com", rule_path="test_param",
            old_value=1, new_value=2,
        ))
        export = changelog.export_json()
        data = json.loads(export)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_get_nonexistent_change(self, changelog):
        result = changelog.get_change("nonexistent-id")
        assert result is None


# ===========================================================================
# Integration test
# ===========================================================================

class TestIntegration:
    """Integration tests combining config + filters + engine."""

    def test_conservative_preset_with_engine(self):
        config = load_preset("conservative")
        engine = FocusEngine(config)

        candidates = [
            RecallCandidate(
                entry_id=1, content="Important fact",
                relevance_score=0.8, sensitivity=2,
                created_at="2026-03-14T12:00:00+00:00",
            ),
            RecallCandidate(
                entry_id=2, content="Low relevance noise",
                relevance_score=0.1, sensitivity=1,
                created_at="2026-03-14T12:00:00+00:00",
            ),
            RecallCandidate(
                entry_id=3, content="Highly sensitive data",
                relevance_score=0.9, sensitivity=5,
                created_at="2026-03-14T12:00:00+00:00",
            ),
        ]

        result = engine.process(candidates)
        # Conservative: high sensitivity threshold = 3, min relevance = 0.5
        # Entry 1: relevance 0.8, sensitivity 2 → INCLUDE
        # Entry 2: relevance 0.1 < 0.5 → REJECT
        # Entry 3: sensitivity 5 > 3 → REJECT
        assert result.total_selected == 1
        assert result.records[0].entry_id == 1

    def test_full_pipeline_with_changelog(self, tmp_path):
        """Test complete flow: config → filter → engine → log."""
        # 1. Load config
        config = load_preset("standard")

        # 2. Log a config change
        log = RulesChangeLog(tmp_path / "changelog.db")
        change_id = log.log_change(RuleChange(
            user="test@test.com",
            rule_path="output_filter.token_budget_per_query",
            old_value=3000,
            new_value=5000,
            reason="Integration test",
        ))

        # 3. Apply change
        config.output_filter.token_budget_per_query = 5000

        # 4. Run Focus Engine
        engine = FocusEngine(config)
        candidates = [
            RecallCandidate(
                entry_id=i, content=f"Record {i} content",
                relevance_score=0.5 + i * 0.05, sensitivity=1,
                created_at="2026-03-14T12:00:00+00:00",
            )
            for i in range(5)
        ]
        result = engine.process(candidates)

        # 5. Verify
        assert result.total_selected >= 1
        assert log.get_change(change_id) is not None

        report = engine.get_token_usage_report(result)
        assert report.budget == 5000 or report.budget <= 5000

        log.close()


class TestSavedConfigStore:
    """Tests for named configuration save/load/delete."""

    @pytest.fixture
    def store(self, tmp_path):
        from uaml.core.focus_config import SavedConfigStore
        s = SavedConfigStore(tmp_path / "configs.db")
        yield s
        s.close()

    @pytest.fixture
    def config(self):
        from uaml.core.focus_config import load_preset
        return load_preset("conservative")

    def test_save_and_load(self, store, config):
        result = store.save("test-config", config, description="Test config")
        assert result["name"] == "test-config"

        loaded = store.load("test-config")
        assert loaded.output_filter.token_budget_per_query == config.output_filter.token_budget_per_query

    def test_list_configs(self, store, config):
        store.save("config-1", config, description="First")
        store.save("config-2", config, description="Second")

        configs = store.list()
        assert len(configs) == 2
        names = [c["name"] for c in configs]
        assert "config-1" in names
        assert "config-2" in names

    def test_delete_config(self, store, config):
        store.save("to-delete", config)
        assert store.delete("to-delete") is True
        assert store.delete("nonexistent") is False

        with pytest.raises(KeyError):
            store.load("to-delete")

    def test_set_active(self, store, config):
        store.save("cfg-a", config)
        store.save("cfg-b", config)
        store.set_active("cfg-a")

        assert store.get_active_name() == "cfg-a"
        active = store.get_active()
        assert active is not None

    def test_set_active_deactivates_others(self, store, config):
        store.save("cfg-a", config)
        store.save("cfg-b", config)
        store.set_active("cfg-a")
        store.set_active("cfg-b")

        assert store.get_active_name() == "cfg-b"

    def test_load_nonexistent_raises(self, store):
        with pytest.raises(KeyError):
            store.load("does-not-exist")

    def test_set_active_nonexistent_raises(self, store):
        with pytest.raises(KeyError):
            store.set_active("does-not-exist")

    def test_save_with_set_active(self, store, config):
        store.save("active-one", config, set_active=True)
        assert store.get_active_name() == "active-one"

    def test_update_existing(self, store, config):
        store.save("updatable", config, description="v1")
        from uaml.core.focus_config import load_preset
        config2 = load_preset("research")
        store.save("updatable", config2, description="v2")

        loaded = store.load("updatable")
        assert loaded.output_filter.token_budget_per_query == 8000

        configs = store.list()
        assert len(configs) == 1
        assert configs[0]["description"] == "v2"

    def test_no_active_returns_none(self, store):
        assert store.get_active() is None
        assert store.get_active_name() is None

    def test_filter_type_separation(self, store, config):
        """Input and output configs are separate."""
        store.save("shared-name", config, filter_type="input", description="Input version")
        store.save("shared-name", config, filter_type="output", description="Output version")

        input_configs = store.list(filter_type="input")
        output_configs = store.list(filter_type="output")
        all_configs = store.list()

        assert len(input_configs) == 1
        assert len(output_configs) == 1
        assert len(all_configs) == 2
        assert input_configs[0]["description"] == "Input version"
        assert output_configs[0]["description"] == "Output version"

    def test_active_per_filter_type(self, store, config):
        """Active config is tracked per filter_type."""
        store.save("cfg-in", config, filter_type="input")
        store.save("cfg-out", config, filter_type="output")
        store.set_active("cfg-in", filter_type="input")
        store.set_active("cfg-out", filter_type="output")

        assert store.get_active_name(filter_type="input") == "cfg-in"
        assert store.get_active_name(filter_type="output") == "cfg-out"
