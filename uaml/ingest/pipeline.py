# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Ingest Pipeline — multi-stage knowledge ingestion.

Processes raw input through validation, enrichment, dedup, and storage
stages with hooks for custom processing.

Usage:
    from uaml.ingest.pipeline import IngestPipeline

    pipeline = IngestPipeline(store)
    pipeline.add_stage("validate", validator_fn)
    result = pipeline.ingest("New knowledge about Python")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from uaml.core.store import MemoryStore


@dataclass
class IngestResult:
    """Result of ingestion."""
    success: bool
    entry_id: Optional[int] = None
    stages_passed: list[str] = field(default_factory=list)
    stages_failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class IngestItem:
    """Item being ingested through the pipeline."""
    content: str
    topic: str = ""
    confidence: float = 0.8
    data_layer: str = "knowledge"
    source_type: str = "manual"
    source_ref: str = ""
    tags: str = ""
    metadata: dict = field(default_factory=dict)
    rejected: bool = False
    reject_reason: str = ""


class IngestPipeline:
    """Multi-stage ingestion pipeline."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self._stages: list[tuple[str, Callable]] = []
        self._setup_defaults()

    def _setup_defaults(self):
        """Add default validation stage."""
        self.add_stage("length_check", self._check_length)

    def _check_length(self, item: IngestItem) -> IngestItem:
        if not item.content or len(item.content.strip()) < 3:
            item.rejected = True
            item.reject_reason = "Content too short (< 3 chars)"
        return item

    def add_stage(self, name: str, fn: Callable[[IngestItem], IngestItem]) -> None:
        """Add a processing stage."""
        self._stages.append((name, fn))

    def remove_stage(self, name: str) -> bool:
        """Remove a stage by name."""
        before = len(self._stages)
        self._stages = [(n, f) for n, f in self._stages if n != name]
        return len(self._stages) < before

    def ingest(
        self,
        content: str,
        *,
        topic: str = "",
        confidence: float = 0.8,
        data_layer: str = "knowledge",
        source_type: str = "manual",
        source_ref: str = "",
        tags: str = "",
    ) -> IngestResult:
        """Ingest a single item through the pipeline."""
        item = IngestItem(
            content=content,
            topic=topic,
            confidence=confidence,
            data_layer=data_layer,
            source_type=source_type,
            source_ref=source_ref,
            tags=tags,
        )

        result = IngestResult(success=False)

        for name, fn in self._stages:
            try:
                item = fn(item)
                if item.rejected:
                    result.stages_failed.append(name)
                    result.errors.append(f"{name}: {item.reject_reason}")
                    return result
                result.stages_passed.append(name)
            except Exception as e:
                result.stages_failed.append(name)
                result.errors.append(f"{name}: {str(e)}")
                return result

        # Store the item
        try:
            entry_id = self.store.learn(
                content=item.content,
                topic=item.topic,
                confidence=item.confidence,
                data_layer=item.data_layer,
                source_type=item.source_type,
            )
            result.success = True
            result.entry_id = entry_id
            result.metadata = item.metadata
        except Exception as e:
            result.errors.append(f"store: {str(e)}")

        return result

    def ingest_batch(self, items: list[dict]) -> list[IngestResult]:
        """Ingest multiple items."""
        return [self.ingest(**item) for item in items]

    def list_stages(self) -> list[str]:
        """List stage names in order."""
        return [name for name, _ in self._stages]
