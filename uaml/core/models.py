# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Data models for UAML knowledge entries and entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DataLayer(str, Enum):
    """5-layer data hierarchy (Pavel's architecture, 2026-03-05).

    Each layer has different storage, sharing, and access characteristics:
    - IDENTITY: Who am I? Personality, preferences, traits (RAM-tier, never shared)
    - KNOWLEDGE: What do I know? Skills, learned facts, environment (SSD-tier, export only)
    - TEAM: Shared experiences, research, studies, conclusions (shared with access control)
    - OPERATIONAL: Logs, configs, security, audit trails (shared, signed)
    - PROJECT: Project data, inputs, outputs, deliverables (centralized, largest volume)
    """
    IDENTITY = "identity"
    KNOWLEDGE = "knowledge"
    TEAM = "team"
    OPERATIONAL = "operational"
    PROJECT = "project"


class MemoryType(str, Enum):
    """5 memory types — cognitive architecture inspired by human memory.

    - EPISODIC: Events, experiences, conversations ("what happened")
    - SEMANTIC: Facts, concepts, definitions ("what I know")
    - PROCEDURAL: Skills, processes, how-to ("how to do it")
    - REASONING: Decisions, conclusions, logic chains ("why I decided")
    - ASSOCIATIVE: Cross-memory links, patterns, intuitions ("what relates")
    """
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    REASONING = "reasoning"
    ASSOCIATIVE = "associative"


class SourceOrigin(str, Enum):
    """Origin classification: where did this data come from?

    Distinguishes between externally acquired data vs. internally produced.
    """
    EXTERNAL = "external"      # Acquired from outside (web, API, documents, research)
    GENERATED = "generated"    # Produced by the agent (analyses, summaries, conclusions)
    DERIVED = "derived"        # Derived from other entries (aggregations, transformations)
    OBSERVED = "observed"      # Observed from environment (logs, configs, scans)


class LegalBasis(str, Enum):
    """GDPR Art. 6(1) — Legal basis for data processing.

    Every processing of personal data must have at least one legal basis.
    """
    CONSENT = "consent"                       # Art. 6(1)(a)
    CONTRACT = "contract"                     # Art. 6(1)(b)
    LEGAL_OBLIGATION = "legal_obligation"     # Art. 6(1)(c)
    VITAL_INTEREST = "vital_interest"         # Art. 6(1)(d)
    PUBLIC_TASK = "public_task"               # Art. 6(1)(e)
    LEGITIMATE_INTEREST = "legitimate_interest"  # Art. 6(1)(f)


class LegalBasis(str, Enum):
    """GDPR Art. 6 — legal basis for processing personal data."""
    CONSENT = "consent"                      # Art. 6(1)(a) — data subject gave consent
    CONTRACT = "contract"                    # Art. 6(1)(b) — necessary for contract
    LEGAL_OBLIGATION = "legal_obligation"    # Art. 6(1)(c) — legal obligation
    VITAL_INTEREST = "vital_interest"        # Art. 6(1)(d) — vital interests
    PUBLIC_TASK = "public_task"              # Art. 6(1)(e) — public interest
    LEGITIMATE_INTEREST = "legitimate_interest"  # Art. 6(1)(f) — legitimate interests


class TaskStatus(str, Enum):
    """Task lifecycle status."""
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ArtifactStatus(str, Enum):
    """Artifact/deliverable lifecycle status."""
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    FINAL = "final"
    DELIVERED = "delivered"
    ARCHIVED = "archived"


class EntityType(str, Enum):
    """POLE+O entity classification (neo4j-labs standard)."""
    PERSON = "person"
    OBJECT = "object"
    LOCATION = "location"
    EVENT = "event"
    ORGANIZATION = "organization"
    PROJECT = "project"  # UAML extension


class SourceType(str, Enum):
    """Classification of knowledge source."""
    CHAT = "chat"
    RESEARCH = "research"
    DOCUMENT = "document"
    WEB_PAGE = "web_page"
    VIDEO = "video"
    SCAN = "scan"
    API = "api"
    MANUAL = "manual"
    PRIVATE = "private"
    CODE = "code"


class AccessLevel(str, Enum):
    """Access control level for knowledge entries."""
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    CLIENT_CONFIDENTIAL = "client_confidential"


class TrustLevel(str, Enum):
    """Trust level for knowledge sources."""
    VERIFIED = "verified"
    PEER_REVIEWED = "peer_reviewed"
    UNVERIFIED = "unverified"


@dataclass
class KnowledgeEntry:
    """A single knowledge entry in the UAML memory store.

    Supports temporal validity (valid_from/valid_until) and provenance tracking.
    """
    content: str
    agent_id: str = "default"
    topic: str = ""
    summary: str = ""
    source_type: SourceType = SourceType.MANUAL
    source_ref: str = ""
    tags: str = ""
    confidence: float = 0.8
    access_level: AccessLevel = AccessLevel.INTERNAL
    trust_level: TrustLevel = TrustLevel.UNVERIFIED

    # Temporal fields
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    # Auto-populated
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Client isolation
    client_ref: Optional[str] = None
    project: Optional[str] = None

    # Data layer and origin (v0.2)
    data_layer: DataLayer = DataLayer.KNOWLEDGE
    source_origin: SourceOrigin = SourceOrigin.EXTERNAL


@dataclass
class Entity:
    """An extracted entity (POLE+O model)."""
    name: str
    entity_type: EntityType
    properties: dict = field(default_factory=dict)
    id: Optional[int] = None
    source_entry_id: Optional[int] = None


@dataclass
class SearchResult:
    """A search result with relevance scoring."""
    entry: KnowledgeEntry
    score: float = 0.0
    snippet: str = ""
    highlights: list[str] = field(default_factory=list)


@dataclass
class AgentIdentity:
    """Agent personality and procedural memory."""
    agent_id: str
    name: str = ""
    role: str = ""
    traits: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=dict)


@dataclass
class Task:
    """A task/TODO item managed within UAML.

    Tasks live in the PROJECT data layer and can be linked to
    knowledge entries, artifacts, entities, and other tasks.
    """
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    project: Optional[str] = None
    assigned_to: Optional[str] = None  # agent_id
    priority: int = 0  # 0=normal, 1=high, 2=urgent
    tags: str = ""
    due_date: Optional[str] = None
    parent_id: Optional[int] = None  # for subtasks
    client_ref: Optional[str] = None
    data_layer: DataLayer = DataLayer.PROJECT

    # Auto-populated
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class Artifact:
    """A file, deliverable, or produced output.

    Tracks the lifecycle of artifacts from creation to delivery.
    Links back to tasks, projects, and knowledge entries.
    """
    name: str
    artifact_type: str = "file"  # file, report, analysis, code, document, media
    path: Optional[str] = None  # file path or URL
    status: ArtifactStatus = ArtifactStatus.DRAFT
    source_origin: SourceOrigin = SourceOrigin.GENERATED
    project: Optional[str] = None
    task_id: Optional[int] = None
    client_ref: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None  # SHA-256
    data_layer: DataLayer = DataLayer.PROJECT

    # Auto-populated
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SourceLink:
    """Bidirectional link between knowledge entries and their sources.

    Enables provenance tracking: "this conclusion is based on these sources"
    and "these sources contributed to these conclusions".
    """
    source_id: int  # knowledge entry that IS the source
    target_id: int  # knowledge entry that USES the source
    link_type: str = "based_on"  # based_on, cites, derived_from, supersedes, contradicts
    confidence: float = 0.8
    notes: str = ""

    # Auto-populated
    id: Optional[int] = None
    created_at: Optional[str] = None
