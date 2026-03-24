"""Tests for UAML Schema v2 — 5-layer architecture, tasks, artifacts, source links."""

import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.core.models import DataLayer, SourceOrigin, TaskStatus, ArtifactStatus


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path)
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


class TestSchemaV2Tables:
    def test_tasks_table_exists(self, store):
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        assert tables is not None

    def test_artifacts_table_exists(self, store):
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts'"
        ).fetchone()
        assert tables is not None

    def test_source_links_table_exists(self, store):
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='source_links'"
        ).fetchone()
        assert tables is not None

    def test_task_knowledge_table_exists(self, store):
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='task_knowledge'"
        ).fetchone()
        assert tables is not None

    def test_tasks_fts_exists(self, store):
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks_fts'"
        ).fetchone()
        assert tables is not None


class TestTasksCRUD:
    def test_create_task(self, store):
        store.conn.execute(
            "INSERT INTO tasks (title, status, project) VALUES (?, ?, ?)",
            ("Build MCP server", "todo", "uaml")
        )
        store.conn.commit()
        task = store.conn.execute("SELECT * FROM tasks WHERE title = ?", ("Build MCP server",)).fetchone()
        assert task is not None
        assert task["status"] == "todo"
        assert task["project"] == "uaml"

    def test_task_lifecycle(self, store):
        store.conn.execute(
            "INSERT INTO tasks (title, status, assigned_to, priority) VALUES (?, ?, ?, ?)",
            ("Write tests", "todo", "cyril", 1)
        )
        store.conn.commit()

        # Move to in_progress
        store.conn.execute("UPDATE tasks SET status = 'in_progress' WHERE title = 'Write tests'")
        store.conn.commit()

        # Complete
        store.conn.execute(
            "UPDATE tasks SET status = 'done', completed_at = datetime('now') WHERE title = 'Write tests'"
        )
        store.conn.commit()

        task = store.conn.execute("SELECT * FROM tasks WHERE title = 'Write tests'").fetchone()
        assert task["status"] == "done"
        assert task["completed_at"] is not None

    def test_task_fts_search(self, store):
        store.conn.execute(
            "INSERT INTO tasks (title, description, tags) VALUES (?, ?, ?)",
            ("Fix Ollama GPU", "Resolve CUDA detection issue on WSL2", "gpu,ollama,wsl2")
        )
        store.conn.commit()

        results = store.conn.execute(
            "SELECT t.* FROM tasks_fts JOIN tasks t ON t.id = tasks_fts.rowid WHERE tasks_fts MATCH ?",
            ("CUDA",)
        ).fetchall()
        assert len(results) >= 1
        assert results[0]["title"] == "Fix Ollama GPU"

    def test_subtasks(self, store):
        store.conn.execute("INSERT INTO tasks (title) VALUES (?)", ("Parent task",))
        store.conn.commit()
        parent_id = store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        store.conn.execute(
            "INSERT INTO tasks (title, parent_id) VALUES (?, ?)",
            ("Subtask 1", parent_id)
        )
        store.conn.commit()

        subtasks = store.conn.execute(
            "SELECT * FROM tasks WHERE parent_id = ?", (parent_id,)
        ).fetchall()
        assert len(subtasks) == 1

    def test_task_client_isolation(self, store):
        store.conn.execute(
            "INSERT INTO tasks (title, client_ref) VALUES (?, ?)",
            ("Client A task", "client-a")
        )
        store.conn.execute(
            "INSERT INTO tasks (title, client_ref) VALUES (?, ?)",
            ("Client B task", "client-b")
        )
        store.conn.commit()

        a_tasks = store.conn.execute(
            "SELECT * FROM tasks WHERE client_ref = ?", ("client-a",)
        ).fetchall()
        assert len(a_tasks) == 1
        assert a_tasks[0]["title"] == "Client A task"


