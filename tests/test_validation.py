"""Tests for UAML Knowledge Validation."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.validation import KnowledgeValidator


@pytest.fixture
def validator(tmp_path):
    store = MemoryStore(tmp_path / "val.db", agent_id="test")
    store.learn("Valid knowledge entry with enough content", topic="test", confidence=0.8)
    store.learn("Short", topic="", confidence=0.5)  # Short + no topic
    v = KnowledgeValidator(store)
    yield v
    store.close()


class TestKnowledgeValidator:
    def test_valid_entry(self, validator):
        issues = validator.validate_entry(1)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_short_content_warning(self, validator):
        issues = validator.validate_entry(2)
        warnings = [i for i in issues if i.severity == "warning" and "short" in i.message]
        assert len(warnings) >= 1

    def test_missing_topic_warning(self, validator):
        issues = validator.validate_entry(2)
        warnings = [i for i in issues if "topic" in i.message.lower()]
        assert len(warnings) >= 1

    def test_nonexistent_entry(self, validator):
        issues = validator.validate_entry(999)
        assert len(issues) == 1
        assert issues[0].severity == "error"

    def test_full_validation(self, validator):
        report = validator.full_validation()
        assert report["total_entries"] == 2
        assert report["total_issues"] >= 1
        assert "pass_rate" in report

    def test_validate_batch(self, validator):
        result = validator.validate_batch([1, 2])
        assert 1 in result
        assert 2 in result

    def test_top_issues(self, validator):
        report = validator.full_validation()
        assert isinstance(report["top_issues"], list)
