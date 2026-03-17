"""Tests for UAML Auto-Tagger."""

from __future__ import annotations

import pytest

from uaml.reasoning.tagger import AutoTagger


@pytest.fixture
def tagger():
    return AutoTagger()


class TestAutoTagger:
    def test_topic_detection(self, tagger):
        suggestions = tagger.suggest("Python dataclass with typing and asyncio features")
        tags = [s.tag for s in suggestions]
        assert "python" in tags

    def test_security_topic(self, tagger):
        suggestions = tagger.suggest("Configure firewall and SSL certificate authentication")
        tags = [s.tag for s in suggestions]
        assert "security" in tags

    def test_multiple_topics(self, tagger):
        suggestions = tagger.suggest("Deploy Python Flask app with Docker on Kubernetes")
        tags = [s.tag for s in suggestions]
        assert len(tags) >= 2

    def test_frequency_extraction(self, tagger):
        suggestions = tagger.suggest("The database query optimized the database index for database performance")
        tags = [s.tag for s in suggestions]
        assert "database" in tags

    def test_version_pattern(self, tagger):
        suggestions = tagger.suggest("Updated to v3.12.1 with new features")
        tags = [s.tag for s in suggestions]
        assert "version" in tags

    def test_url_pattern(self, tagger):
        suggestions = tagger.suggest("See documentation at https://docs.uaml.ai for details")
        tags = [s.tag for s in suggestions]
        assert "reference" in tags

    def test_bugfix_pattern(self, tagger):
        suggestions = tagger.suggest("Fixed critical error in authentication module")
        tags = [s.tag for s in suggestions]
        assert "bugfix" in tags

    def test_max_tags(self, tagger):
        suggestions = tagger.suggest("Big content " * 100, max_tags=3)
        assert len(suggestions) <= 3

    def test_suggest_tags_str(self, tagger):
        result = tagger.suggest_tags_str("Python pytest testing with fixtures")
        assert isinstance(result, str)
        assert "," in result or len(result) > 0

    def test_auto_tag_entry(self, tagger):
        result = tagger.auto_tag_entry(
            "Python dataclass with typing features",
            existing_tags="manual,important",
        )
        assert "manual" in result
        assert "important" in result
        assert len(result.split(",")) >= 3

    def test_custom_topics(self):
        tagger = AutoTagger(custom_topics={
            "finance": ["bitcoin", "trading", "wallet", "blockchain"],
        })
        suggestions = tagger.suggest("Bitcoin wallet trading on blockchain network")
        tags = [s.tag for s in suggestions]
        assert "finance" in tags

    def test_empty_content(self, tagger):
        suggestions = tagger.suggest("")
        assert isinstance(suggestions, list)
