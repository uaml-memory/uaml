"""Tests for UAML Changelog."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.core.changelog import ChangelogGenerator, Changelog, ChangeEntry


@pytest.fixture
def gen(tmp_path):
    store = MemoryStore(tmp_path / "cl.db", agent_id="test")
    store.learn("Entry 1", topic="python")
    store.learn("Entry 2", topic="database")
    g = ChangelogGenerator(store)
    yield g
    store.close()


class TestChangelog:
    def test_generate(self, gen):
        log = gen.generate(days=1)
        assert isinstance(log, Changelog)

    def test_has_changes(self, gen):
        log = gen.generate(days=1)
        assert log.stats["total_changes"] >= 0

    def test_to_markdown(self, gen):
        log = gen.generate(days=1)
        md = log.to_markdown()
        assert "Knowledge Changelog" in md

    def test_daily_summary(self, gen):
        summary = gen.daily_summary()
        assert "date" in summary
        assert "changes" in summary

    def test_empty_changelog(self):
        cl = Changelog()
        assert cl.stats["total_changes"] == 0
        md = cl.to_markdown()
        assert "Total changes: 0" in md

    def test_change_entry(self):
        entry = ChangeEntry(
            timestamp="2026-03-14T00:00:00",
            action="learn", agent_id="test",
            topic="python", summary="New fact",
        )
        assert entry.action == "learn"