class TestArtifacts:
    def test_create_artifact(self, store):
        store.conn.execute(
            "INSERT INTO artifacts (name, artifact_type, path, status, project) VALUES (?, ?, ?, ?, ?)",
            ("report.pdf", "report", "/output/report.pdf", "final", "uaml")
        )
        store.conn.commit()

        art = store.conn.execute("SELECT * FROM artifacts WHERE name = ?", ("report.pdf",)).fetchone()
        assert art is not None
        assert art["status"] == "final"

    def test_artifact_linked_to_task(self, store):
        store.conn.execute("INSERT INTO tasks (title) VALUES (?)", ("Generate report",))
        store.conn.commit()
        task_id = store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        store.conn.execute(
            "INSERT INTO artifacts (name, task_id) VALUES (?, ?)",
            ("output.csv", task_id)
        )
        store.conn.commit()

        art = store.conn.execute(
            "SELECT * FROM artifacts WHERE task_id = ?", (task_id,)
        ).fetchone()
        assert art is not None
        assert art["name"] == "output.csv"


class TestSourceLinks:
    def test_create_source_link(self, store):
        id1 = store.learn("GDPR regulation text", topic="legal")
        id2 = store.learn("Our privacy policy is based on GDPR", topic="policy")

        store.conn.execute(
            "INSERT INTO source_links (source_id, target_id, link_type) VALUES (?, ?, ?)",
            (id1, id2, "based_on")
        )
        store.conn.commit()

        links = store.conn.execute(
            "SELECT * FROM source_links WHERE target_id = ?", (id2,)
        ).fetchall()
        assert len(links) == 1
        assert links[0]["source_id"] == id1
        assert links[0]["link_type"] == "based_on"

    def test_bidirectional_lookup(self, store):
        id1 = store.learn("Source document A")
        id2 = store.learn("Derived analysis B")
        id3 = store.learn("Derived analysis C")

        store.conn.execute(
            "INSERT INTO source_links (source_id, target_id, link_type) VALUES (?, ?, ?)",
            (id1, id2, "based_on")
        )
        store.conn.execute(
            "INSERT INTO source_links (source_id, target_id, link_type) VALUES (?, ?, ?)",
            (id1, id3, "based_on")
        )
        store.conn.commit()

        # Forward: what was derived from source A?
        derived = store.conn.execute(
            "SELECT target_id FROM source_links WHERE source_id = ?", (id1,)
        ).fetchall()
        assert len(derived) == 2

        # Backward: what is analysis B based on?
        sources = store.conn.execute(
            "SELECT source_id FROM source_links WHERE target_id = ?", (id2,)
        ).fetchall()
        assert len(sources) == 1
        assert sources[0]["source_id"] == id1


class TestTaskKnowledge:
    def test_link_task_to_knowledge(self, store):
        entry_id = store.learn("Neo4j uses Cypher", topic="database")

        store.conn.execute("INSERT INTO tasks (title) VALUES (?)", ("Research Neo4j",))
        store.conn.commit()
        task_id = store.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        store.conn.execute(
            "INSERT INTO task_knowledge (task_id, entry_id, relation) VALUES (?, ?, ?)",
            (task_id, entry_id, "research")
        )
        store.conn.commit()

        linked = store.conn.execute(
            "SELECT k.* FROM knowledge k JOIN task_knowledge tk ON tk.entry_id = k.id WHERE tk.task_id = ?",
            (task_id,)
        ).fetchall()
        assert len(linked) == 1
        assert "Cypher" in linked[0]["content"]


class TestDataLayerModels:
    def test_data_layer_enum(self):
        assert DataLayer.IDENTITY.value == "identity"
        assert DataLayer.KNOWLEDGE.value == "knowledge"
        assert DataLayer.TEAM.value == "team"
        assert DataLayer.OPERATIONAL.value == "operational"
        assert DataLayer.PROJECT.value == "project"

    def test_source_origin_enum(self):
        assert SourceOrigin.EXTERNAL.value == "external"
        assert SourceOrigin.GENERATED.value == "generated"
        assert SourceOrigin.DERIVED.value == "derived"
        assert SourceOrigin.OBSERVED.value == "observed"

    def test_task_status_enum(self):
        assert TaskStatus.TODO.value == "todo"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.BLOCKED.value == "blocked"
