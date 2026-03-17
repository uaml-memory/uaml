"""Tests for UAML Plugin System."""

from __future__ import annotations

import pytest

from uaml.plugins import PluginManager, HookType


class TestPluginManager:
    def test_register_and_apply(self):
        pm = PluginManager()
        pm.register(HookType.PRE_LEARN, lambda d: {**d, "modified": True})
        result = pm.apply(HookType.PRE_LEARN, {"content": "test"})
        assert result["modified"] is True

    def test_decorator(self):
        pm = PluginManager()

        @pm.hook(HookType.VALIDATE)
        def check_length(data):
            assert len(data.get("content", "")) > 0
            return data

        result = pm.apply(HookType.VALIDATE, {"content": "ok"})
        assert result["content"] == "ok"

    def test_priority_order(self):
        pm = PluginManager()
        order = []

        pm.register(HookType.TRANSFORM, lambda d: order.append("b") or d, priority=200)
        pm.register(HookType.TRANSFORM, lambda d: order.append("a") or d, priority=50)

        pm.apply(HookType.TRANSFORM, {})
        assert order == ["a", "b"]

    def test_error_handling(self):
        pm = PluginManager()
        pm.register(HookType.PRE_LEARN, lambda d: 1/0)  # ZeroDivisionError
        # Should not raise
        result = pm.apply(HookType.PRE_LEARN, {"content": "ok"})
        assert result["content"] == "ok"
        assert pm.error_count == 1

    def test_disable_enable(self):
        pm = PluginManager()
        pm.register(HookType.TRANSFORM, lambda d: {**d, "x": True}, name="my_plugin")
        pm.disable("my_plugin")
        result = pm.apply(HookType.TRANSFORM, {})
        assert "x" not in result

        pm.enable("my_plugin")
        result = pm.apply(HookType.TRANSFORM, {})
        assert result["x"] is True

    def test_unregister(self):
        pm = PluginManager()
        pm.register(HookType.VALIDATE, lambda d: d, name="temp")
        assert pm.unregister("temp") == 1
        assert len(pm.list_plugins(HookType.VALIDATE)) == 0

    def test_list_plugins(self):
        pm = PluginManager()
        pm.register(HookType.PRE_LEARN, lambda d: d, name="p1", description="Test")
        plugins = pm.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["name"] == "p1"

    def test_stats(self):
        pm = PluginManager()
        pm.register(HookType.PRE_LEARN, lambda d: d)
        pm.register(HookType.POST_LEARN, lambda d: d)
        stats = pm.stats()
        assert stats["total_plugins"] == 2
        assert stats["active_plugins"] == 2

    def test_chain_transforms(self):
        pm = PluginManager()
        pm.register(HookType.TRANSFORM, lambda d: {**d, "step1": True}, priority=1)
        pm.register(HookType.TRANSFORM, lambda d: {**d, "step2": True}, priority=2)
        result = pm.apply(HookType.TRANSFORM, {})
        assert result["step1"] is True
        assert result["step2"] is True
