"""Tests for UAML RBAC."""

from __future__ import annotations

import pytest

from uaml.security.rbac import AccessControl, Permission, ROLE_TEMPLATES


class TestAccessControl:
    def test_predefined_roles(self):
        ac = AccessControl()
        roles = ac.list_roles()
        names = [r["name"] for r in roles]
        assert "admin" in names
        assert "viewer" in names

    def test_assign_and_check(self):
        ac = AccessControl()
        ac.assign_role("cyril", "editor")
        assert ac.check("cyril", Permission.READ) is True
        assert ac.check("cyril", Permission.WRITE) is True
        assert ac.check("cyril", Permission.DELETE) is False

    def test_admin_has_all(self):
        ac = AccessControl()
        ac.assign_role("root", "admin")
        for perm in Permission:
            assert ac.check("root", perm) is True

    def test_viewer_limited(self):
        ac = AccessControl()
        ac.assign_role("guest", "viewer")
        assert ac.check("guest", Permission.READ) is True
        assert ac.check("guest", Permission.WRITE) is False
        assert ac.check("guest", Permission.DELETE) is False

    def test_multiple_roles(self):
        ac = AccessControl()
        ac.assign_role("agent", "viewer")
        ac.assign_role("agent", "auditor")
        # Should have union of permissions
        assert ac.check("agent", Permission.READ) is True
        assert ac.check("agent", Permission.AUDIT_READ) is True

    def test_custom_role(self):
        ac = AccessControl()
        ac.add_role("exporter", [Permission.READ, Permission.EXPORT], description="Export only")
        ac.assign_role("bot", "exporter")
        assert ac.check("bot", Permission.EXPORT) is True
        assert ac.check("bot", Permission.WRITE) is False

    def test_revoke_role(self):
        ac = AccessControl()
        ac.assign_role("agent", "admin")
        ac.revoke_role("agent", "admin")
        assert ac.check("agent", Permission.ADMIN) is False

    def test_check_any(self):
        ac = AccessControl()
        ac.assign_role("agent", "viewer")
        assert ac.check_any("agent", [Permission.READ, Permission.WRITE]) is True
        assert ac.check_any("agent", [Permission.WRITE, Permission.DELETE]) is False

    def test_check_all(self):
        ac = AccessControl()
        ac.assign_role("agent", "editor")
        assert ac.check_all("agent", [Permission.READ, Permission.WRITE]) is True
        assert ac.check_all("agent", [Permission.READ, Permission.DELETE]) is False

    def test_unassigned_agent(self):
        ac = AccessControl()
        assert ac.check("nobody", Permission.READ) is False

    def test_remove_role(self):
        ac = AccessControl()
        ac.add_role("temp", [Permission.READ])
        assert ac.remove_role("temp") is True
        assert ac.remove_role("nonexistent") is False

    def test_stats(self):
        ac = AccessControl()
        ac.assign_role("a", "viewer")
        ac.assign_role("b", "editor")
        stats = ac.stats()
        assert stats["total_agents"] == 2

    def test_list_agents(self):
        ac = AccessControl()
        ac.assign_role("cyril", "editor")
        agents = ac.list_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "cyril"
