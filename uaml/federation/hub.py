# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Federation Hub — coordinate memory sharing between agents.

Manages registered agents and handles share/sync requests
with access control and provenance tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


# Layers that can be shared (identity is NEVER shared)
SHAREABLE_LAYERS = {"knowledge", "team", "operational", "project"}


@dataclass
class ShareRequest:
    """A request to share entries between agents."""
    from_agent: str
    to_agent: str
    entry_ids: list[int]
    layer: str = "team"
    note: str = ""


@dataclass
class ShareResult:
    """Result of a share operation."""
    shared: int = 0
    skipped: int = 0
    denied: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.shared > 0 and not self.errors


class FederationHub:
    """Central hub for multi-agent memory federation."""

    def __init__(self):
        self._agents: dict[str, MemoryStore] = {}
        self._permissions: dict[str, set[str]] = {}  # agent → set of allowed peers
        self._share_log: list[dict] = []

    def register_agent(
        self,
        store: MemoryStore,
        agent_id: str,
        *,
        peers: Optional[list[str]] = None,
    ) -> None:
        """Register an agent's store with the federation.

        Args:
            store: Agent's MemoryStore
            agent_id: Agent identifier
            peers: List of agent IDs this agent can share with (None = all)
        """
        self._agents[agent_id] = store
        if peers is not None:
            self._permissions[agent_id] = set(peers)

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the federation."""
        self._agents.pop(agent_id, None)
        self._permissions.pop(agent_id, None)

    def list_agents(self) -> list[dict]:
        """List all registered agents."""
        return [
            {
                "agent_id": aid,
                "entries": store.stats().get("total_entries", 0) if hasattr(store, 'stats') else 0,
                "peers": list(self._permissions.get(aid, set())),
            }
            for aid, store in self._agents.items()
        ]

    def can_share(self, from_agent: str, to_agent: str) -> bool:
        """Check if sharing is permitted between two agents."""
        if from_agent not in self._agents or to_agent not in self._agents:
            return False
        if from_agent not in self._permissions:
            return True  # No restrictions = share with anyone
        return to_agent in self._permissions[from_agent]

    def share(self, request: ShareRequest) -> ShareResult:
        """Execute a share request — copy entries from one agent to another.

        Rules:
        - Identity layer entries are NEVER shared
        - Sharing requires permission (if configured)
        - Provenance is tracked (source_ref includes original agent)
        - Entries are deduplicated on the target
        """
        result = ShareResult()

        # Validate agents
        if request.from_agent not in self._agents:
            result.errors.append(f"Source agent '{request.from_agent}' not registered")
            return result
        if request.to_agent not in self._agents:
            result.errors.append(f"Target agent '{request.to_agent}' not registered")
            return result

        # Check permissions
        if not self.can_share(request.from_agent, request.to_agent):
            result.denied = len(request.entry_ids)
            result.errors.append(f"Sharing not permitted: {request.from_agent} → {request.to_agent}")
            return result

        # Validate layer
        if request.layer not in SHAREABLE_LAYERS:
            result.denied = len(request.entry_ids)
            result.errors.append(f"Layer '{request.layer}' cannot be shared")
            return result

        source = self._agents[request.from_agent]
        target = self._agents[request.to_agent]

        for entry_id in request.entry_ids:
            try:
                # Read from source
                row = source._conn.execute(
                    "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
                ).fetchone()

                if not row:
                    result.skipped += 1
                    continue

                entry = dict(row)

                # Never share identity
                if entry.get("data_layer") == "identity":
                    result.denied += 1
                    continue

                # Override layer if specified
                data_layer = request.layer or entry.get("data_layer", "team")

                # Write to target with provenance
                target.learn(
                    entry.get("content", ""),
                    topic=entry.get("topic", ""),
                    summary=entry.get("summary", ""),
                    source_type="federation",
                    source_origin="derived",
                    source_ref=f"federation:{request.from_agent}:entry:{entry_id}",
                    tags=f"federated,from:{request.from_agent}",
                    confidence=entry.get("confidence", 0.5),
                    data_layer=data_layer,
                    dedup=True,
                )
                result.shared += 1

            except Exception as e:
                result.errors.append(f"entry:{entry_id}: {e}")

        # Log the share
        self._share_log.append({
            "from": request.from_agent,
            "to": request.to_agent,
            "entries": len(request.entry_ids),
            "shared": result.shared,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return result

    def share_log(self, limit: int = 20) -> list[dict]:
        """Get recent share operations."""
        return self._share_log[-limit:]

    def sync_layer(
        self,
        from_agent: str,
        to_agent: str,
        layer: str = "team",
        *,
        since: Optional[str] = None,
    ) -> ShareResult:
        """Sync all entries in a layer from one agent to another.

        Args:
            from_agent: Source agent ID
            to_agent: Target agent ID
            layer: Data layer to sync
            since: Only sync entries created/updated after this ISO timestamp
        """
        if from_agent not in self._agents:
            return ShareResult(errors=[f"Agent '{from_agent}' not registered"])

        source = self._agents[from_agent]

        where = "data_layer = ?"
        params: list = [layer]
        if since:
            where += " AND (created_at > ? OR updated_at > ?)"
            params.extend([since, since])

        rows = source._conn.execute(
            f"SELECT id FROM knowledge WHERE {where}",
            params,
        ).fetchall()

        entry_ids = [r["id"] for r in rows]

        if not entry_ids:
            return ShareResult()

        request = ShareRequest(
            from_agent=from_agent,
            to_agent=to_agent,
            entry_ids=entry_ids,
            layer=layer,
        )
        return self.share(request)
