# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Base ingestor — abstract interface for all UAML ingestors.

Every ingestor inherits from BaseIngestor and implements:
- ingest(source) → IngestStats
- can_handle(source) → bool (optional, for auto-detection)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from uaml.core.store import MemoryStore


@dataclass
class IngestStats:
    """Statistics from an ingestion run."""

    source: str = ""
    source_type: str = ""
    entries_created: int = 0
    entries_skipped: int = 0  # dedup
    entries_rejected: int = 0  # ethics
    errors: int = 0
    details: dict = field(default_factory=dict)

    @property
    def total_processed(self) -> int:
        return self.entries_created + self.entries_skipped + self.entries_rejected + self.errors

    def __repr__(self) -> str:
        return (
            f"IngestStats(source={self.source!r}, created={self.entries_created}, "
            f"skipped={self.entries_skipped}, rejected={self.entries_rejected}, "
            f"errors={self.errors})"
        )


class BaseIngestor(ABC):
    """Abstract base class for all ingestors.

    Subclasses must implement `ingest()`.
    """

    # Override in subclass
    source_type: str = "manual"
    source_origin: str = "external"  # external, generated, derived, observed
    data_layer: str = "knowledge"  # identity, knowledge, team, operational, project

    def __init__(
        self,
        store: MemoryStore,
        *,
        default_topic: str = "",
        default_tags: str = "",
        default_project: Optional[str] = None,
        default_client_ref: Optional[str] = None,
        confidence: float = 0.8,
        min_content_length: int = 20,
    ):
        self.store = store
        self.default_topic = default_topic
        self.default_tags = default_tags
        self.default_project = default_project
        self.default_client_ref = default_client_ref
        self.confidence = confidence
        self.min_content_length = min_content_length

    @abstractmethod
    def ingest(self, source: str | Path, **kwargs) -> IngestStats:
        """Ingest data from a source. Returns statistics."""
        ...

    def can_handle(self, source: str | Path) -> bool:
        """Check if this ingestor can handle the given source.

        Override in subclass for auto-detection.
        """
        return False

    def _learn_entry(
        self,
        content: str,
        stats: IngestStats,
        *,
        topic: str = "",
        summary: str = "",
        source_ref: str = "",
        tags: str = "",
        confidence: Optional[float] = None,
        valid_from: Optional[str] = None,
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
        source_origin: Optional[str] = None,
        data_layer: Optional[str] = None,
    ) -> Optional[int]:
        """Helper: learn a single entry with error handling and stats tracking."""
        if len(content.strip()) < self.min_content_length:
            stats.entries_skipped += 1
            return None

        try:
            entry_id = self.store.learn(
                content,
                topic=topic or self.default_topic,
                summary=summary,
                source_type=self.source_type,
                source_ref=source_ref,
                tags=tags or self.default_tags,
                confidence=confidence or self.confidence,
                valid_from=valid_from,
                client_ref=client_ref or self.default_client_ref,
                project=project or self.default_project,
                source_origin=source_origin or self.source_origin,
                data_layer=data_layer or self.data_layer,
                dedup=True,
            )
            stats.entries_created += 1
            return entry_id
        except Exception as e:
            if "EthicsViolation" in type(e).__name__:
                stats.entries_rejected += 1
            else:
                stats.errors += 1
            return None
