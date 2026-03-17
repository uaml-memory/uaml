# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Incident → Lesson Pipeline — automatic learning from failures.

Captures incidents (errors, anomalies, failures), analyzes root cause,
extracts lessons learned, and stores them as knowledge for future reference.

Architecture:
    1. Log incident (error, anomaly, unexpected behavior)
    2. Classify severity (info/warning/error/critical)
    3. Extract root cause and contributing factors
    4. Generate lesson/rule from the incident
    5. Store lesson in knowledge DB with high confidence
    6. Optionally create preventive task

Usage:
    from uaml.reasoning.incidents import IncidentPipeline

    pipeline = IncidentPipeline(store)
    incident = pipeline.log_incident(
        title="Spam loop in Discord",
        description="Agent generated 100+ messages in 20 minutes due to allowBots=true",
        severity="critical",
        category="operational",
        root_cause="allowBots config + failure loop + weak local model",
    )
    lesson = pipeline.extract_lesson(incident)
    # Lesson stored in knowledge DB automatically
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from uaml.core.store import MemoryStore


SEVERITY_LEVELS = {
    "info": 0,
    "warning": 1,
    "error": 2,
    "critical": 3,
}

CATEGORIES = [
    "operational",      # Infrastructure, deployment, services
    "security",         # Security incidents, unauthorized access
    "data",             # Data corruption, loss, leaks
    "performance",      # Slow queries, timeouts, resource exhaustion
    "communication",    # Agent communication failures, spam
    "logic",            # Wrong decisions, incorrect reasoning
    "integration",      # External system failures, API errors
]


