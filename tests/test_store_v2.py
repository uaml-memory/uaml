"""Tests for UAML MemoryStore v2 — task, artifact, and provenance methods."""

import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path, agent_id="test-agent")
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


class TestTaskStore:
    def test_create_task(self, store):
        tid = store.create_task("Build MCP server", project="uaml", priority=1)
        assert tid > 0

    def test_list_tasks(self, store):
        store.create_task("Task A", project="p1", status="todo")
        store.create_task("Task B", project="p1", status="done")
        store.create_task("Task C", project="p2", status="todo")

        all_tasks = store.list_tasks()
        assert len(all_tasks) == 3

        p1 = store.list_tasks(project="p1")
        assert len(p1) == 2

        todo = store.list_tasks(status="todo")
        assert len(todo) == 2

    def test_update_task(self, store):
        tid = store.create_task("Test task", status="todo")
        assert store.update_task(tid, status="in_progress")

        tasks = store.list_tasks()
        assert tasks[0]["status"] == "in_progress"

    def test_complete_task_sets_completed_at(self, store):
        tid = store.create_task("Complete me")
        store.update_task(tid, status="done")

        tasks = store.list_tasks(status="done")
        assert len(tasks) == 1
        assert tasks[0]["completed_at"] is not None

    def test_update_nonexistent(self, store):
        assert not store.update_task(9999, status="done")

    def test_search_tasks(self, store):
        store.create_task("Fix Ollama GPU detection", description="CUDA issue on WSL2")
        store.create_task("Write documentation")

        results = store.search_tasks("Ollama GPU")
        assert len(results) >= 1
        assert "Ollama" in results[0]["title"]

    def test_task_assignment(self, store):
        store.create_task("agent-b's task", assigned_to="cyril")
        store.create_task("agent-a's task", assigned_to="metod")

        cyril_tasks = store.list_tasks(assigned_to="cyril")
        assert len(cyril_tasks) == 1
        assert cyril_tasks[0]["title"] == "agent-b's task"

    def test_subtask(self, store):
        parent = store.create_task("Parent")
        child = store.create_task("Child", parent_id=parent)

        children = store.list_tasks(parent_id=parent)
        assert len(children) == 1

    def test_task_client_isolation(self, store):
        store.create_task("Client A work", client_ref="a")
        store.create_task("Client B work", client_ref="b")

        a_tasks = store.list_tasks(client_ref="a")
        assert len(a_tasks) == 1


class TestArtifactStore:
    def test_create_artifact(self, store):
        aid = store.create_artifact("report.pdf", artifact_type="report", project="uaml")
        assert aid > 0

    def test_list_artifacts(self, store):
        tid = store.create_task("Generate report")
        store.create_artifact("output.csv", task_id=tid, project="p1")
        store.create_artifact("analysis.md", project="p1")
        store.create_artifact("other.txt", project="p2")

        p1 = store.list_artifacts(project="p1")
        assert len(p1) == 2

        task_arts = store.list_artifacts(task_id=tid)
        assert len(task_arts) == 1

    def test_artifact_with_metadata(self, store):
        aid = store.create_artifact(
            "model.bin",
            artifact_type="model",
            path="/models/model.bin",
            mime_type="application/octet-stream",
            size_bytes=1024000,
            checksum="abc123",
            status="final",
        )
        arts = store.list_artifacts()
        assert arts[0]["size_bytes"] == 1024000
        assert arts[0]["checksum"] == "abc123"


class TestSourceLinks:
    def test_link_and_get_sources(self, store):
        src = store.learn("GDPR regulation original text", topic="legal")
        derived = store.learn("Our privacy policy based on GDPR", topic="policy")

        store.link_source(src, derived, link_type="based_on")

        sources = store.get_sources(derived)
        assert len(sources) == 1
        assert sources[0]["source_id"] == src
        assert "GDPR" in sources[0]["content"]

    def test_get_derived(self, store):
        src = store.learn("Source document")
        d1 = store.learn("Analysis 1")
        d2 = store.learn("Analysis 2")

        store.link_source(src, d1)
        store.link_source(src, d2)

        derived = store.get_derived(src)
        assert len(derived) == 2

    def test_link_types(self, store):
        a = store.learn("Old law")
        b = store.learn("New law")

        store.link_source(a, b, link_type="supersedes")

        sources = store.get_sources(b)
        assert sources[0]["link_type"] == "supersedes"


class TestTaskKnowledgeLinks:
    def test_link_and_retrieve(self, store):
        eid = store.learn("Neo4j uses Cypher query language", topic="database")
        tid = store.create_task("Research Neo4j")

        store.link_task_knowledge(tid, eid, relation="research")

        knowledge = store.get_task_knowledge(tid)
        assert len(knowledge) == 1
        assert "Cypher" in knowledge[0]["content"]
        assert knowledge[0]["relation"] == "research"

    def test_multiple_links(self, store):
        e1 = store.learn("Fact 1")
        e2 = store.learn("Fact 2")
        tid = store.create_task("Research task")

        store.link_task_knowledge(tid, e1)
        store.link_task_knowledge(tid, e2)

        knowledge = store.get_task_knowledge(tid)
        assert len(knowledge) == 2

    def test_duplicate_link_ignored(self, store):
        eid = store.learn("Fact")
        tid = store.create_task("Task")

        store.link_task_knowledge(tid, eid)
        store.link_task_knowledge(tid, eid)  # Should not raise

        knowledge = store.get_task_knowledge(tid)
        assert len(knowledge) == 1


class TestStatsV2:
    def test_stats_includes_new_tables(self, store):
        store.create_task("A task")
        store.create_artifact("A file")

        s = store.stats()
        assert "tasks" in s
        assert s["tasks"] >= 1
        assert "artifacts" in s
        assert s["artifacts"] >= 1
        assert "source_links" in s
