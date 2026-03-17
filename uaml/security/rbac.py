# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML RBAC — Role-Based Access Control for knowledge operations.

Defines roles, permissions, and access policies for multi-agent
and multi-user deployments.

Usage:
    from uaml.security.rbac import AccessControl, Role, Permission

    ac = AccessControl()
    ac.add_role("reader", permissions=[Permission.READ, Permission.SEARCH])
    ac.add_role("writer", permissions=[Permission.READ, Permission.SEARCH, Permission.WRITE])
    ac.assign_role("agent-cyril", "writer")
    ac.check("agent-cyril", Permission.WRITE)  # True
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class Permission(enum.Enum):
    """Available permissions."""
    READ = "read"
    WRITE = "write"
    SEARCH = "search"
    DELETE = "delete"
    EXPORT = "export"
    ADMIN = "admin"
    PURGE = "purge"
    SHARE = "share"
    AUDIT_READ = "audit_read"
    AUDIT_WRITE = "audit_write"


# Predefined role templates
ROLE_TEMPLATES = {
    "viewer": {Permission.READ, Permission.SEARCH},
    "editor": {Permission.READ, Permission.SEARCH, Permission.WRITE},
    "manager": {Permission.READ, Permission.SEARCH, Permission.WRITE, Permission.DELETE, Permission.EXPORT, Permission.SHARE},
    "admin": set(Permission),
    "auditor": {Permission.READ, Permission.SEARCH, Permission.AUDIT_READ, Permission.EXPORT},
}


@dataclass
class Role:
    """A named role with permissions."""
    name: str
    permissions: set[Permission] = field(default_factory=set)
    description: str = ""


class AccessControl:
    """Role-based access control for UAML operations."""

    def __init__(self):
        self._roles: dict[str, Role] = {}
        self._assignments: dict[str, set[str]] = {}  # agent_id → set of role names

        # Load templates
        for name, perms in ROLE_TEMPLATES.items():
            self._roles[name] = Role(name=name, permissions=perms)

    def add_role(
        self,
        name: str,
        permissions: list[Permission],
        description: str = "",
    ) -> Role:
        """Create a custom role."""
        role = Role(name=name, permissions=set(permissions), description=description)
        self._roles[name] = role
        return role

    def remove_role(self, name: str) -> bool:
        """Remove a role (and unassign from all agents)."""
        if name not in self._roles:
            return False
        del self._roles[name]
        for agent_id in self._assignments:
            self._assignments[agent_id].discard(name)
        return True

    def assign_role(self, agent_id: str, role_name: str) -> bool:
        """Assign a role to an agent."""
        if role_name not in self._roles:
            return False
        self._assignments.setdefault(agent_id, set()).add(role_name)
        return True

    def revoke_role(self, agent_id: str, role_name: str) -> bool:
        """Revoke a role from an agent."""
        if agent_id in self._assignments:
            self._assignments[agent_id].discard(role_name)
            return True
        return False

    def get_permissions(self, agent_id: str) -> set[Permission]:
        """Get all permissions for an agent (union of all roles)."""
        roles = self._assignments.get(agent_id, set())
        perms = set()
        for role_name in roles:
            role = self._roles.get(role_name)
            if role:
                perms |= role.permissions
        return perms

    def check(self, agent_id: str, permission: Permission) -> bool:
        """Check if an agent has a specific permission."""
        return permission in self.get_permissions(agent_id)

    def check_any(self, agent_id: str, permissions: list[Permission]) -> bool:
        """Check if agent has ANY of the given permissions."""
        agent_perms = self.get_permissions(agent_id)
        return bool(agent_perms & set(permissions))

    def check_all(self, agent_id: str, permissions: list[Permission]) -> bool:
        """Check if agent has ALL of the given permissions."""
        agent_perms = self.get_permissions(agent_id)
        return set(permissions).issubset(agent_perms)

    def get_roles(self, agent_id: str) -> list[str]:
        """Get role names assigned to an agent."""
        return sorted(self._assignments.get(agent_id, set()))

    def list_roles(self) -> list[dict]:
        """List all defined roles."""
        return [
            {
                "name": r.name,
                "permissions": sorted(p.value for p in r.permissions),
                "description": r.description,
            }
            for r in self._roles.values()
        ]

    def list_agents(self) -> list[dict]:
        """List all agents with their roles."""
        return [
            {
                "agent_id": aid,
                "roles": sorted(roles),
                "permissions": sorted(p.value for p in self.get_permissions(aid)),
            }
            for aid, roles in self._assignments.items()
        ]

    def stats(self) -> dict:
        """Access control statistics."""
        return {
            "total_roles": len(self._roles),
            "total_agents": len(self._assignments),
            "role_usage": {
                name: sum(1 for roles in self._assignments.values() if name in roles)
                for name in self._roles
            },
        }
