"""Tests for UAML Query Optimizer."""

from __future__ import annotations

import pytest

from uaml.reasoning.optimizer import QueryOptimizer


@pytest.fixture
def opt():
    return QueryOptimizer()


class TestQueryOptimizer:
    def test_expand_abbreviation(self, opt):
        result = opt.optimize("py threading")
        assert "python" in result.expanded

    def test_normalize(self, opt):
        result = opt.optimize("  Py  Threading  ")
        assert result.normalized == "py threading"

    def test_suggestions(self, opt):
        result = opt.optimize("find error")
        assert len(result.suggestions) > 0

    def test_no_change(self, opt):
        result = opt.optimize("python")
        assert result.expanded == "python"

    def test_empty_query(self, opt):
        result = opt.optimize("")
        assert result.expanded == ""

    def test_custom_expansion(self, opt):
        opt.add_expansion("uaml", "universal agent memory layer")
        result = opt.optimize("uaml search")
        assert "universal agent memory layer" in result.expanded

    def test_analyze(self, opt):
        analysis = opt.analyze('find "exact phrase" py')
        assert analysis["word_count"] == 4
        assert analysis["has_quotes"] is True
        assert "py" in analysis["abbreviations"]

    def test_transformations_recorded(self, opt):
        result = opt.optimize("py db")
        assert len(result.transformations) > 0

    def test_expanded_query_property(self, opt):
        result = opt.optimize("js async")
        assert result.expanded_query == result.expanded
