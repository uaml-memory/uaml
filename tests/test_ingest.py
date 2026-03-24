"""Tests for UAML Ingestors — chat, markdown, web."""

import json
import tempfile
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.ingest import ChatIngestor, MarkdownIngestor, WebIngestor
from uaml.ingest.base import IngestStats


@pytest.fixture
def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = MemoryStore(db_path, agent_id="test-ingest")
    yield s
    s.close()
    Path(db_path).unlink(missing_ok=True)


# ── IngestStats ──────────────────────────────────────────────


class TestIngestStats:
    def test_total_processed(self):
        s = IngestStats()
        s.entries_created = 5
        s.entries_skipped = 2
        s.entries_rejected = 1
        s.errors = 1
        assert s.total_processed == 9

    def test_repr(self):
        s = IngestStats(source="test.jsonl", source_type="chat")
        assert "test.jsonl" in repr(s)


# ── ChatIngestor ─────────────────────────────────────────────


class TestChatIngestor:
    def _make_jsonl(self, messages: list[dict]) -> str:
        """Create a temp JSONL file with messages."""
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
        f.close()
        return f.name

    def test_basic_ingest(self, store):
        path = self._make_jsonl([
            {"role": "user", "content": "How does Python handle memory management with garbage collection?"},
            {"role": "assistant", "content": "Python uses reference counting plus a cyclic garbage collector for memory management."},
        ])
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created == 2
        assert stats.errors == 0
        Path(path).unlink()

    def test_skip_system_messages(self, store):
        path = self._make_jsonl([
            {"role": "system", "content": "You are an assistant." * 5},
            {"role": "user", "content": "Tell me about Neo4j graph database and its Cypher query language."},
        ])
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created == 1
        assert stats.entries_skipped >= 1
        Path(path).unlink()

    def test_skip_heartbeats(self, store):
        path = self._make_jsonl([
            {"role": "assistant", "content": "HEARTBEAT_OK"},
            {"role": "assistant", "content": "NO_REPLY"},
            {"role": "user", "content": "What is the difference between SQL and NoSQL databases in practice?"},
        ])
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created == 1
        Path(path).unlink()

    def test_skip_short_messages(self, store):
        path = self._make_jsonl([
            {"role": "user", "content": "ok"},
            {"role": "user", "content": "yes"},
            {"role": "user", "content": "This is a longer message that should be ingested into the knowledge base."},
        ])
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created == 1
        assert stats.entries_skipped >= 2
        Path(path).unlink()

    def test_session_id_from_filename(self, store):
        path = self._make_jsonl([
            {"role": "user", "content": "What are the key differences between Python and JavaScript?"},
        ])
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(path)
        assert "session_id" in stats.details
        Path(path).unlink()

    def test_custom_session_id(self, store):
        path = self._make_jsonl([
            {"role": "user", "content": "How do you implement a binary search tree in Python?"},
        ])
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(path, session_id="my-session-123")
        assert stats.details["session_id"] == "my-session-123"
        Path(path).unlink()

    def test_file_not_found(self, store):
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest("/nonexistent/file.jsonl")
        assert stats.errors == 1

    def test_invalid_json_lines(self, store):
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        f.write("not json\n")
        f.write(json.dumps({"role": "user", "content": "A valid message about machine learning and neural networks."}) + "\n")
        f.write("{broken\n")
        f.close()
        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(f.name)
        assert stats.entries_created == 1
        assert stats.errors == 2
        Path(f.name).unlink()

    def test_can_handle(self, store):
        ingestor = ChatIngestor(store)
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        f.close()
        assert ingestor.can_handle(f.name) is True
        assert ingestor.can_handle("/fake/file.txt") is False
        Path(f.name).unlink()


# ── MarkdownIngestor ─────────────────────────────────────────