@dataclass
class Incident:
    """Represents a recorded incident."""

    id: int = 0
    title: str = ""
    description: str = ""
    severity: str = "warning"  # info/warning/error/critical
    category: str = "operational"
    root_cause: str = ""
    contributing_factors: list[str] = field(default_factory=list)
    affected_systems: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    resolution: str = ""
    agent_id: str = ""
    project: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def severity_level(self) -> int:
        return SEVERITY_LEVELS.get(self.severity, 0)

    @property
    def fingerprint(self) -> str:
        """Unique fingerprint for deduplication."""
        key = f"{self.title}:{self.category}:{self.root_cause}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "category": self.category,
            "root_cause": self.root_cause,
            "contributing_factors": self.contributing_factors,
            "affected_systems": self.affected_systems,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "agent_id": self.agent_id,
            "project": self.project,
            "metadata": self.metadata,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Incident":
        return cls(
            id=d.get("id", 0),
            title=d.get("title", ""),
            description=d.get("description", ""),
            severity=d.get("severity", "warning"),
            category=d.get("category", "operational"),
            root_cause=d.get("root_cause", ""),
            contributing_factors=d.get("contributing_factors", []),
            affected_systems=d.get("affected_systems", []),
            timestamp=d.get("timestamp", time.time()),
            resolved=d.get("resolved", False),
            resolution=d.get("resolution", ""),
            agent_id=d.get("agent_id", ""),
            project=d.get("project", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Lesson:
    """A lesson extracted from an incident."""

    id: int = 0
    incident_id: int = 0
    title: str = ""
    description: str = ""
    rule: str = ""  # Actionable rule derived from the lesson
    category: str = "operational"
    severity: str = "warning"
    prevention: str = ""  # How to prevent recurrence
    detection: str = ""   # How to detect early
    confidence: float = 0.9
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "title": self.title,
            "description": self.description,
            "rule": self.rule,
            "category": self.category,
            "severity": self.severity,
            "prevention": self.prevention,
            "detection": self.detection,
            "confidence": self.confidence,
            "tags": self.tags,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Lesson":
        return cls(
            id=d.get("id", 0),
            incident_id=d.get("incident_id", 0),
            title=d.get("title", ""),
            description=d.get("description", ""),
            rule=d.get("rule", ""),
            category=d.get("category", "operational"),
            severity=d.get("severity", "warning"),
            prevention=d.get("prevention", ""),
            detection=d.get("detection", ""),
            confidence=d.get("confidence", 0.9),
            tags=d.get("tags", []),
            created_at=d.get("created_at", time.time()),
        )


class IncidentPipeline:
    """Pipeline for recording incidents and extracting lessons."""

    def __init__(self, store: Optional["MemoryStore"] = None):
        self.store = store
        self._incidents: list[Incident] = []
        self._lessons: list[Lesson] = []
        self._next_incident_id = 1
        self._next_lesson_id = 1

    def log_incident(
        self,
        title: str,
        description: str = "",
        severity: str = "warning",
        category: str = "operational",
        root_cause: str = "",
        contributing_factors: Optional[list[str]] = None,
        affected_systems: Optional[list[str]] = None,
        agent_id: str = "",
        project: str = "",
        resolution: str = "",
        metadata: Optional[dict] = None,
    ) -> Incident:
        """Record a new incident."""
        if severity not in SEVERITY_LEVELS:
            raise ValueError(f"Invalid severity: {severity}. Use: {list(SEVERITY_LEVELS.keys())}")

        incident = Incident(
            id=self._next_incident_id,
            title=title,
            description=description,
            severity=severity,
            category=category,
            root_cause=root_cause,
            contributing_factors=contributing_factors or [],
            affected_systems=affected_systems or [],
            agent_id=agent_id,
            project=project,
            resolution=resolution,
            resolved=bool(resolution),
            metadata=metadata or {},
        )
        self._incidents.append(incident)
        self._next_incident_id += 1

        # Store as knowledge if we have a store
        if self.store:
            content = self._incident_to_knowledge(incident)
            self.store.learn(
                content,
                topic="incident",
                data_layer="operational",
                project=project or None,
                confidence=0.95,
                source_type="incident",
                tags=f"incident,{severity},{category}",
            )

        return incident

    def extract_lesson(self, incident: Incident) -> Lesson:
        """Extract a lesson from an incident."""
        lesson = Lesson(
            id=self._next_lesson_id,
            incident_id=incident.id,
            title=f"Lesson from: {incident.title}",
            description=self._generate_lesson_description(incident),
            rule=self._generate_rule(incident),
            category=incident.category,
            severity=incident.severity,
            prevention=self._generate_prevention(incident),
            detection=self._generate_detection(incident),
            confidence=self._calculate_lesson_confidence(incident),
            tags=[incident.category, incident.severity, "lesson"],
        )
        self._lessons.append(lesson)
        self._next_lesson_id += 1

        # Store lesson as high-confidence knowledge
        if self.store:
            content = self._lesson_to_knowledge(lesson)
            self.store.learn(
                content,
                topic="lesson",
                data_layer="knowledge",
                confidence=lesson.confidence,
                source_type="lesson",
                tags=",".join(lesson.tags),
            )

        return lesson

    def resolve_incident(self, incident_id: int, resolution: str) -> Optional[Incident]:
        """Mark an incident as resolved."""
        for incident in self._incidents:
            if incident.id == incident_id:
                incident.resolved = True
                incident.resolution = resolution
                return incident
        return None

    def get_incidents(
        self,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        resolved: Optional[bool] = None,
    ) -> list[Incident]:
        """Query incidents with optional filters."""
        results = self._incidents[:]
        if severity:
            results = [i for i in results if i.severity == severity]
        if category:
            results = [i for i in results if i.category == category]
        if resolved is not None:
            results = [i for i in results if i.resolved == resolved]
        return results

    def get_lessons(self, category: Optional[str] = None) -> list[Lesson]:
        """Get extracted lessons."""
        if category:
            return [l for l in self._lessons if l.category == category]
        return self._lessons[:]

    def get_stats(self) -> dict:
        """Pipeline statistics."""
        by_severity = {}
        for i in self._incidents:
            by_severity[i.severity] = by_severity.get(i.severity, 0) + 1

        by_category = {}
        for i in self._incidents:
            by_category[i.category] = by_category.get(i.category, 0) + 1

        resolved = sum(1 for i in self._incidents if i.resolved)

        return {
            "total_incidents": len(self._incidents),
            "total_lessons": len(self._lessons),
            "resolved": resolved,
            "unresolved": len(self._incidents) - resolved,
            "by_severity": by_severity,
            "by_category": by_category,
        }

    def create_preventive_task(self, lesson: Lesson, assigned_to: str = "") -> Optional[int]:
        """Create a preventive task from a lesson."""
        if not self.store:
            return None

        title = f"[Prevention] {lesson.prevention or lesson.title}"
        task_id = self.store.create_task(
            title=title[:200],
            description=f"Derived from lesson #{lesson.id}: {lesson.description}",
            status="todo",
            project=lesson.category,
            assigned_to=assigned_to,
            priority=2 if lesson.severity in ("error", "critical") else 1,
            tags="prevention,lesson",
        )
        return task_id

    def get_rules(self, category: Optional[str] = None) -> list[dict]:
        """Get all actionable rules derived from lessons.

        Returns rules with their source lesson and incident context.
        Useful for building operational playbooks and pre-flight checks.
        """
        lessons = self.get_lessons(category=category)
        rules = []
        for lesson in lessons:
            if lesson.rule:
                rules.append({
                    "rule": lesson.rule,
                    "lesson_id": lesson.id,
                    "incident_id": lesson.incident_id,
                    "title": lesson.title,
                    "category": lesson.category,
                    "severity": lesson.severity,
                    "prevention": lesson.prevention,
                    "detection": lesson.detection,
                })
        return rules

    def check_rules(self, action: str, context: Optional[dict] = None) -> list[dict]:
        """Check an intended action against learned rules.

        Performs keyword-based matching of the action description against
        all stored rules. Returns matching rules as warnings.

        Args:
            action: Description of the intended action
            context: Optional context (category, project, etc.)

        Returns:
            List of matching rules with relevance info
        """
        rules = self.get_rules(
            category=context.get("category") if context else None
        )
        action_lower = action.lower()
        matches = []

        for rule in rules:
            rule_lower = rule["rule"].lower()
            title_lower = rule["title"].lower()

            # Simple keyword overlap scoring
            rule_words = set(rule_lower.split())
            action_words = set(action_lower.split())
            overlap = rule_words & action_words
            # Exclude common words
            overlap -= {"the", "a", "an", "is", "are", "was", "were", "be", "to",
                        "of", "in", "for", "on", "with", "at", "by", "from", "and",
                        "or", "not", "no", "should", "must", "do", "don't"}

            if len(overlap) >= 2 or any(w in action_lower for w in rule_lower.split() if len(w) > 4):
                matches.append({
                    **rule,
                    "matched_words": list(overlap),
                    "relevance": len(overlap) / max(len(rule_words), 1),
                })

        # Sort by relevance
        matches.sort(key=lambda m: m["relevance"], reverse=True)
        return matches

    # ── Internal helpers ─────────────────────────────────────────

    def _incident_to_knowledge(self, incident: Incident) -> str:
        """Convert incident to knowledge entry text."""
        parts = [f"INCIDENT [{incident.severity.upper()}]: {incident.title}"]
        if incident.description:
            parts.append(f"Description: {incident.description}")
        if incident.root_cause:
            parts.append(f"Root cause: {incident.root_cause}")
        if incident.contributing_factors:
            parts.append(f"Contributing factors: {', '.join(incident.contributing_factors)}")
        if incident.resolution:
            parts.append(f"Resolution: {incident.resolution}")
        return " | ".join(parts)

    def _lesson_to_knowledge(self, lesson: Lesson) -> str:
        """Convert lesson to knowledge entry text."""
        parts = [f"LESSON: {lesson.title}"]
        if lesson.rule:
            parts.append(f"Rule: {lesson.rule}")
        if lesson.prevention:
            parts.append(f"Prevention: {lesson.prevention}")
        if lesson.detection:
            parts.append(f"Detection: {lesson.detection}")
        return " | ".join(parts)

    def _generate_lesson_description(self, incident: Incident) -> str:
        """Generate lesson description from incident."""
        parts = []
        if incident.root_cause:
            parts.append(f"Root cause was: {incident.root_cause}.")
        if incident.contributing_factors:
            parts.append(f"Contributing factors: {', '.join(incident.contributing_factors)}.")
        if incident.resolution:
            parts.append(f"Resolved by: {incident.resolution}.")
        return " ".join(parts) if parts else f"Incident: {incident.description}"

    def _generate_rule(self, incident: Incident) -> str:
        """Generate an actionable rule from the incident."""
        if incident.resolution:
            return f"When encountering '{incident.category}' issues similar to '{incident.title}': {incident.resolution}"
        if incident.root_cause:
            return f"Avoid: {incident.root_cause}"
        return f"Monitor for: {incident.title}"

    def _generate_prevention(self, incident: Incident) -> str:
        """Generate prevention advice."""
        if incident.resolution:
            return f"Apply fix proactively: {incident.resolution}"
        if incident.root_cause:
            return f"Address root cause: {incident.root_cause}"
        return f"Monitor and alert on: {incident.title}"

    def _generate_detection(self, incident: Incident) -> str:
        """Generate early detection advice."""
        if incident.affected_systems:
            return f"Monitor: {', '.join(incident.affected_systems)}"
        return f"Watch for symptoms of: {incident.title}"

    def _calculate_lesson_confidence(self, incident: Incident) -> float:
        """Calculate confidence score for a lesson."""
        base = 0.7
        if incident.root_cause:
            base += 0.1
        if incident.resolution:
            base += 0.1
        if incident.contributing_factors:
            base += 0.05
        if incident.severity in ("error", "critical"):
            base += 0.05
        return min(1.0, base)
