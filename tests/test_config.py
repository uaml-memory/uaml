"""Tests for UAML Config Manager."""

from __future__ import annotations

import json
import pytest

from uaml.core.config import ConfigManager


class TestConfigManager:
    def test_defaults(self):
        cfg = ConfigManager()
        assert cfg.get("store.default_confidence") == 0.8

    def test_get_dotpath(self):
        cfg = ConfigManager()
        assert cfg.get("search.default_limit") == 10

    def test_get_missing(self):
        cfg = ConfigManager()
        assert cfg.get("nonexistent.key") is None
        assert cfg.get("nonexistent.key", 42) == 42

    def test_set(self):
        cfg = ConfigManager()
        cfg.set("store.default_confidence", 0.9)
        assert cfg.get("store.default_confidence") == 0.9

    def test_section(self):
        cfg = ConfigManager()
        sec = cfg.section("security")
        assert "encryption_enabled" in sec

    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "config.json")
        cfg = ConfigManager()
        cfg.set("store.default_confidence", 0.95)
        cfg.save(path)

        cfg2 = ConfigManager(config_path=path)
        assert cfg2.get("store.default_confidence") == 0.95

    def test_to_dict(self):
        cfg = ConfigManager()
        d = cfg.to_dict()
        assert "store" in d
        assert "security" in d

    def test_reset(self):
        cfg = ConfigManager()
        cfg.set("store.default_confidence", 0.1)
        cfg.reset()
        assert cfg.get("store.default_confidence") == 0.8

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("UAML_SEARCH_DEFAULT_LIMIT", "50")
        cfg = ConfigManager()
        assert cfg.get("search.default_limit") == 50

    def test_merge_file(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps({"store": {"default_confidence": 0.75}}))
        cfg = ConfigManager(config_path=str(path))
        assert cfg.get("store.default_confidence") == 0.75
        # Other defaults should remain
        assert cfg.get("store.max_content_length") == 50000
