# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Configuration Manager — centralized config for all modules.

Provides typed, validated configuration with defaults, env overrides,
and file-based persistence.

Usage:
    from uaml.core.config import ConfigManager

    config = ConfigManager()
    config.set("store.default_confidence", 0.8)
    val = config.get("store.default_confidence")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


# Default configuration
DEFAULTS = {
    "store": {
        "default_confidence": 0.8,
        "default_data_layer": "knowledge",
        "default_source_type": "manual",
        "max_content_length": 50000,
    },
    "search": {
        "default_limit": 10,
        "min_confidence": 0.0,
        "cache_enabled": True,
        "cache_ttl_seconds": 300,
    },
    "security": {
        "encryption_enabled": True,
        "audit_enabled": True,
        "rbac_enabled": False,
        "max_login_attempts": 5,
    },
    "backup": {
        "compress": True,
        "max_backups": 10,
        "auto_backup_hours": 24,
    },
    "federation": {
        "enabled": False,
        "share_identity": False,
        "max_peers": 10,
    },
    "retention": {
        "default_max_age_days": 365,
        "auto_archive": False,
    },
}


class ConfigManager:
    """Centralized configuration manager."""

    def __init__(self, config_path: Optional[str] = None):
        self._config: dict = {}
        self._config_path = config_path
        self._load_defaults()
        if config_path:
            self._load_file(config_path)
        self._apply_env_overrides()

    def _load_defaults(self):
        """Load default configuration."""
        import copy
        self._config = copy.deepcopy(DEFAULTS)

    def _load_file(self, path: str):
        """Load configuration from JSON file."""
        p = Path(path)
        if p.exists():
            with open(p) as f:
                file_config = json.load(f)
            self._merge(self._config, file_config)

    def _apply_env_overrides(self):
        """Apply environment variable overrides (UAML_SECTION_KEY format)."""
        prefix = "UAML_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                parts = key[len(prefix):].lower().split("_", 1)
                if len(parts) == 2:
                    section, setting = parts
                    if section in self._config:
                        # Type coercion
                        existing = self._config[section].get(setting)
                        if isinstance(existing, bool):
                            self._config[section][setting] = value.lower() in ("true", "1", "yes")
                        elif isinstance(existing, int):
                            try:
                                self._config[section][setting] = int(value)
                            except ValueError:
                                pass
                        elif isinstance(existing, float):
                            try:
                                self._config[section][setting] = float(value)
                            except ValueError:
                                pass
                        else:
                            self._config[section][setting] = value

    def get(self, dotpath: str, default: Any = None) -> Any:
        """Get config value by dot path (e.g. 'store.default_confidence')."""
        parts = dotpath.split(".")
        current = self._config
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, dotpath: str, value: Any) -> None:
        """Set config value by dot path."""
        parts = dotpath.split(".")
        current = self._config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def section(self, name: str) -> dict:
        """Get entire config section."""
        return dict(self._config.get(name, {}))

    def save(self, path: Optional[str] = None) -> None:
        """Save config to file."""
        target = path or self._config_path
        if not target:
            raise ValueError("No config path specified")
        with open(target, "w") as f:
            json.dump(self._config, f, indent=2)

    def to_dict(self) -> dict:
        """Get full config as dict."""
        import copy
        return copy.deepcopy(self._config)

    def reset(self) -> None:
        """Reset to defaults."""
        self._load_defaults()

    def _merge(self, base: dict, override: dict) -> None:
        """Deep merge override into base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value
