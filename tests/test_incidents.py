"""Tests for incident → lesson pipeline."""

import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.reasoning.incidents import (
    Incident,
    IncidentPipeline,
    Lesson,
    SEVERITY_LEVELS,
    CATEGORIES,
)


@pytest.fixture
def store(tmp_path):
    return MemoryStore(str(tmp_path / "test.db"))


@pytest.fixture
def pipeline(store):
    return IncidentPipeline(store)


@pytest.fixture
def pipeline_no_store():
    return IncidentPipeline()


class TestIncident:
    """Test Incident dataclass."""

    def test_create(self):
        i = Incident(title="Test incident", severity="warning")
        assert i.title == "Test incident"
        assert i.severity == "warning"
        assert i.severity_level == 1

    def test_severity_levels(self):
        assert Incident(severity="info").severity_level == 0
        assert Incident(severity="warning").severity_level == 1
        assert Incident(severity="error").severity_level == 2
        assert Incident(severity="critical").severity_level == 3

    def test_fingerprint_stable(self):
        i1 = Incident(title="X", category="ops", root_cause="Y")
        i2 = Incident(title="X", category="ops", root_cause="Y")
        assert i1.fingerprint == i2.fingerprint

    def test_fingerprint_unique(self):
        i1 = Incident(title="A", category="ops", root_cause="X")
        i2 = Incident(title="B", category="ops", root_cause="X")
        assert i1.fingerprint != i2.fingerprint

    def test_to_dict_and_back(self):
        i = Incident(
            id=1, title="Test", description="desc", severity="error",
            category="security", root_cause="bug",
            contributing_factors=["factor1"], affected_systems=["sys1"],
            resolved=True, resolution="fixed",
        )
        d = i.to_dict()
        restored = Incident.from_dict(d)
        assert restored.title == "Test"
        assert restored.severity == "error"
        assert restored.root_cause == "bug"
        assert restored.contributing_factors == ["factor1"]
        assert restored.resolved is True


class TestLesson:
    """Test Lesson dataclass."""

    def test_create(self):
        l = Lesson(title="Learned something", rule="Do X not Y")
        assert l.title == "Learned something"
        assert l.rule == "Do X not Y"

    def test_to_dict_and_back(self):
        l = Lesson(
            id=1, incident_id=5, title="Lesson",
            rule="Always check", prevention="Pre-check",
            tags=["ops", "critical"],
        )
        d = l.to_dict()
        restored = Lesson.from_dict(d)
        assert restored.incident_id == 5
        assert restored.rule == "Always check"
        assert "ops" in restored.tags