class TestMarkdownIngestor:
    def _make_md(self, content: str, name: str = "test.md") -> str:
        f = tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, prefix=name)
        f.write(content)
        f.close()
        return f.name

    def test_whole_file_ingest(self, store):
        path = self._make_md("This is a test markdown file with enough content to pass the minimum length filter for ingestion.")
        ingestor = MarkdownIngestor(store)
        stats = ingestor.ingest(path, split_sections=False)
        assert stats.entries_created == 1
        Path(path).unlink()

    def test_section_split(self, store):
        content = """# Main Title

Intro text that is ignored.

## Section One

Content of section one is about Python programming and its memory model.

## Section Two

Content of section two covers database design patterns and normalization.

## Section Three

Content of section three discusses API design best practices.
"""
        path = self._make_md(content)
        ingestor = MarkdownIngestor(store)
        stats = ingestor.ingest(path, split_sections=True, heading_level=2)
        assert stats.entries_created == 3
        Path(path).unlink()

    def test_frontmatter_extraction(self, store):
        content = """---
topic: python
tags: programming,tutorial
project: uaml
---

## Getting Started

This section explains how to get started with the Python programming language.
"""
        path = self._make_md(content)
        ingestor = MarkdownIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created == 1

        results = store.search("Getting Started")
        assert len(results) >= 1
        Path(path).unlink()

    def test_directory_ingest(self, store):
        tmpdir = tempfile.mkdtemp()
        for i in range(3):
            Path(tmpdir, f"doc{i}.md").write_text(
                f"## Document {i}\n\nThis is the content of document number {i} with enough text to pass the filter."
            )
        ingestor = MarkdownIngestor(store)
        stats = ingestor.ingest(tmpdir)
        assert stats.entries_created == 3

        # Cleanup
        for f in Path(tmpdir).glob("*.md"):
            f.unlink()
        Path(tmpdir).rmdir()

    def test_empty_file(self, store):
        path = self._make_md("")
        ingestor = MarkdownIngestor(store)
        stats = ingestor.ingest(path, split_sections=False)
        assert stats.entries_created == 0
        Path(path).unlink()

    def test_can_handle(self, store):
        ingestor = MarkdownIngestor(store)
        path = self._make_md("test content for can_handle")
        assert ingestor.can_handle(path) is True
        assert ingestor.can_handle("/fake.txt") is False
        Path(path).unlink()


# ── WebIngestor ──────────────────────────────────────────────


class TestWebIngestor:
    def _make_html(self, html_content: str) -> str:
        f = tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False)
        f.write(html_content)
        f.close()
        return f.name

    def test_local_html_ingest(self, store):
        path = self._make_html("""
        <html>
        <head><title>Test Page About Python</title></head>
        <body>
        <h1>Python Guide</h1>
        <p>Python is a versatile programming language used for web development, data science, and automation tasks.</p>
        </body>
        </html>
        """)
        ingestor = WebIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created >= 1
        assert stats.details.get("title") == "Test Page About Python"
        Path(path).unlink()

    def test_html_tag_stripping(self, store):
        path = self._make_html("""
        <html><body>
        <script>alert('malicious');</script>
        <style>.hidden { display: none; }</style>
        <p>Only this clean text about database optimization should remain after the HTML stripping process.</p>
        </body></html>
        """)
        ingestor = WebIngestor(store)
        stats = ingestor.ingest(path)
        assert stats.entries_created >= 1

        results = store.search("clean text")
        assert len(results) >= 1
        # Should not contain script content
        assert "alert" not in results[0].entry.content
        Path(path).unlink()

    def test_text_file_ingest(self, store):
        f = tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False)
        f.write("This is a plain text file about machine learning algorithms and their applications in production.")
        f.close()
        ingestor = WebIngestor(store)
        stats = ingestor.ingest(f.name)
        assert stats.entries_created == 1
        Path(f.name).unlink()

    def test_chunking(self, store):
        # Create content longer than chunk_size
        long_text = "A" * 100 + ". " + "B" * 100 + ". " + "C" * 100
        path = self._make_html(f"<html><body><p>{long_text}</p></body></html>")
        ingestor = WebIngestor(store, chunk_size=80, min_content_length=10)
        stats = ingestor.ingest(path, chunk=True)
        assert stats.entries_created >= 1
        Path(path).unlink()

    def test_file_not_found(self, store):
        ingestor = WebIngestor(store)
        stats = ingestor.ingest("/nonexistent/page.html")
        assert stats.errors == 1

    def test_url_detection(self, store):
        ingestor = WebIngestor(store)
        # Invalid URL should fail gracefully
        stats = ingestor.ingest("http://localhost:99999/nonexistent")
        assert stats.errors >= 1

    def test_can_handle(self, store):
        ingestor = WebIngestor(store)
        assert ingestor.can_handle("https://example.com") is True
        path = self._make_html("<p>test</p>")
        assert ingestor.can_handle(path) is True
        assert ingestor.can_handle("/fake.py") is False
        Path(path).unlink()


