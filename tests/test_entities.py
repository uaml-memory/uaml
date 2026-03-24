"""Tests for UAML Entity Extraction."""

from __future__ import annotations

import pytest

from uaml.reasoning.entities import EntityExtractor, extract_entities


@pytest.fixture
def extractor():
    return EntityExtractor()


class TestEntityExtraction:
    def test_extract_email(self, extractor):
        entities = extractor.extract("Contact info@smart-memory.ai for details")
        emails = [e for e in entities if e.entity_type == "email"]
        assert len(emails) == 1
        assert emails[0].text == "info@smart-memory.ai"

    def test_extract_url(self, extractor):
        entities = extractor.extract("Visit https://uaml.ai/docs for info")
        urls = [e for e in entities if e.entity_type == "url"]
        assert len(urls) == 1
        assert "uaml.ai" in urls[0].text

    def test_extract_ip(self, extractor):
        entities = extractor.extract("Server at 192.168.1.20:3003")
        ips = [e for e in entities if e.entity_type == "ip_address"]
        assert len(ips) == 1

    def test_extract_version(self, extractor):
        entities = extractor.extract("Updated to v1.0.0 from 0.4.2")
        versions = [e for e in entities if e.entity_type == "version"]
        assert len(versions) >= 2

    def test_extract_date(self, extractor):
        entities = extractor.extract("Meeting scheduled for 2026-03-14")
        dates = [e for e in entities if e.entity_type == "date_iso"]
        assert len(dates) == 1
        assert dates[0].text == "2026-03-14"

    def test_extract_file_path(self, extractor):
        entities = extractor.extract("Edit /home/user/project/main.py")
        paths = [e for e in entities if e.entity_type == "file_path"]
        assert len(paths) >= 1

    def test_extract_name_heuristic(self, extractor):
        entities = extractor.extract("John Smith decided to use UAML")
        names = [e for e in entities if e.entity_type == "name"]
        assert any("John" in e.text for e in names)

    def test_filter_non_names(self, extractor):
        entities = extractor.extract("The Monday meeting was about This")
        names = [e for e in entities if e.entity_type == "name"]
        assert not any(e.text in ("The", "Monday", "This") for e in names)

    def test_summarize(self, extractor):
        text = "Deploy v1.0.0 to 192.168.1.40 — see https://docs.uaml.ai"
        summary = extractor.summarize(text)
        assert "url" in summary
        assert "ip_address" in summary

    def test_extract_typed(self, extractor):
        text = "Email info@test.com and visit https://test.com"
        emails = extractor.extract_typed(text, "email")
        assert len(emails) == 1
        assert emails[0].entity_type == "email"

    def test_convenience_function(self):
        entities = extract_entities("Check 192.168.1.1 and info@glg.cz")
        assert len(entities) >= 2

    def test_dedup(self, extractor):
        entities = extractor.extract("Visit https://uaml.ai and https://uaml.ai again")
        urls = [e for e in entities if e.entity_type == "url"]
        assert len(urls) == 1

    def test_python_import(self, extractor):
        entities = extractor.extract("from uaml.core.store import MemoryStore")
        modules = [e for e in entities if e.entity_type == "module"]
        assert len(modules) == 1
        assert modules[0].text == "uaml.core.store"

    def test_hex_hash(self, extractor):
        entities = extractor.extract("Commit 7a9407c pushed to master")
        hashes = [e for e in entities if e.entity_type == "hex_hash"]
        assert len(hashes) == 1