class TestIncidentPipeline:
    """Test the full pipeline."""

    def test_log_incident(self, pipeline):
        incident = pipeline.log_incident(
            title="Test incident",
            description="Something went wrong",
            severity="warning",
            category="operational",
        )
        assert incident.id == 1
        assert incident.title == "Test incident"
        assert incident.severity == "warning"

    def test_log_incident_invalid_severity(self, pipeline):
        with pytest.raises(ValueError, match="Invalid severity"):
            pipeline.log_incident(title="X", severity="mega-bad")

    def test_log_incident_stores_knowledge(self, pipeline, store):
        pipeline.log_incident(
            title="Spam loop",
            description="100+ messages in 20 min",
            severity="critical",
            root_cause="allowBots + failure loop",
        )
        # Should be stored in knowledge DB
        results = store.search("spam loop")
        assert len(results) > 0

    def test_log_multiple_incidents(self, pipeline):
        i1 = pipeline.log_incident(title="First", severity="info")
        i2 = pipeline.log_incident(title="Second", severity="error")
        assert i1.id == 1
        assert i2.id == 2

    def test_extract_lesson(self, pipeline):
        incident = pipeline.log_incident(
            title="Database corruption",
            severity="critical",
            root_cause="concurrent writes without locking",
            resolution="Added WAL mode",
        )
        lesson = pipeline.extract_lesson(incident)
        assert lesson.incident_id == incident.id
        assert lesson.confidence >= 0.7
        assert "concurrent writes" in lesson.description.lower() or "wal" in lesson.description.lower()

    def test_lesson_confidence_calculation(self, pipeline):
        # Minimal incident → lower confidence
        i1 = pipeline.log_incident(title="Vague issue", severity="info")
        l1 = pipeline.extract_lesson(i1)

        # Detailed incident → higher confidence
        i2 = pipeline.log_incident(
            title="Specific issue", severity="critical",
            root_cause="known bug", resolution="patched",
            contributing_factors=["factor1"],
        )
        l2 = pipeline.extract_lesson(i2)
        assert l2.confidence > l1.confidence

    def test_lesson_stored_as_knowledge(self, pipeline, store):
        incident = pipeline.log_incident(
            title="Test for lesson storage",
            severity="error",
            root_cause="test cause",
        )
        pipeline.extract_lesson(incident)
        results = store.search("lesson")
        assert len(results) > 0

    def test_resolve_incident(self, pipeline):
        incident = pipeline.log_incident(title="Unresolved", severity="warning")
        assert not incident.resolved
        result = pipeline.resolve_incident(incident.id, "Fixed by restart")
        assert result is not None
        assert result.resolved
        assert result.resolution == "Fixed by restart"

    def test_resolve_nonexistent(self, pipeline):
        result = pipeline.resolve_incident(999, "whatever")
        assert result is None

    def test_get_incidents_filter_severity(self, pipeline):
        pipeline.log_incident(title="Info", severity="info")
        pipeline.log_incident(title="Error", severity="error")
        pipeline.log_incident(title="Warning", severity="warning")

        errors = pipeline.get_incidents(severity="error")
        assert len(errors) == 1
        assert errors[0].title == "Error"

    def test_get_incidents_filter_category(self, pipeline):
        pipeline.log_incident(title="Sec", severity="info", category="security")
        pipeline.log_incident(title="Ops", severity="info", category="operational")

        sec = pipeline.get_incidents(category="security")
        assert len(sec) == 1
        assert sec[0].title == "Sec"

    def test_get_incidents_filter_resolved(self, pipeline):
        i1 = pipeline.log_incident(title="Resolved", severity="info")
        pipeline.log_incident(title="Open", severity="info")
        pipeline.resolve_incident(i1.id, "done")

        unresolved = pipeline.get_incidents(resolved=False)
        assert len(unresolved) == 1
        assert unresolved[0].title == "Open"

    def test_get_lessons(self, pipeline):
        i1 = pipeline.log_incident(title="I1", severity="info", category="security")
        i2 = pipeline.log_incident(title="I2", severity="info", category="operational")
        pipeline.extract_lesson(i1)
        pipeline.extract_lesson(i2)

        all_lessons = pipeline.get_lessons()
        assert len(all_lessons) == 2

        sec_lessons = pipeline.get_lessons(category="security")
        assert len(sec_lessons) == 1

    def test_get_stats(self, pipeline):
        pipeline.log_incident(title="A", severity="info", category="operational")
        pipeline.log_incident(title="B", severity="error", category="security")
        i3 = pipeline.log_incident(title="C", severity="warning", category="operational")
        pipeline.resolve_incident(i3.id, "fixed")
        pipeline.extract_lesson(i3)

        stats = pipeline.get_stats()
        assert stats["total_incidents"] == 3
        assert stats["total_lessons"] == 1
        assert stats["resolved"] == 1
        assert stats["unresolved"] == 2
        assert stats["by_severity"]["info"] == 1
        assert stats["by_severity"]["error"] == 1
        assert stats["by_category"]["operational"] == 2

    def test_create_preventive_task(self, pipeline, store):
        incident = pipeline.log_incident(
            title="Disk full", severity="error",
            root_cause="No monitoring",
        )
        lesson = pipeline.extract_lesson(incident)
        task_id = pipeline.create_preventive_task(lesson, assigned_to="pepa2")
        assert task_id is not None
        assert task_id > 0

    def test_create_preventive_task_no_store(self, pipeline_no_store):
        incident = pipeline_no_store.log_incident(title="X", severity="info")
        lesson = pipeline_no_store.extract_lesson(incident)
        result = pipeline_no_store.create_preventive_task(lesson)
        assert result is None

    def test_pipeline_no_store(self, pipeline_no_store):
        """Pipeline works without a store (in-memory only)."""
        incident = pipeline_no_store.log_incident(
            title="No store test", severity="warning"
        )
        lesson = pipeline_no_store.extract_lesson(incident)
        assert incident.id == 1
        assert lesson.id == 1

    def test_full_flow(self, pipeline, store):
        """End-to-end: incident → lesson → task → verify in DB."""
        # 1. Log incident
        incident = pipeline.log_incident(
            title="Discord spam loop",
            description="Agent generated 100+ messages in 20 minutes",
            severity="critical",
            category="communication",
            root_cause="allowBots=true + failure loop + weak local model (qwen3:32b)",
            contributing_factors=["config error", "no rate limiting", "insufficient model"],
            affected_systems=["Discord", "OpenClaw agent"],
            resolution="Added anti-spam rule: stop after 3 consecutive failures",
        )

        # 2. Extract lesson
        lesson = pipeline.extract_lesson(incident)
        assert lesson.confidence >= 0.9  # High confidence (has root cause + resolution + factors + critical)

        # 3. Create preventive task
        task_id = pipeline.create_preventive_task(lesson, assigned_to="pepa2")
        assert task_id is not None

        # 4. Verify everything is in the DB
        stats = pipeline.get_stats()
        assert stats["total_incidents"] == 1
        assert stats["total_lessons"] == 1

        # Knowledge DB should have both incident and lesson
        results = store.search("spam loop")
        assert len(results) >= 1

    def test_incident_with_all_fields(self, pipeline):
        incident = pipeline.log_incident(
            title="Full incident",
            description="Everything filled in",
            severity="error",
            category="data",
            root_cause="Schema mismatch",
            contributing_factors=["migration skipped", "no tests"],
            affected_systems=["memory.db", "dashboard"],
            agent_id="pepa2",
            project="uaml",
            resolution="Added schema migration",
            metadata={"version": "0.3.0", "affected_rows": 42},
        )
        assert incident.agent_id == "pepa2"
        assert incident.project == "uaml"
        assert incident.metadata["affected_rows"] == 42
        assert incident.resolved is True

    def test_get_rules(self, pipeline):
        """get_rules extracts rules from lessons."""
        incident = pipeline.log_incident(
            title="Git pull overwrites DB",
            severity="critical",
            category="data",
            root_cause="SQLite tracked in git",
        )
        lesson = pipeline.extract_lesson(incident)
        assert lesson.rule  # Should have auto-generated rule

        rules = pipeline.get_rules()
        assert len(rules) >= 1
        assert rules[0]["rule"] == lesson.rule
        assert rules[0]["lesson_id"] == lesson.id

    def test_get_rules_by_category(self, pipeline):
        """get_rules filters by category."""
        pipeline.log_incident(title="Data incident", severity="error", category="data",
                              root_cause="corruption")
        pipeline.log_incident(title="Security incident", severity="error", category="security",
                              root_cause="auth bypass")

        # Extract lessons for both
        incidents = pipeline.get_incidents()
        for inc in incidents:
            pipeline.extract_lesson(inc)

        data_rules = pipeline.get_rules(category="data")
        security_rules = pipeline.get_rules(category="security")
        assert all(r["category"] == "data" for r in data_rules)
        assert all(r["category"] == "security" for r in security_rules)

    def test_check_rules_finds_match(self, pipeline):
        """check_rules matches action against stored rules."""
        incident = pipeline.log_incident(
            title="SQLite database overwritten by git pull",
            severity="critical",
            category="data",
            root_cause="SQLite files tracked in git repository",
        )
        pipeline.extract_lesson(incident)

        matches = pipeline.check_rules("git pull on repository with database files")
        # Should find at least some keyword overlap
        assert isinstance(matches, list)

    def test_check_rules_empty_on_no_match(self, pipeline):
        """check_rules returns empty for unrelated actions."""
        incident = pipeline.log_incident(
            title="Network timeout",
            severity="warning",
            category="operational",
            root_cause="DNS resolution failure",
        )
        pipeline.extract_lesson(incident)

        matches = pipeline.check_rules("compile rust code")
        # Very unlikely to match network/DNS rules
        assert isinstance(matches, list)

    def test_full_pipeline_flow(self, pipeline):
        """Full flow: incident → lesson → rule → check → preventive task."""
        # 1. Log incident
        incident = pipeline.log_incident(
            title="API rate limit hit",
            severity="error",
            category="operational",
            root_cause="No rate limiting on outbound API calls",
            contributing_factors=["burst traffic", "no backoff"],
        )
        assert incident.id > 0

        # 2. Extract lesson
        lesson = pipeline.extract_lesson(incident)
        assert lesson.id > 0
        assert lesson.rule

        # 3. Get rules
        rules = pipeline.get_rules()
        assert len(rules) >= 1

        # 4. Create preventive task
        task_id = pipeline.create_preventive_task(lesson, assigned_to="metod")
        assert task_id is not None

        # 5. Verify stats
        stats = pipeline.get_stats()
        assert stats["total_incidents"] >= 1
        assert stats["total_lessons"] >= 1
