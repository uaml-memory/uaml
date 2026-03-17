# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Knowledge Templates — predefined entry structures.

Templates ensure consistent knowledge formatting across agents
and use cases. Each template defines required/optional fields
and defaults.

Usage:
    from uaml.core.templates import TemplateEngine

    engine = TemplateEngine()
    entry = engine.create("decision", decision="Use SQLite", reason="Simplicity")
    # Returns formatted content ready for store.learn()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Template:
    """A knowledge entry template."""
    name: str
    format_str: str
    required_fields: list[str]
    optional_fields: list[str] = field(default_factory=list)
    default_topic: str = ""
    default_tags: str = ""
    default_confidence: float = 0.8
    default_data_layer: str = "knowledge"
    description: str = ""


# Built-in templates
BUILTIN_TEMPLATES: dict[str, Template] = {
    "decision": Template(
        name="decision",
        format_str="**Decision:** {decision}\n**Reason:** {reason}\n**Context:** {context}",
        required_fields=["decision", "reason"],
        optional_fields=["context", "alternatives", "date"],
        default_topic="decision",
        default_tags="decision",
        default_confidence=0.9,
        description="Record a decision with reasoning",
    ),
    "fact": Template(
        name="fact",
        format_str="{content}",
        required_fields=["content"],
        optional_fields=["source", "verified"],
        default_topic="fact",
        default_confidence=0.8,
        description="A factual knowledge entry",
    ),
    "procedure": Template(
        name="procedure",
        format_str="**Procedure:** {title}\n**Steps:**\n{steps}\n**Notes:** {notes}",
        required_fields=["title", "steps"],
        optional_fields=["notes", "prerequisites"],
        default_topic="procedure",
        default_tags="procedure,howto",
        default_confidence=0.85,
        default_data_layer="operational",
        description="Step-by-step procedure",
    ),
    "lesson": Template(
        name="lesson",
        format_str="**Lesson:** {title}\n**What happened:** {what}\n**What we learned:** {learned}\n**Action:** {action}",
        required_fields=["title", "what", "learned"],
        optional_fields=["action", "category"],
        default_topic="lesson-learned",
        default_tags="lesson",
        default_confidence=0.85,
        description="Lesson learned from an incident or experience",
    ),
    "contact": Template(
        name="contact",
        format_str="**Name:** {name}\n**Role:** {role}\n**Contact:** {contact}\n**Notes:** {notes}",
        required_fields=["name"],
        optional_fields=["role", "contact", "notes", "organization"],
        default_topic="contact",
        default_tags="contact,person",
        default_data_layer="identity",
        default_confidence=0.95,
        description="Contact information",
    ),
    "config": Template(
        name="config",
        format_str="**System:** {system}\n**Setting:** {setting} = {value}\n**Reason:** {reason}",
        required_fields=["system", "setting", "value"],
        optional_fields=["reason", "previous_value"],
        default_topic="configuration",
        default_tags="config,infrastructure",
        default_data_layer="operational",
        default_confidence=0.9,
        description="System configuration record",
    ),
    "meeting": Template(
        name="meeting",
        format_str="**Meeting:** {title}\n**Date:** {date}\n**Participants:** {participants}\n**Summary:** {summary}\n**Actions:** {actions}",
        required_fields=["title", "summary"],
        optional_fields=["date", "participants", "actions", "decisions"],
        default_topic="meeting",
        default_tags="meeting",
        default_confidence=0.85,
        description="Meeting notes and actions",
    ),
}


class TemplateEngine:
    """Create knowledge entries from templates."""

    def __init__(self):
        self._templates: dict[str, Template] = {**BUILTIN_TEMPLATES}

    def register(self, template: Template) -> None:
        """Register a custom template."""
        self._templates[template.name] = template

    def create(self, template_name: str, **kwargs) -> dict:
        """Create a knowledge entry from a template.

        Args:
            template_name: Name of the template
            **kwargs: Template field values

        Returns:
            Dict ready for store.learn() with content, topic, tags, etc.
        """
        template = self._templates.get(template_name)
        if not template:
            raise ValueError(f"Unknown template: {template_name}")

        # Check required fields
        missing = [f for f in template.required_fields if f not in kwargs]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # Fill defaults for optional fields
        for f in template.optional_fields:
            if f not in kwargs:
                kwargs[f] = ""

        # Format content
        content = template.format_str.format(**kwargs)

        return {
            "content": content,
            "topic": kwargs.get("_topic", template.default_topic),
            "tags": kwargs.get("_tags", template.default_tags),
            "confidence": kwargs.get("_confidence", template.default_confidence),
            "data_layer": kwargs.get("_data_layer", template.default_data_layer),
        }

    def list_templates(self) -> list[dict]:
        """List available templates."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "required": t.required_fields,
                "optional": t.optional_fields,
            }
            for t in self._templates.values()
        ]

    def get_template(self, name: str) -> Optional[Template]:
        """Get a template by name."""
        return self._templates.get(name)

    def validate(self, template_name: str, **kwargs) -> list[str]:
        """Validate fields without creating. Returns list of errors."""
        template = self._templates.get(template_name)
        if not template:
            return [f"Unknown template: {template_name}"]

        errors = []
        for f in template.required_fields:
            if f not in kwargs or not kwargs[f]:
                errors.append(f"Missing required field: {f}")

        return errors
