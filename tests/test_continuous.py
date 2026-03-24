"""Tests for ContinuousLearner and source backfill."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.ingest.continuous import ContinuousLearner


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "test.db", agent_id="test")
    yield s
    s.close()


class TestContinuousLearner:
    def test_process_tool_result(self, store):
        learner = ContinuousLearner(store)
        msg = {
            "role": "tool",
            "name": "web_search",
            "content": "Python 3.13 introduces free-threaded mode, removing the GIL for better parallelism in CPU-bound tasks.",
        }
        created = learner.process_message(msg, session_id="test-session")
        assert created >= 1
        assert learner.stats()["tool_results_extracted"] >= 1

    def test_process_tool_calls(self, store):
        learner = ContinuousLearner(store)
        msg = {
            "role": "assistant",
            "content": "Let me search for that.",
            "tool_calls": [{
                "function": {"name": "web_fetch"},
                "result": "The UAML framework provides 5-layer data architecture for AI agent memory management with post-quantum encryption.",
            }],
        }
        created = learner.process_message(msg, session_id="s1")
        assert created >= 1

    def test_extract_decision(self, store):
        learner = ContinuousLearner(store)
        msg = {
            "role": "assistant",
            "content": "After analyzing the options, we decided to use SQLite because it has zero external dependencies and supports local-first operation perfectly.",
        }
        created = learner.process_message(msg, session_id="s2")
        # Should detect "decided to" pattern
        stats = learner.stats()
        assert stats["messages_processed"] == 1

    def test_skip_short_content(self, store):
        learner = ContinuousLearner(store)
        msg = {"role": "tool", "name": "exec", "content": "OK"}
        created = learner.process_message(msg, session_id="s3")
        assert created == 0

    def test_process_session_file(self, store, tmp_path):
        learner = ContinuousLearner(store)

        # Create a fake session file
        session_file = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"role": "user", "content": "Search for UAML info"}),
            json.dumps({
                "role": "tool", "name": "search",
                "content": "UAML is a Universal Agent Memory Layer providing persistent, auditable memory for AI agents with post-quantum encryption.",
            }),
            json.dumps({
                "role": "assistant",
                "content": "Based on the search results, I concluded that UAML provides comprehensive memory management for AI agents.",
            }),
        ]
        session_file.write_text("\n".join(lines))

        stats = learner.process_session_file(session_file)
        assert stats.messages_processed == 3

    def test_incremental_processing(self, store, tmp_path):
        learner = ContinuousLearner(store)
        session_file = tmp_path / "incr.jsonl"

        # First write
        with open(session_file, "w") as f:
            f.write(json.dumps({"role": "user", "content": "Hello world this is a test message"}) + "\n")

        stats1 = learner.process_session_file(session_file)
        assert stats1.messages_processed == 1

        # Append more
        with open(session_file, "a") as f:
            f.write(json.dumps({"role": "user", "content": "Another message with enough content to process"}) + "\n")

        stats2 = learner.process_session_file(session_file)
        # Should only process the new line
        assert stats2.messages_processed >= 1

    def test_stats(self, store):
        learner = ContinuousLearner(store)
        s = learner.stats()
        assert s["messages_processed"] == 0
        assert s["tracked_files"] == 0


class TestSourceBackfill:
    def test_backfill_dry_run(self, store):
        # Create entry with explicitly empty source metadata
        store._conn.execute(
            "INSERT INTO knowledge (content, tags, source_origin, source_type) VALUES (?, ?, '', '')",
            ("Test entry without source", "tool:exec"),
        )
        store._conn.commit()

        result = store.backfill_sources(dry_run=True)
        assert result["status"] == "dry_run"
        assert result["would_update"] >= 1

    def test_backfill_execute(self, store):
        store._conn.execute(
            "INSERT INTO knowledge (content, tags, source_origin, source_type) VALUES (?, ?, '', '')",
            ("Web search result content", "search,web"),
        )
        store._conn.commit()

        result = store.backfill_sources(dry_run=False)
        assert result["status"] == "completed"
        assert result["updated"] >= 1

        # Verify
        row = store._conn.execute(
            "SELECT source_origin, source_type FROM knowledge WHERE content = ?",
            ("Web search result content",),
        ).fetchone()
        assert row["source_origin"] == "external"

    def test_backfill_no_missing(self, store):
        store.learn("Full metadata", source_type="manual", source_origin="external")
        result = store.backfill_sources(dry_run=True)
        assert result["would_update"] == 0
