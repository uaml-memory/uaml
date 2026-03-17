"""Tests for UAML I/O — export and import."""

import json
import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.io.exporter import Exporter
from uaml.io.importer import Importer, ImportStats


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path, agent_id="test")
    # Seed data
    s.learn("Python uses GIL for threading", topic="python", tags="concurrency")
    s.learn("Neo4j uses Cypher", topic="database", project="uaml")
    s.learn("GDPR requires consent", topic="legal", client_ref="client-A",
            valid_from="2018-05-25")
    s.create_task("Build MCP", project="uaml", assigned_to="cyril")
    s.create_task("Write docs", project="uaml", assigned_to="metod")
    s.create_artifact("report.pdf", project="uaml", artifact_type="report")
    # Link
    s.link_source(1, 2, link_type="related")
    s.link_task_knowledge(1, 1)
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def empty_store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path, agent_id="importer")
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


class TestExporter:
    def test_export_all_knowledge(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_knowledge(path)
        assert count == 3

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 3
        obj = json.loads(lines[0])
        assert obj["_type"] == "knowledge"
        assert "content" in obj
        Path(path).unlink()

    def test_export_by_topic(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_knowledge(path, topic="python")
        assert count == 1

        with open(path) as f:
            obj = json.loads(f.readline())
        assert "GIL" in obj["content"]
        Path(path).unlink()

    def test_export_by_project(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_knowledge(path, project="uaml")
        assert count == 1
        Path(path).unlink()

    def test_export_by_client(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_knowledge(path, client_ref="client-A")
        assert count == 1
        Path(path).unlink()

    def test_export_tasks(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_tasks(path)
        assert count == 2
        Path(path).unlink()

    def test_export_tasks_by_assigned(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_tasks(path, assigned_to="cyril")
        assert count == 1
        Path(path).unlink()

    def test_export_artifacts(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        count = exporter.export_artifacts(path)
        assert count == 1
        Path(path).unlink()

    def test_export_all(self, store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        counts = exporter.export_all(path)
        assert counts["knowledge"] == 3
        assert counts["tasks"] == 2
        assert counts["artifacts"] == 1
        assert counts["source_links"] >= 1
        assert counts["task_knowledge"] >= 1
        assert counts["total"] > 0
        Path(path).unlink()

    def test_identity_export_blocked(self, store):
        exporter = Exporter(store)
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        with pytest.raises(PermissionError):
            exporter.export_knowledge(path, data_layer="identity")
        Path(path).unlink()

    def test_identity_export_with_confirm(self, store):
        exporter = Exporter(store)
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        # Should not raise (even if 0 results)
        count = exporter.export_knowledge(path, data_layer="identity", confirm_identity=True)
        assert count >= 0
        Path(path).unlink()


class TestImporter:
    def test_import_knowledge(self, store, empty_store):
        # Export from store
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        exporter.export_knowledge(path)

        # Import into empty store
        importer = Importer(empty_store)
        stats = importer.import_file(path)
        assert stats.imported == 3
        assert stats.errors == 0
        assert stats.by_type.get("knowledge", 0) == 3

        # Verify data
        results = empty_store.search("GIL")
        assert len(results) >= 1
        Path(path).unlink()

    def test_import_tasks(self, store, empty_store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        exporter.export_tasks(path)

        importer = Importer(empty_store)
        stats = importer.import_file(path)
        assert stats.imported == 2
        assert stats.by_type.get("task", 0) == 2

        tasks = empty_store.list_tasks()
        assert len(tasks) == 2
        Path(path).unlink()

    def test_import_full_roundtrip(self, store, empty_store):
        """Full export → import roundtrip."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        export_counts = exporter.export_all(path)

        importer = Importer(empty_store)
        stats = importer.import_file(path)

        # All non-link items should import
        assert stats.imported >= export_counts["knowledge"] + export_counts["tasks"] + export_counts["artifacts"]
        assert stats.errors == 0
        Path(path).unlink()

    def test_import_dedup(self, store):
        """Importing same data twice should dedup."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        exporter.export_knowledge(path)

        # Import back into same store
        before = store.stats()["knowledge"]
        importer = Importer(store)
        stats = importer.import_file(path)

        after = store.stats()["knowledge"]
        # Should not increase (dedup)
        assert after == before
        Path(path).unlink()

    def test_import_with_override_agent(self, store, empty_store):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        exporter = Exporter(store)
        exporter.export_knowledge(path)

        importer = Importer(empty_store)
        stats = importer.import_file(path, override_agent="new-agent")
        assert stats.imported == 3

        # Check agent was overridden
        results = empty_store.search("GIL")
        assert results[0].entry.agent_id == "new-agent"
        Path(path).unlink()

    def test_import_stats_to_dict(self):
        stats = ImportStats()
        stats.imported = 5
        stats.skipped_dedup = 2
        d = stats.to_dict()
        assert d["imported"] == 5
        assert d["skipped_dedup"] == 2
