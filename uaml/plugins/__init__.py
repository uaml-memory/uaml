# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Plugin System — extensible hook-based architecture.

Register plugins to intercept and extend UAML operations:
pre/post learn, pre/post search, transform, validate.

Usage:
    from uaml.plugins import PluginManager, HookType

    manager = PluginManager()

    @manager.hook(HookType.PRE_LEARN)
    def validate_content(entry: dict) -> dict:
        if len(entry["content"]) < 10:
            raise ValueError("Content too short")
        return entry

    manager.apply(HookType.PRE_LEARN, {"content": "test"})
"""

from uaml.plugins.manager import PluginManager, HookType, Plugin

__all__ = ["PluginManager", "HookType", "Plugin"]
