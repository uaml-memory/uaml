# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""
UAML — Universal Agent Memory Layer

Persistent, temporal, ethical memory for AI agents.
Works with any framework: OpenClaw, LangChain, AutoGen, or your own.

Quick start:
    from uaml import MemoryStore

    store = MemoryStore("knowledge.db", agent_id="my-agent")
    store.learn("Python's GIL prevents true threading", topic="python")
    results = store.search("threading")
"""

__version__ = "1.0.0"

# Core
from uaml.core.store import MemoryStore, EthicsViolation
from uaml.core.models import KnowledgeEntry, Entity
from uaml.core.search import search, search_entities
from uaml.core.config import ConfigManager

# Ethics
from uaml.ethics.checker import EthicsChecker, EthicsRule, EthicsVerdict

__all__ = [
    # Core
    "MemoryStore", "KnowledgeEntry", "Entity", "ConfigManager",
    "search", "search_entities",
    # Ethics
    "EthicsChecker", "EthicsRule", "EthicsVerdict", "EthicsViolation",
]
