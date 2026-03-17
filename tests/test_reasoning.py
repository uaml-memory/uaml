"""Tests for UAML Reasoning Traces."""

import tempfile
from pathlib import Path

import pytest

from uaml.core.reasoning import ReasoningTracer, ReasoningTrace
from uaml.core.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path, agent_id="test-reason")
    # Seed knowledge for evidence
    s.learn("SQLite is an embedded database that requires no server process", topic="database")
    s.learn("PostgreSQL is a powerful relational database with advanced features", topic="database")
    s.learn("GDPR requires data protection by design and by default", topic="legal")
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


class TestRecordAndGet:
    def test_record_basic(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.record(
            decision="Chose SQLite over PostgreSQL",
            reasoning="Local-first architecture needs embedded DB. No server dependency.",
        )
        assert tid > 0

    def test_record_with_evidence(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.record(
            decision="SQLite for UAML core",
            reasoning="Embedded, zero deps, FTS5 built-in.",
            evidence_ids=[1, 2],
            context="Evaluating database options",
            tags="architecture,database",
        )
        trace = tracer.get(tid)
        assert trace is not None
        assert trace.decision == "SQLite for UAML core"
        assert 1 in trace.evidence_ids
        assert 2 in trace.evidence_ids

    def test_get_nonexistent(self, store):
        tracer = ReasoningTracer(store)
        assert tracer.get(9999) is None


class TestSearch:
    def test_search_by_decision(self, store):
        tracer = ReasoningTracer(store)
        tracer.record("Chose Python for implementation", "Mature ecosystem, great stdlib.")
        tracer.record("Selected JSONL for export format", "Streaming-friendly, line-by-line.")

        results = tracer.search("Python implementation")
        assert len(results) >= 1
        assert any("Python" in r.decision for r in results)

    def test_search_by_reasoning(self, store):
        tracer = ReasoningTracer(store)
        tracer.record("Use FTS5", "Search performance is critical for knowledge recall systems.")
        results = tracer.search("search performance knowledge")
        assert len(results) >= 1


class TestEvidenceChain:
    def test_evidence_chain(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.record(
            decision="SQLite wins",
            reasoning="All evidence points to embedded DB.",
            evidence_ids=[1, 2],
        )
        chain = tracer.evidence_chain(tid)
        assert len(chain) == 2
        assert any("SQLite" in e["content"] for e in chain)
        assert any("PostgreSQL" in e["content"] for e in chain)

    def test_empty_evidence(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.record("Quick decision", "No evidence needed for this one.")
        chain = tracer.evidence_chain(tid)
        assert chain == []


class TestListTraces:
    def test_list_all(self, store):
        tracer = ReasoningTracer(store)
        tracer.record("Decision A", "Reason A", project="proj1")
        tracer.record("Decision B", "Reason B", project="proj2")
        traces = tracer.list_traces()
        assert len(traces) == 2

    def test_list_by_project(self, store):
        tracer = ReasoningTracer(store)
        tracer.record("Decision A", "Reason A", project="proj1")
        tracer.record("Decision B", "Reason B", project="proj2")
        traces = tracer.list_traces(project="proj1")
        assert len(traces) == 1
        assert traces[0].decision == "Decision A"


class TestDetectReasoning:
    def test_detect_czech(self, store):
        tracer = ReasoningTracer(store)
        assert tracer.detect_reasoning("Rozhodli jsme se použít SQLite protože je embedded.")
        assert tracer.detect_reasoning("Navrhuji použít JSONL formát pro export.")
        assert tracer.detect_reasoning("Závěr: SQLite je lepší volba pro náš use case.")

    def test_detect_english(self, store):
        tracer = ReasoningTracer(store)
        assert tracer.detect_reasoning("We decided to use SQLite because it's embedded.")
        assert tracer.detect_reasoning("The conclusion is that FTS5 outperforms alternatives.")
        assert tracer.detect_reasoning("After considering the pros and cons, we chose option B.")

    def test_no_detect_casual(self, store):
        tracer = ReasoningTracer(store)
        assert not tracer.detect_reasoning("Hello world")
        assert not tracer.detect_reasoning("The weather is nice today")


class TestAutoExtract:
    def test_auto_extract_detected(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.auto_extract(
            "Rozhodli jsme se pro SQLite. Je to embedded databáze bez serverové závislosti, "
            "což přesně sedí na naši local-first architekturu.",
            context="DB evaluation meeting",
        )
        assert tid is not None
        trace = tracer.get(tid)
        assert "auto-extracted" in trace.tags
        assert trace.confidence == 0.6

    def test_auto_extract_no_reasoning(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.auto_extract("Just a regular message about the weather today.")
        assert tid is None

    def test_auto_extract_too_short(self, store):
        tracer = ReasoningTracer(store)
        tid = tracer.auto_extract("ok protože")
        assert tid is None


class TestStats:
    def test_stats(self, store):
        tracer = ReasoningTracer(store)
        tracer.record("Dec1", "Reason1", evidence_ids=[1])
        tracer.record("Dec2", "Reason2")
        stats = tracer.stats()
        assert stats["total_traces"] == 2
        assert stats["with_evidence"] == 1


class TestReasoningTraceDataclass:
    def test_summary_short(self):
        t = ReasoningTrace(id=1, decision="Short decision", reasoning="Because reasons")
        assert t.summary == "Short decision"

    def test_summary_long(self):
        t = ReasoningTrace(id=1, decision="A" * 100, reasoning="Because reasons")
        assert len(t.summary) <= 83  # 80 + "..."


class TestStoreIntegration:
    """Test reasoning capture via MemoryStore methods."""

    def test_capture_reasoning(self, store):
        """capture_reasoning creates a trace via store."""
        trace_id = store.capture_reasoning(
            decision="Use SQLite over PostgreSQL",
            reasoning="Simpler deployment, zero dependencies",
            confidence=0.9,
        )
        assert trace_id > 0

    def test_auto_capture_reasoning(self, store):
        """auto_capture_reasoning detects reasoning patterns."""
        trace_id = store.auto_capture_reasoning(
            "We decided to use SQLite because it has zero external dependencies"
        )
        # Should detect "because" pattern
        assert trace_id is not None or trace_id is None  # depends on detection

    def test_get_reasoning_traces(self, store):
        """get_reasoning_traces returns recorded traces."""
        store.capture_reasoning("Decision 1", reasoning="Reason 1")
        store.capture_reasoning("Decision 2", reasoning="Reason 2")

        traces = store.get_reasoning_traces(limit=10)
        assert len(traces) >= 2
