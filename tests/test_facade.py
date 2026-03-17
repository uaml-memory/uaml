"""Tests for UAML Facade — integration tests for the unified API."""

from __future__ import annotations

import pytest

from uaml.facade import UAML


@pytest.fixture
def uaml(tmp_path):
    u = UAML(str(tmp_path / "facade.db"), agent_id="test")
    u.learn("Python GIL prevents true multithreading in CPython.", topic="python", confidence=0.9)
    u.learn("SQLite is a serverless embedded database engine.", topic="database", confidence=0.85)
    u.learn("Asyncio provides cooperative multitasking.", topic="python", confidence=0.8)
    yield u
    u.close()


class TestFacade:
    def test_learn_and_search(self, uaml):
        results = uaml.search("python threading")
        assert len(results) >= 1

    def test_stats(self, uaml):
        s = uaml.stats()
        assert s["knowledge"] >= 3

    def test_delete(self, uaml):
        assert uaml.delete(1) is True

    def test_context_building(self, uaml):
        ctx = uaml.context("python threading", max_tokens=1000)
        assert ctx.count >= 1
        assert len(ctx.text) > 0

    def test_score_entry(self, uaml):
        score = uaml.score(1)
        assert score is not None
        assert 0 <= score.overall <= 1

    def test_rank(self, uaml):
        ranked = uaml.rank()
        assert len(ranked) == 3
        assert ranked[0].overall >= ranked[-1].overall

    def test_overview(self, uaml):
        overview = uaml.overview()
        assert overview.total_entries == 3

    def test_topic_summary(self, uaml):
        ts = uaml.topic_summary("python")
        assert ts.entry_count == 2

    def test_validate(self, uaml):
        issues = uaml.validate(1)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_validate_all(self, uaml):
        report = uaml.validate_all()
        assert report["total_entries"] == 3

    def test_sanitize(self, uaml):
        result = uaml.sanitize("Email: test@test.com")
        assert "[EMAIL_REDACTED]" in result.cleaned

    def test_tags(self, uaml):
        uaml.add_tags(1, ["gil", "threading"])
        cloud = uaml.tag_cloud()
        tags = [c["tag"] for c in cloud]
        assert "gil" in tags

    def test_cluster(self, uaml):
        clusters = uaml.cluster(min_similarity=0.15)
        assert isinstance(clusters, list)

    def test_detect_conflicts(self, uaml):
        conflicts = uaml.detect_conflicts()
        assert isinstance(conflicts, list)

    def test_optimize_query(self, uaml):
        result = uaml.optimize_query("py db")
        assert "python" in result.expanded

    def test_snapshot_and_diff(self, uaml):
        uaml.snapshot("v1")
        uaml.learn("New entry", topic="new")
        uaml.snapshot("v2")
        diff = uaml.snapshot_diff("v1", "v2")
        assert diff.entries_added == 1

    def test_backup(self, uaml, tmp_path):
        path = uaml.backup()
        assert path.exists()

    def test_health_check(self, uaml):
        health = uaml.health_check()
        assert "status" in health

    def test_lazy_initialization(self, uaml):
        """Modules should be initialized lazily."""
        assert len(uaml._cache) == 0
        uaml.score(1)
        assert "scorer" in uaml._cache
        assert len(uaml._cache) == 1

    # ── Focus Engine facade tests ──

    def test_focus_recall(self, uaml):
        result = uaml.focus_recall("python threading")
        assert "records" in result
        assert "token_report" in result
        assert "decisions" in result
        assert result["token_report"]["budget"] > 0

    def test_focus_recall_with_preset(self, uaml):
        config = uaml.load_focus_preset("research")
        result = uaml.focus_recall("python", focus_config=config)
        assert result["token_report"]["budget"] > 0

    def test_load_focus_preset(self, uaml):
        config = uaml.load_focus_preset("conservative")
        assert config.output_filter.token_budget_per_query == 1500

    def test_load_focus_preset_standard(self, uaml):
        config = uaml.load_focus_preset("standard")
        assert config.output_filter.recall_tier == 2

    def test_focus_param_specs(self, uaml):
        specs = uaml.focus_param_specs()
        assert "input_filter" in specs
        assert "output_filter" in specs
        assert "agent_rules" in specs
        assert "token_budget_per_query" in specs["output_filter"]

    def test_save_load_focus_config(self, uaml, tmp_path):
        config = uaml.load_focus_preset("standard")
        config.output_filter.token_budget_per_query = 4242
        path = str(tmp_path / "focus.json")
        uaml.save_focus_config(config, path, modified_by="test")
        loaded = uaml.load_focus_config(path)
        assert loaded.output_filter.token_budget_per_query == 4242
