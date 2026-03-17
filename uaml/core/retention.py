# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Retention Policies — automated knowledge lifecycle management.

Define rules for how long entries are kept, when they're archived,
and when they should be reviewed or purged.

Usage:
    from uaml.core.retention import RetentionManager, RetentionPolicy

    rm = RetentionManager(store)
    rm.add_policy(RetentionPolicy(
        name="archive_old", data_layer="operational",
        max_age_days=180, action="archive"
    ))
    report = rm.evaluate()
    rm.execute(dry_run=False)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class RetentionPolicy:
    """A retention rule for knowledge entries."""
    name: str
    action: str = "archive"  # archive, delete, flag_review, reduce_confidence
    max_age_days: int = 365
    data_layer: Optional[str] = None
    topic: Optional[str] = None
    min_confidence: float = 0.0
    max_confidence: float = 1.0
    description: str = ""
    enabled: bool = True


@dataclass
class RetentionAction:
    """A planned or executed retention action."""
    entry_id: int
    policy_name: str
    action: str
    reason: str
    topic: str = ""
    age_days: int = 0


class RetentionManager:
    """Manage knowledge retention lifecycle."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._policies: list[RetentionPolicy] = []

    def add_policy(self, policy: RetentionPolicy) -> None:
        """Add a retention policy."""
        self._policies.append(policy)

    def remove_policy(self, name: str) -> bool:
        """Remove a policy by name."""
        before = len(self._policies)
        self._policies = [p for p in self._policies if p.name != name]
        return len(self._policies) < before

    def evaluate(self) -> list[RetentionAction]:
        """Evaluate all policies and return planned actions (dry run)."""
        actions = []
        now = datetime.now(timezone.utc)

        for policy in self._policies:
            if not policy.enabled:
                continue

            cutoff = (now - timedelta(days=policy.max_age_days)).isoformat()

            where = ["(updated_at < ? OR (updated_at IS NULL AND created_at < ?))"]
            params: list = [cutoff, cutoff]

            where.append("confidence >= ? AND confidence <= ?")
            params.extend([policy.min_confidence, policy.max_confidence])

            if policy.data_layer:
                where.append("data_layer = ?")
                params.append(policy.data_layer)

            if policy.topic:
                where.append("topic LIKE ?")
                params.append(f"%{policy.topic}%")

            rows = self.store._conn.execute(
                f"""SELECT id, topic, created_at, updated_at
                    FROM knowledge
                    WHERE {' AND '.join(where)}""",
                params,
            ).fetchall()

            for r in rows:
                ts = r["updated_at"] or r["created_at"] or ""
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age = (now - dt).days
                except (ValueError, AttributeError):
                    age = policy.max_age_days + 1

                actions.append(RetentionAction(
                    entry_id=r["id"],
                    policy_name=policy.name,
                    action=policy.action,
                    reason=f"Age {age}d > {policy.max_age_days}d threshold",
                    topic=r["topic"] or "",
                    age_days=age,
                ))

        return actions

    def execute(self, *, dry_run: bool = True) -> dict:
        """Execute retention policies.

        Args:
            dry_run: If True, only report what would happen

        Returns:
            Summary with counts
        """
        actions = self.evaluate()
        result = {
            "dry_run": dry_run,
            "total_actions": len(actions),
            "by_action": {},
            "by_policy": {},
        }

        for a in actions:
            result["by_action"][a.action] = result["by_action"].get(a.action, 0) + 1
            result["by_policy"][a.policy_name] = result["by_policy"].get(a.policy_name, 0) + 1

        if dry_run:
            return result

        # Execute actions
        executed = 0
        for a in actions:
            try:
                if a.action == "delete":
                    self.store._conn.execute(
                        "DELETE FROM knowledge WHERE id = ?", (a.entry_id,)
                    )
                    executed += 1
                elif a.action == "archive":
                    self.store._conn.execute(
                        "UPDATE knowledge SET data_layer = 'archive' WHERE id = ?",
                        (a.entry_id,),
                    )
                    executed += 1
                elif a.action == "reduce_confidence":
                    self.store._conn.execute(
                        "UPDATE knowledge SET confidence = MAX(0.1, confidence * 0.5) WHERE id = ?",
                        (a.entry_id,),
                    )
                    executed += 1
                elif a.action == "flag_review":
                    self.store._conn.execute(
                        "UPDATE knowledge SET tags = tags || ',needs_review' WHERE id = ?",
                        (a.entry_id,),
                    )
                    executed += 1
            except Exception:
                pass

        self.store._conn.commit()
        result["executed"] = executed
        return result

    def list_policies(self) -> list[dict]:
        """List all retention policies."""
        return [
            {
                "name": p.name,
                "action": p.action,
                "max_age_days": p.max_age_days,
                "data_layer": p.data_layer,
                "enabled": p.enabled,
                "description": p.description,
            }
            for p in self._policies
        ]
