# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Facade — single entry point for the full UAML stack.

Provides convenient access to all UAML capabilities through one object.
Modules are lazily initialized on first access.

Usage:
    from uaml.facade import UAML

    uaml = UAML("knowledge.db", agent_id="my-agent")

    # Core operations
    uaml.learn("Python's GIL prevents true threading", topic="python")
    results = uaml.search("threading")

    # Advanced features
    ctx = uaml.context("What about threading?", max_tokens=2000)
    score = uaml.score(entry_id=1)
    uaml.backup()

    # Analytics
    overview = uaml.overview()
    health = uaml.health_check()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from uaml.core.store import MemoryStore


class UAML:
    """Unified facade for all UAML capabilities.

    Lazily initializes sub-modules on first use to keep startup fast.
    """

    def __init__(self, db_path: str = "uaml.db", *, agent_id: str = "default"):
        self.store = MemoryStore(db_path, agent_id=agent_id)
        self._cache = {}

    def close(self):
        """Close the store connection."""
        self.store.close()

    # ── Core operations ──

    def learn(self, content: str, **kwargs) -> int:
        """Store new knowledge."""
        return self.store.learn(content, **kwargs)

    def search(self, query: str, **kwargs):
        """Search knowledge."""
        return self.store.search(query, **kwargs)

    def delete(self, entry_id: int) -> bool:
        """Delete an entry."""
        return self.store.delete_entry(entry_id)

    def stats(self) -> dict:
        """Get store statistics."""
        return self.store.stats()

    # ── Context building ──

    def context(self, query: str, **kwargs):
        """Build context window for LLM prompts."""
        return self._get("context_builder").build(query, **kwargs)

    # ── Focus Engine (intelligent recall) ──

    def focus_recall(self, query: str, **kwargs) -> dict:
        """Intelligent recall with Focus Engine — token budget, temporal decay, sensitivity.

        This is the recommended recall method for production use.
        Uses the configured FocusEngineConfig or falls back to conservative preset.

        Args:
            query: Search query
            focus_config: Optional FocusEngineConfig (default: conservative preset)
            model_context_window: Model's context window size (default: 128000)
            **kwargs: Additional search filters (agent_id, topic, project, client_ref)

        Returns:
            dict with 'records', 'token_report', 'decisions', 'total_selected', 'utilization_pct'
        """
        return self.store.focus_recall(query, **kwargs)

    def load_focus_config(self, path: str) -> "FocusEngineConfig":
        """Load Focus Engine configuration from file.

        Args:
            path: Path to YAML or JSON config file

        Returns:
            FocusEngineConfig object
        """
        from uaml.core.focus_config import load_focus_config
        return load_focus_config(path)

    def load_focus_preset(self, name: str = "conservative") -> "FocusEngineConfig":
        """Load a built-in Focus Engine preset.

        Args:
            name: Preset name — 'conservative' (default), 'standard', or 'research'

        Returns:
            FocusEngineConfig object
        """
        from uaml.core.focus_config import load_preset
        return load_preset(name)

    def save_focus_config(self, config, path: str, *, modified_by: str = "") -> None:
        """Save Focus Engine configuration to file.

        Args:
            config: FocusEngineConfig object
            path: Output path (.yaml/.yml or .json)
            modified_by: User identifier for audit trail
        """
        from uaml.core.focus_config import save_focus_config
        save_focus_config(config, path, modified_by=modified_by)

    def focus_param_specs(self) -> dict:
        """Get all Focus Engine parameter specifications.

        Returns specs grouped by section (input_filter, output_filter, agent_rules).
        Each spec has: type, default, min, max, description, certification_relevant.
        Useful for UI rendering and documentation.
        """
        from uaml.core.focus_config import get_all_param_specs
        specs = get_all_param_specs()
        result = {}
        for section, params in specs.items():
            result[section] = {
                name: {
                    "type": s.type,
                    "default": s.default,
                    "min": s.min_val,
                    "max": s.max_val,
                    "description": s.description,
                    "certification_relevant": s.certification_relevant,
                }
                for name, s in params.items()
            }
        return result

    # ── Scoring ──

    def score(self, entry_id: int):
        """Score a knowledge entry."""
        return self._get("scorer").score_entry(entry_id)

    def rank(self, **kwargs):
        """Rank entries by quality."""
        return self._get("scorer").rank_all(**kwargs)

    # ── Summarization ──

    def overview(self):
        """Get store overview."""
        return self._get("summarizer").store_overview()

    def topic_summary(self, topic: str, **kwargs):
        """Summarize a topic."""
        return self._get("summarizer").topic_summary(topic, **kwargs)

    # ── Backup ──

    def backup(self, **kwargs):
        """Create a backup."""
        return self._get("backup").create_backup(**kwargs)

    def verify_backup(self, path):
        """Verify a backup."""
        return self._get("backup").verify_backup(Path(path))

    # ── Health ──

    def health_check(self):
        """Run health check."""
        return self._get("health").quick_check()

    # ── Validation ──

    def validate(self, entry_id: int):
        """Validate an entry."""
        return self._get("validator").validate_entry(entry_id)

    def validate_all(self, **kwargs):
        """Validate all entries."""
        return self._get("validator").full_validation(**kwargs)

    # ── Sanitization ──

    def sanitize(self, text: str, **kwargs):
        """Sanitize text for PII."""
        return self._get("sanitizer").sanitize(text, **kwargs)

    # ── Tags ──

    def add_tags(self, entry_id: int, tags: list[str]):
        """Add tags to an entry."""
        return self._get("tags").add_tags(entry_id, tags)

    def tag_cloud(self, **kwargs):
        """Get tag frequency distribution."""
        return self._get("tags").tag_cloud(**kwargs)

    # ── Clustering ──

    def cluster(self, **kwargs):
        """Cluster entries by similarity."""
        return self._get("clusterer").cluster(**kwargs)

    # ── Conflicts ──

    def detect_conflicts(self, **kwargs):
        """Detect knowledge conflicts."""
        return self._get("conflicts").detect(**kwargs)

    # ── Search optimization ──

    def optimize_query(self, query: str):
        """Optimize a search query."""
        return self._get("optimizer").optimize(query)

    # ── Snapshots ──

    def snapshot(self, name: str):
        """Take a store snapshot."""
        return self._get("snapshots").take(name)

    def snapshot_diff(self, a: str, b: str):
        """Compare two snapshots."""
        return self._get("snapshots").diff(a, b)

    # ── Lazy module access ──

    def _get(self, name: str):
        """Lazily initialize and cache a sub-module."""
        if name not in self._cache:
            self._cache[name] = self._init_module(name)
        return self._cache[name]

    def _init_module(self, name: str):
        """Initialize a module by name."""
        if name == "context_builder":
            from uaml.reasoning.context import ContextBuilder
            return ContextBuilder(self.store)
        elif name == "scorer":
            from uaml.reasoning.scoring import KnowledgeScorer
            return KnowledgeScorer(self.store)
        elif name == "summarizer":
            from uaml.reasoning.summarizer import KnowledgeSummarizer
            return KnowledgeSummarizer(self.store)
        elif name == "backup":
            from uaml.io.backup import BackupManager
            return BackupManager(self.store)
        elif name == "health":
            from uaml.core.health import HealthChecker
            return HealthChecker(self.store)
        elif name == "validator":
            from uaml.core.validation import KnowledgeValidator
            return KnowledgeValidator(self.store)
        elif name == "sanitizer":
            from uaml.security.sanitizer import DataSanitizer
            return DataSanitizer()
        elif name == "tags":
            from uaml.core.tagging import TagManager
            return TagManager(self.store)
        elif name == "clusterer":
            from uaml.reasoning.clustering import KnowledgeClusterer
            return KnowledgeClusterer(self.store)
        elif name == "conflicts":
            from uaml.reasoning.conflicts import ConflictResolver
            return ConflictResolver(self.store)
        elif name == "optimizer":
            from uaml.reasoning.optimizer import QueryOptimizer
            return QueryOptimizer()
        elif name == "snapshots":
            from uaml.core.snapshot import SnapshotManager
            return SnapshotManager(self.store)
        else:
            raise ValueError(f"Unknown module: {name}")
