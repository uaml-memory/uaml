# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Ingestors — pluggable data ingestion pipeline.

Ingestors transform external data sources into UAML knowledge entries.
Each ingestor handles a specific format and knows how to extract
meaningful content with proper metadata.

Usage:
    from uaml.ingest import ChatIngestor, WebIngestor, MarkdownIngestor

    ingestor = ChatIngestor(store)
    stats = ingestor.ingest("session.jsonl")

Plugin system:
    from uaml.ingest import IngestRegistry, BaseIngestor

    # Register custom ingestor
    @IngestRegistry.register("csv")
    class CsvIngestor(BaseIngestor):
        source_type = "csv"
        def ingest(self, source, **kwargs): ...
        def can_handle(self, source): return str(source).endswith(".csv")

    # Auto-detect and ingest
    stats = IngestRegistry.auto_ingest(store, "data.csv")

    # List available ingestors
    IngestRegistry.list()  # → {"chat": ChatIngestor, "markdown": MarkdownIngestor, ...}
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Type

from uaml.ingest.base import BaseIngestor, IngestStats
from uaml.ingest.chat import ChatIngestor
from uaml.ingest.markdown import MarkdownIngestor
from uaml.ingest.search import SearchIngestor
from uaml.ingest.web import WebIngestor


class IngestRegistry:
    """Central registry for ingestor plugins.

    Built-in ingestors (chat, markdown, web) are registered automatically.
    Third-party ingestors can register via @IngestRegistry.register("name")
    or IngestRegistry.register_class("name", MyIngestor).
    """

    _registry: dict[str, Type[BaseIngestor]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register an ingestor class.

        Usage:
            @IngestRegistry.register("csv")
            class CsvIngestor(BaseIngestor): ...
        """
        def decorator(ingestor_cls: Type[BaseIngestor]):
            cls._registry[name] = ingestor_cls
            return ingestor_cls
        return decorator

    @classmethod
    def register_class(cls, name: str, ingestor_cls: Type[BaseIngestor]) -> None:
        """Register an ingestor class programmatically."""
        cls._registry[name] = ingestor_cls

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseIngestor]]:
        """Get an ingestor class by name."""
        return cls._registry.get(name)

    @classmethod
    def list(cls) -> dict[str, Type[BaseIngestor]]:
        """List all registered ingestors."""
        return dict(cls._registry)

    @classmethod
    def detect(cls, source: str | Path) -> Optional[str]:
        """Auto-detect which ingestor can handle the given source.

        Returns the ingestor name, or None if no match.
        Uses suffix/URL pattern matching for built-in types,
        then falls back to can_handle() on registered plugins.
        """
        source_str = str(source)
        path = Path(source_str) if not source_str.startswith(("http://", "https://")) else None

        # Built-in detection by extension/pattern
        if path:
            suffix = path.suffix.lower()
            ext_map = {
                ".jsonl": "chat",
                ".md": "markdown",
                ".markdown": "markdown",
                ".html": "web",
                ".htm": "web",
                ".txt": "web",  # WebIngestor handles plain text too
            }
            if suffix in ext_map and ext_map[suffix] in cls._registry:
                return ext_map[suffix]

        # URL detection
        if source_str.startswith(("http://", "https://")) and "web" in cls._registry:
            return "web"

        # Fallback: try can_handle on all registered (for custom plugins)
        for name, ingestor_cls in cls._registry.items():
            try:
                instance = object.__new__(ingestor_cls)
                if hasattr(instance, 'can_handle') and instance.can_handle(source):
                    return name
            except Exception:
                continue
        return None

    @classmethod
    def auto_ingest(
        cls,
        store,
        source: str | Path,
        **kwargs,
    ) -> IngestStats:
        """Auto-detect source type and ingest.

        Raises ValueError if no ingestor can handle the source.
        """
        name = cls.detect(source)
        if not name:
            raise ValueError(
                f"No ingestor can handle source: {source}. "
                f"Available: {', '.join(cls._registry.keys())}"
            )
        ingestor_cls = cls._registry[name]
        ingestor = ingestor_cls(store, **{k: v for k, v in kwargs.items()
                                          if k in ('default_topic', 'default_tags',
                                                    'default_project', 'default_client_ref',
                                                    'confidence', 'min_content_length')})
        ingest_kwargs = {k: v for k, v in kwargs.items()
                         if k not in ('default_topic', 'default_tags',
                                      'default_project', 'default_client_ref',
                                      'confidence', 'min_content_length')}
        return ingestor.ingest(source, **ingest_kwargs)


# Register built-in ingestors
IngestRegistry.register_class("chat", ChatIngestor)
IngestRegistry.register_class("markdown", MarkdownIngestor)
IngestRegistry.register_class("search", SearchIngestor)
IngestRegistry.register_class("web", WebIngestor)


__all__ = [
    "BaseIngestor",
    "IngestStats",
    "IngestRegistry",
    "ChatIngestor",
    "MarkdownIngestor",
    "SearchIngestor",
    "WebIngestor",
]
