"""Tests for UAML Knowledge Templates."""

from __future__ import annotations

import pytest

from uaml.core.templates import TemplateEngine, Template


@pytest.fixture
def engine():
    return TemplateEngine()


class TestTemplateEngine:
    def test_create_decision(self, engine):
        entry = engine.create("decision", decision="Use SQLite", reason="Simplicity")
        assert "Use SQLite" in entry["content"]
        assert "Simplicity" in entry["content"]
        assert entry["topic"] == "decision"

    def test_create_fact(self, engine):
        entry = engine.create("fact", content="Python 3.12 is current")
        assert entry["content"] == "Python 3.12 is current"

    def test_create_procedure(self, engine):
        entry = engine.create("procedure", title="Deploy", steps="1. Build\n2. Test\n3. Ship")
        assert "Deploy" in entry["content"]
        assert entry["data_layer"] == "operational"

    def test_create_lesson(self, engine):
        entry = engine.create("lesson", title="DB Backup", what="Lost data", learned="Always backup")
        assert "Always backup" in entry["content"]

    def test_missing_required(self, engine):
        with pytest.raises(ValueError, match="Missing required"):
            engine.create("decision", decision="Test")

    def test_unknown_template(self, engine):
        with pytest.raises(ValueError, match="Unknown template"):
            engine.create("nonexistent", x="y")

    def test_custom_template(self, engine):
        engine.register(Template(
            name="bug",
            format_str="Bug: {title}\nSteps: {steps}",
            required_fields=["title", "steps"],
            default_topic="bug",
        ))
        entry = engine.create("bug", title="Crash", steps="1. Click\n2. Boom")
        assert "Crash" in entry["content"]

    def test_list_templates(self, engine):
        templates = engine.list_templates()
        names = [t["name"] for t in templates]
        assert "decision" in names
        assert "fact" in names
        assert "procedure" in names

    def test_validate_ok(self, engine):
        errors = engine.validate("decision", decision="X", reason="Y")
        assert errors == []

    def test_validate_missing(self, engine):
        errors = engine.validate("decision", decision="X")
        assert len(errors) == 1
        assert "reason" in errors[0]

    def test_get_template(self, engine):
        t = engine.get_template("decision")
        assert t is not None
        assert t.name == "decision"

    def test_get_nonexistent(self, engine):
        assert engine.get_template("nope") is None

    def test_optional_fields(self, engine):
        entry = engine.create("contact", name="Pavel")
        assert "Pavel" in entry["content"]
        assert entry["data_layer"] == "identity"

    def test_override_defaults(self, engine):
        entry = engine.create("fact", content="Test", _topic="custom", _confidence=0.5)
        assert entry["topic"] == "custom"
        assert entry["confidence"] == 0.5
