# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Entity Extraction — lightweight NER for memory content.

Extracts named entities (people, orgs, URLs, emails, IPs, dates, versions,
file paths) from text using regex patterns. No ML dependencies required.

Usage:
    from uaml.reasoning.entities import EntityExtractor

    extractor = EntityExtractor()
    entities = extractor.extract("Meeting with John at Acme Corp on 2026-03-14")
    # [Entity(text="John", type="person"), Entity(text="Acme Corp", type="org"), ...]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Entity:
    """An extracted entity."""
    text: str
    entity_type: str
    start: int = 0
    end: int = 0
    confidence: float = 0.8

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


# Common patterns
PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
    "url": re.compile(r'https?://[^\s<>"\')\]]+'),
    "ip_address": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b'),
    "version": re.compile(r'\bv?\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?\b'),
    "date_iso": re.compile(r'\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?\b'),
    "file_path": re.compile(r'(?:/[a-zA-Z0-9._-]+){2,}(?:\.[a-zA-Z0-9]+)?'),
    "hex_hash": re.compile(r'\b[0-9a-f]{7,64}\b'),
    "python_import": re.compile(r'\bfrom\s+([\w.]+)\s+import\b'),
}

# Title-case words that are likely names (heuristic)
NAME_PATTERN = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b')

# Common non-name title words to filter
NON_NAMES = {
    "The", "This", "That", "These", "Those", "What", "When", "Where",
    "Which", "While", "With", "Without", "About", "After", "Before",
    "Between", "During", "From", "Into", "Through", "Under", "Until",
    "Upon", "Within", "Also", "Already", "Always", "Because", "Both",
    "Each", "Either", "Every", "However", "Instead", "Just", "Many",
    "Most", "Much", "Neither", "Never", "None", "Only", "Other",
    "Some", "Such", "Than", "Then", "There", "Therefore", "Though",
    "Very", "Well", "Yet", "True", "False", "None", "All", "Any",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
    "Note", "Warning", "Error", "Info", "Debug", "TODO", "FIXME",
    "See", "See Also", "Example", "Usage", "Args", "Returns", "Raises",
    "Community", "Enterprise", "Starter", "Pro", "Free",
}


class EntityExtractor:
    """Extract named entities from text using regex patterns."""

    def __init__(self, *, custom_patterns: Optional[dict[str, re.Pattern]] = None):
        self.patterns = {**PATTERNS}
        if custom_patterns:
            self.patterns.update(custom_patterns)

    def extract(self, text: str) -> list[Entity]:
        """Extract all entities from text."""
        entities: list[Entity] = []
        seen: set[tuple[str, str]] = set()

        # Pattern-based extraction
        for entity_type, pattern in self.patterns.items():
            if entity_type == "python_import":
                for m in pattern.finditer(text):
                    key = (m.group(1), "module")
                    if key not in seen:
                        seen.add(key)
                        entities.append(Entity(
                            text=m.group(1),
                            entity_type="module",
                            start=m.start(1),
                            end=m.end(1),
                            confidence=0.9,
                        ))
            else:
                for m in pattern.finditer(text):
                    key = (m.group(), entity_type)
                    if key not in seen:
                        seen.add(key)
                        entities.append(Entity(
                            text=m.group(),
                            entity_type=entity_type,
                            start=m.start(),
                            end=m.end(),
                            confidence=0.85,
                        ))

        # Name extraction (heuristic — lower confidence)
        for m in NAME_PATTERN.finditer(text):
            name = m.group(1)
            # Filter common non-names
            words = name.split()
            if any(w in NON_NAMES for w in words):
                continue
            # Skip if it's already captured as another type
            if any(name in e.text or e.text in name for e in entities):
                continue
            key = (name, "name")
            if key not in seen:
                seen.add(key)
                entities.append(Entity(
                    text=name,
                    entity_type="name",
                    start=m.start(),
                    end=m.end(),
                    confidence=0.5,  # Lower confidence for heuristic names
                ))

        return sorted(entities, key=lambda e: e.start)

    def extract_typed(self, text: str, entity_type: str) -> list[Entity]:
        """Extract only entities of a specific type."""
        return [e for e in self.extract(text) if e.entity_type == entity_type]

    def summarize(self, text: str) -> dict[str, list[str]]:
        """Extract and group entities by type."""
        result: dict[str, list[str]] = {}
        for entity in self.extract(text):
            result.setdefault(entity.entity_type, [])
            if entity.text not in result[entity.entity_type]:
                result[entity.entity_type].append(entity.text)
        return result


def extract_entities(text: str) -> list[Entity]:
    """Convenience function: extract entities from text."""
    return EntityExtractor().extract(text)
