# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Plugin Manager — hook-based plugin system.

Supports named hooks with priority ordering and error handling.
Plugins can transform data, validate inputs, or add side effects.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class HookType(enum.Enum):
    """Available hook points in the UAML pipeline."""
    PRE_LEARN = "pre_learn"
    POST_LEARN = "post_learn"
    PRE_SEARCH = "pre_search"
    POST_SEARCH = "post_search"
    PRE_EXPORT = "pre_export"
    POST_EXPORT = "post_export"
    TRANSFORM = "transform"
    VALIDATE = "validate"
    ON_ERROR = "on_error"


@dataclass
class Plugin:
    """A registered plugin with metadata."""
    name: str
    hook: HookType
    callback: Callable
    priority: int = 100  # Lower = earlier
    enabled: bool = True
    description: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = self.callback.__name__


class PluginManager:
    """Manage and execute plugins at defined hook points."""

    def __init__(self):
        self._plugins: dict[HookType, list[Plugin]] = {h: [] for h in HookType}
        self._error_count: int = 0

    def register(
        self,
        hook: HookType,
        callback: Callable,
        *,
        name: str = "",
        priority: int = 100,
        description: str = "",
    ) -> Plugin:
        """Register a plugin callback for a hook.

        Args:
            hook: Which hook point to attach to
            callback: Function to call. Receives data dict, returns data dict.
            name: Plugin name (defaults to function name)
            priority: Execution order (lower = earlier)
            description: Human-readable description
        """
        plugin = Plugin(
            name=name or callback.__name__,
            hook=hook,
            callback=callback,
            priority=priority,
            description=description,
        )
        self._plugins[hook].append(plugin)
        self._plugins[hook].sort(key=lambda p: p.priority)
        return plugin

    def hook(self, hook_type: HookType, *, priority: int = 100, name: str = ""):
        """Decorator to register a hook callback.

        Usage:
            @manager.hook(HookType.PRE_LEARN)
            def my_plugin(data):
                return data
        """
        def decorator(fn):
            self.register(hook_type, fn, priority=priority, name=name or fn.__name__)
            return fn
        return decorator

    def unregister(self, name: str) -> int:
        """Remove all plugins with a given name. Returns count removed."""
        removed = 0
        for hook in HookType:
            before = len(self._plugins[hook])
            self._plugins[hook] = [p for p in self._plugins[hook] if p.name != name]
            removed += before - len(self._plugins[hook])
        return removed

    def apply(self, hook: HookType, data: Any) -> Any:
        """Execute all plugins for a hook, passing data through the chain.

        Each plugin receives the output of the previous one.
        If a plugin raises, it's logged and skipped (unless ON_ERROR).
        """
        for plugin in self._plugins[hook]:
            if not plugin.enabled:
                continue
            try:
                result = plugin.callback(data)
                if result is not None:
                    data = result
            except Exception as e:
                self._error_count += 1
                logger.warning("Plugin '%s' error: %s", plugin.name, e)
                # Fire ON_ERROR hooks (but don't recurse)
                if hook != HookType.ON_ERROR:
                    self.apply(HookType.ON_ERROR, {
                        "plugin": plugin.name,
                        "hook": hook.value,
                        "error": str(e),
                        "data": data,
                    })
        return data

    def list_plugins(self, hook: Optional[HookType] = None) -> list[dict]:
        """List registered plugins."""
        result = []
        hooks = [hook] if hook else list(HookType)
        for h in hooks:
            for p in self._plugins[h]:
                result.append({
                    "name": p.name,
                    "hook": p.hook.value,
                    "priority": p.priority,
                    "enabled": p.enabled,
                    "description": p.description,
                })
        return result

    def enable(self, name: str) -> int:
        """Enable plugins by name."""
        return self._set_enabled(name, True)

    def disable(self, name: str) -> int:
        """Disable plugins by name."""
        return self._set_enabled(name, False)

    def _set_enabled(self, name: str, enabled: bool) -> int:
        count = 0
        for hook in HookType:
            for p in self._plugins[hook]:
                if p.name == name:
                    p.enabled = enabled
                    count += 1
        return count

    @property
    def error_count(self) -> int:
        return self._error_count

    def stats(self) -> dict:
        """Plugin system statistics."""
        total = sum(len(ps) for ps in self._plugins.values())
        active = sum(
            sum(1 for p in ps if p.enabled)
            for ps in self._plugins.values()
        )
        return {
            "total_plugins": total,
            "active_plugins": active,
            "error_count": self._error_count,
            "hooks": {
                h.value: len(self._plugins[h])
                for h in HookType
                if self._plugins[h]
            },
        }