# ── Source Origin & Data Layer ───────────────────────────────


class TestSourceMetadata:
    def test_chat_ingestor_sets_observed_team(self, store):
        """ChatIngestor should set source_origin=observed, data_layer=team."""
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False)
        f.write(json.dumps({"role": "user", "content": "What is the architecture of our UAML memory system?"}) + "\n")
        f.close()

        ingestor = ChatIngestor(store)
        stats = ingestor.ingest(f.name)
        assert stats.entries_created == 1

        row = store.conn.execute("SELECT source_origin, data_layer FROM knowledge WHERE id = 1").fetchone()
        assert row["source_origin"] == "observed"
        assert row["data_layer"] == "team"
        Path(f.name).unlink()

    def test_markdown_ingestor_sets_external_knowledge(self, store):
        """MarkdownIngestor should set source_origin=external, data_layer=knowledge."""
        f = tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False)
        f.write("This is a markdown document about Python programming best practices and design patterns.")
        f.close()

        ingestor = MarkdownIngestor(store)
        stats = ingestor.ingest(f.name, split_sections=False)
        assert stats.entries_created == 1

        row = store.conn.execute("SELECT source_origin, data_layer FROM knowledge WHERE id = 1").fetchone()
        assert row["source_origin"] == "external"
        assert row["data_layer"] == "knowledge"
        Path(f.name).unlink()

    def test_web_ingestor_sets_external_knowledge(self, store):
        """WebIngestor should set source_origin=external, data_layer=knowledge."""
        f = tempfile.NamedTemporaryFile(suffix=".html", mode="w", delete=False)
        f.write("<html><body><p>A web page about distributed systems and consensus algorithms.</p></body></html>")
        f.close()

        ingestor = WebIngestor(store)
        stats = ingestor.ingest(f.name)
        assert stats.entries_created == 1

        row = store.conn.execute("SELECT source_origin, data_layer FROM knowledge WHERE id = 1").fetchone()
        assert row["source_origin"] == "external"
        assert row["data_layer"] == "knowledge"
        Path(f.name).unlink()


class TestIngestRegistry:
    """Tests for IngestRegistry plugin system."""

    def test_list_builtins(self):
        """Built-in ingestors are registered."""
        from uaml.ingest import IngestRegistry
        registry = IngestRegistry.list()
        assert "chat" in registry
        assert "markdown" in registry
        assert "web" in registry

    def test_get_ingestor(self):
        """Get returns registered class."""
        from uaml.ingest import IngestRegistry, ChatIngestor
        assert IngestRegistry.get("chat") is ChatIngestor
        assert IngestRegistry.get("nonexistent") is None

    def test_register_custom(self):
        """Custom ingestor can be registered and retrieved."""
        from uaml.ingest import IngestRegistry, BaseIngestor, IngestStats

        @IngestRegistry.register("test_custom")
        class TestCustomIngestor(BaseIngestor):
            source_type = "test"
            def ingest(self, source, **kwargs):
                return IngestStats(source=str(source))
            def can_handle(self, source):
                return str(source).endswith(".test")

        assert "test_custom" in IngestRegistry.list()
        assert IngestRegistry.get("test_custom") is TestCustomIngestor

        # Clean up
        del IngestRegistry._registry["test_custom"]

    def test_detect_jsonl(self):
        """Detect identifies JSONL as chat format."""
        from uaml.ingest import IngestRegistry
        result = IngestRegistry.detect("session.jsonl")
        assert result == "chat"

    def test_detect_markdown(self):
        """Detect identifies .md as markdown format."""
        from uaml.ingest import IngestRegistry
        result = IngestRegistry.detect("document.md")
        assert result == "markdown"

    def test_detect_html(self):
        """Detect identifies .html as web format."""
        from uaml.ingest import IngestRegistry
        result = IngestRegistry.detect("page.html")
        assert result == "web"

    def test_detect_unknown(self):
        """Detect returns None for unknown format."""
        from uaml.ingest import IngestRegistry
        result = IngestRegistry.detect("data.xyz")
        assert result is None

    def test_auto_ingest_unknown_raises(self, store):
        """Auto-ingest raises ValueError for unknown source."""
        from uaml.ingest import IngestRegistry
        import pytest
        with pytest.raises(ValueError, match="No ingestor can handle"):
            IngestRegistry.auto_ingest(store, "data.xyz")
