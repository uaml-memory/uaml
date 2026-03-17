# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Focus Engine Configuration — input/output filter rules.

Provides typed, validated configuration for the Focus Engine:
- Input filter rules (data → Neo4j)
- Output filter rules (Neo4j → agent context)
- Agent behavior rules
- Default presets (conservative, standard, research)

Configuration is human-editable only. AI agents CANNOT read or modify
these settings (enforced at API/auth layer).

Designed for certifiability: every parameter has defined type, range,
default, and validation. All changes are auditable.

© 2026 GLG, a.s. — UAML Focus Engine
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CategoryAction(str, Enum):
    """Action for a data category."""
    ALLOW = "allow"
    ENCRYPT = "encrypt"
    REQUIRE_CONSENT = "require_consent"
    DENY = "deny"


class PresetName(str, Enum):
    """Built-in preset names."""
    CONSERVATIVE = "conservative"
    STANDARD = "standard"
    RESEARCH = "research"


# ---------------------------------------------------------------------------
# Parameter definitions with validation ranges
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSpec:
    """Specification for a single configurable parameter.

    Used for validation, UI rendering, and documentation generation.
    """
    name: str
    type: str  # "float", "int", "bool", "str"
    default: Any
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    description: str = ""
    unit: str = ""
    certification_relevant: bool = False

    def validate(self, value: Any) -> tuple[bool, str]:
        """Validate a value against this spec.

        Returns:
            (is_valid, error_message)
        """
        if self.type == "bool":
            if not isinstance(value, bool):
                return False, f"{self.name}: expected bool, got {type(value).__name__}"
            return True, ""

        if self.type == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"{self.name}: expected int, got {type(value).__name__}"
        elif self.type == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"{self.name}: expected float, got {type(value).__name__}"

        if self.min_val is not None and value < self.min_val:
            return False, f"{self.name}: {value} < minimum {self.min_val}"
        if self.max_val is not None and value > self.max_val:
            return False, f"{self.name}: {value} > maximum {self.max_val}"

        return True, ""


# Input filter parameter specifications
INPUT_FILTER_SPECS: dict[str, ParamSpec] = {
    "min_relevance_score": ParamSpec(
        name="min_relevance_score",
        type="float", default=0.7, min_val=0.0, max_val=1.0,
        description="Minimum relevance score for data to be stored",
        certification_relevant=True,
    ),
    "dedup_threshold": ParamSpec(
        name="dedup_threshold",
        type="float", default=0.95, min_val=0.8, max_val=1.0,
        description="Cosine similarity threshold — above this, record is rejected as duplicate",
    ),
    "max_source_age_days": ParamSpec(
        name="max_source_age_days",
        type="int", default=365, min_val=1, max_val=100000,
        description="Reject data from sources older than X days (0 = unlimited)",
    ),
    "ttl_days": ParamSpec(
        name="ttl_days",
        type="int", default=730, min_val=30, max_val=100000,
        description="Time-to-live for stored records in days",
        certification_relevant=True,
    ),
    "max_entry_tokens": ParamSpec(
        name="max_entry_tokens",
        type="int", default=2000, min_val=100, max_val=10000,
        description="Maximum tokens per single record",
    ),
    "min_entry_length": ParamSpec(
        name="min_entry_length",
        type="int", default=10, min_val=1, max_val=1000,
        description="Minimum character length — shorter records are rejected",
    ),
    "require_classification": ParamSpec(
        name="require_classification",
        type="bool", default=True,
        description="Every record must have at least one category tag",
        certification_relevant=True,
    ),
    "pii_detection": ParamSpec(
        name="pii_detection",
        type="bool", default=True,
        description="NER/regex scan to auto-tag sensitive PII data",
        certification_relevant=True,
    ),
    "rate_limit_per_min": ParamSpec(
        name="rate_limit_per_min",
        type="int", default=100, min_val=1, max_val=10000,
        description="Maximum write operations per minute",
    ),
}

# Output filter parameter specifications
OUTPUT_FILTER_SPECS: dict[str, ParamSpec] = {
    "token_budget_per_query": ParamSpec(
        name="token_budget_per_query",
        type="int", default=2000, min_val=200, max_val=32000,
        description="Maximum tokens for recall per request",
        unit="tokens",
        certification_relevant=True,
    ),
    "min_relevance_score": ParamSpec(
        name="min_relevance_score",
        type="float", default=0.3, min_val=0.0, max_val=1.0,
        description="Below this relevance score, data is not injected into context",
    ),
    "max_records": ParamSpec(
        name="max_records",
        type="int", default=10, min_val=1, max_val=50,
        description="Maximum number of records returned per recall",
    ),
    "temporal_decay_factor": ParamSpec(
        name="temporal_decay_factor",
        type="float", default=0.5, min_val=0.0, max_val=1.0,
        description="Penalization factor for data age",
    ),
    "temporal_decay_halflife_days": ParamSpec(
        name="temporal_decay_halflife_days",
        type="int", default=30, min_val=1, max_val=365,
        description="Half-life for temporal decay in days",
    ),
    "dedup_similarity": ParamSpec(
        name="dedup_similarity",
        type="float", default=0.85, min_val=0.5, max_val=1.0,
        description="Merge similar results above this cosine similarity threshold",
    ),
    "recall_tier": ParamSpec(
        name="recall_tier",
        type="int", default=1, min_val=1, max_val=3,
        description="1=summaries only, 2=summaries+details, 3=full raw data",
        certification_relevant=True,
    ),
    "sensitivity_threshold": ParamSpec(
        name="sensitivity_threshold",
        type="int", default=3, min_val=1, max_val=5,
        description="Records with sensitivity > X require explicit permission",
        certification_relevant=True,
    ),
    "compress_above_tokens": ParamSpec(
        name="compress_above_tokens",
        type="int", default=500, min_val=100, max_val=5000,
        description="Summarize records larger than X tokens before injection",
    ),
    "summary_preference": ParamSpec(
        name="summary_preference",
        type="float", default=0.8, min_val=0.0, max_val=1.0,
        description="Weight toward summaries (1.0) vs raw data (0.0)",
    ),
    "max_context_percentage": ParamSpec(
        name="max_context_percentage",
        type="int", default=30, min_val=5, max_val=80,
        description="Maximum percentage of model context window for recall",
        certification_relevant=True,
    ),
}

# Agent rules parameter specifications
AGENT_RULES_SPECS: dict[str, ParamSpec] = {
    "prefer_summaries_first": ParamSpec(
        name="prefer_summaries_first",
        type="bool", default=True,
        description="Tiered recall: summaries → details → raw",
    ),
    "lazy_loading": ParamSpec(
        name="lazy_loading",
        type="bool", default=True,
        description="Start with minimum context, request more only when needed",
    ),
    "report_token_usage": ParamSpec(
        name="report_token_usage",
        type="bool", default=True,
        description="Agent reports how many tokens recall consumed",
        certification_relevant=True,
    ),
    "budget_aware": ParamSpec(
        name="budget_aware",
        type="bool", default=True,
        description="Agent knows and respects token budget limits",
    ),
    "deduplicate_context": ParamSpec(
        name="deduplicate_context",
        type="bool", default=True,
        description="Never send same information twice in context",
    ),
    "prefer_fresh_data": ParamSpec(
        name="prefer_fresh_data",
        type="bool", default=True,
        description="Newer data gets higher priority in recall",
    ),
    "never_expose_rules": ParamSpec(
        name="never_expose_rules",
        type="bool", default=True,
        description="Agent must not reveal filter/rule configuration",
        certification_relevant=True,
    ),
    "never_bypass_filter": ParamSpec(
        name="never_bypass_filter",
        type="bool", default=True,
        description="Agent cannot circumvent input or output filters",
        certification_relevant=True,
    ),
    "log_all_recalls": ParamSpec(
        name="log_all_recalls",
        type="bool", default=True,
        description="Log every memory access for audit trail",
        certification_relevant=True,
    ),
}

# Default category settings
DEFAULT_CATEGORIES: dict[str, str] = {
    "personal": "require_consent",
    "financial": "encrypt",
    "health": "deny",
    "company": "allow",
    "public": "allow",
    "communication": "encrypt",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class InputFilterConfig:
    """Input filter configuration (data → Neo4j)."""
    min_relevance_score: float = 0.7
    dedup_threshold: float = 0.95
    max_source_age_days: int = 365
    ttl_days: int = 730
    max_entry_tokens: int = 2000
    min_entry_length: int = 10
    require_classification: bool = True
    pii_detection: bool = True
    rate_limit_per_min: int = 100
    categories: dict[str, str] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CATEGORIES))


@dataclass
class OutputFilterConfig:
    """Output filter / Focus Engine configuration (Neo4j → context)."""
    token_budget_per_query: int = 2000
    min_relevance_score: float = 0.3
    max_records: int = 10
    temporal_decay_factor: float = 0.5
    temporal_decay_halflife_days: int = 30
    dedup_similarity: float = 0.85
    recall_tier: int = 1
    sensitivity_threshold: int = 3
    compress_above_tokens: int = 500
    summary_preference: float = 0.8
    max_context_percentage: int = 30


@dataclass
class AgentRulesConfig:
    """Agent behavior rules (read-only for agents)."""
    prefer_summaries_first: bool = True
    lazy_loading: bool = True
    report_token_usage: bool = True
    budget_aware: bool = True
    deduplicate_context: bool = True
    prefer_fresh_data: bool = True
    never_expose_rules: bool = True
    never_bypass_filter: bool = True
    log_all_recalls: bool = True


@dataclass
class FocusEngineConfig:
    """Complete Focus Engine configuration.

    This is the top-level config object that contains all sub-configs.
    Human-editable only — AI agents receive read-only copies via the
    agent_rules section.
    """
    version: str = "1.0"
    last_modified: str = ""
    modified_by: str = ""
    input_filter: InputFilterConfig = field(default_factory=InputFilterConfig)
    output_filter: OutputFilterConfig = field(default_factory=OutputFilterConfig)
    agent_rules: AgentRulesConfig = field(default_factory=AgentRulesConfig)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)

    def validate(self) -> list[str]:
        """Validate all parameters against their specs.

        Returns:
            List of validation error messages (empty = valid).
        """
        errors = []

        for name, spec in INPUT_FILTER_SPECS.items():
            value = getattr(self.input_filter, name, None)
            if value is not None:
                valid, msg = spec.validate(value)
                if not valid:
                    errors.append(f"input_filter.{msg}")

        for name, spec in OUTPUT_FILTER_SPECS.items():
            value = getattr(self.output_filter, name, None)
            if value is not None:
                valid, msg = spec.validate(value)
                if not valid:
                    errors.append(f"output_filter.{msg}")

        for name, spec in AGENT_RULES_SPECS.items():
            value = getattr(self.agent_rules, name, None)
            if value is not None:
                valid, msg = spec.validate(value)
                if not valid:
                    errors.append(f"agent_rules.{msg}")

        # Validate categories
        valid_actions = {a.value for a in CategoryAction}
        for cat, action in self.input_filter.categories.items():
            if action not in valid_actions:
                errors.append(
                    f"input_filter.categories.{cat}: "
                    f"invalid action '{action}', must be one of {valid_actions}"
                )

        return errors

    def certification_params(self) -> dict[str, Any]:
        """Return only parameters relevant for certification/audit.

        These parameters affect data protection, access control,
        and compliance behavior.
        """
        result = {}
        for section_name, specs in [
            ("input_filter", INPUT_FILTER_SPECS),
            ("output_filter", OUTPUT_FILTER_SPECS),
            ("agent_rules", AGENT_RULES_SPECS),
        ]:
            section_obj = getattr(self, section_name)
            for name, spec in specs.items():
                if spec.certification_relevant:
                    result[f"{section_name}.{name}"] = getattr(section_obj, name)
        return result


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

PRESETS: dict[str, FocusEngineConfig] = {
    "conservative": FocusEngineConfig(
        input_filter=InputFilterConfig(
            min_relevance_score=0.7,
            require_classification=True,
            pii_detection=True,
            categories={
                "personal": "require_consent",
                "financial": "encrypt",
                "health": "deny",
                "company": "allow",
                "public": "allow",
                "communication": "encrypt",
            },
        ),
        output_filter=OutputFilterConfig(
            token_budget_per_query=1500,
            min_relevance_score=0.5,
            recall_tier=1,
            max_records=5,
        ),
    ),
    "standard": FocusEngineConfig(
        input_filter=InputFilterConfig(
            min_relevance_score=0.5,
            require_classification=True,
            pii_detection=True,
            categories={
                "personal": "require_consent",
                "financial": "encrypt",
                "health": "deny",
                "company": "allow",
                "public": "allow",
                "communication": "allow",
            },
        ),
        output_filter=OutputFilterConfig(
            token_budget_per_query=3000,
            min_relevance_score=0.3,
            recall_tier=2,
            max_records=10,
        ),
    ),
    "research": FocusEngineConfig(
        input_filter=InputFilterConfig(
            min_relevance_score=0.3,
            require_classification=False,
            pii_detection=True,
            categories={
                "personal": "require_consent",
                "financial": "encrypt",
                "health": "require_consent",
                "company": "allow",
                "public": "allow",
                "communication": "allow",
            },
        ),
        output_filter=OutputFilterConfig(
            token_budget_per_query=8000,
            min_relevance_score=0.2,
            recall_tier=3,
            max_records=25,
        ),
    ),
}


# ---------------------------------------------------------------------------
# Loader / Saver
# ---------------------------------------------------------------------------

def _dict_to_config(data: dict) -> FocusEngineConfig:
    """Convert a dictionary to FocusEngineConfig.

    Handles nested structures and ignores unknown keys gracefully.
    """
    config = FocusEngineConfig()

    if "version" in data:
        config.version = str(data["version"])
    if "last_modified" in data:
        config.last_modified = str(data["last_modified"])
    if "modified_by" in data:
        config.modified_by = str(data["modified_by"])

    if "input_filter" in data and isinstance(data["input_filter"], dict):
        ifd = data["input_filter"]
        for key in INPUT_FILTER_SPECS:
            if key in ifd:
                setattr(config.input_filter, key, ifd[key])
        if "categories" in ifd and isinstance(ifd["categories"], dict):
            config.input_filter.categories = dict(ifd["categories"])

    if "output_filter" in data and isinstance(data["output_filter"], dict):
        ofd = data["output_filter"]
        for key in OUTPUT_FILTER_SPECS:
            if key in ofd:
                setattr(config.output_filter, key, ofd[key])

    if "agent_rules" in data and isinstance(data["agent_rules"], dict):
        ard = data["agent_rules"]
        for key in AGENT_RULES_SPECS:
            if key in ard:
                setattr(config.agent_rules, key, ard[key])

    return config


def load_focus_config(path: str | Path) -> FocusEngineConfig:
    """Load Focus Engine configuration from YAML or JSON file.

    Args:
        path: Path to config file (.yaml/.yml or .json)

    Returns:
        Validated FocusEngineConfig

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Focus config not found: {p}")

    text = p.read_text(encoding="utf-8")

    if p.suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required for YAML config files. "
                "Install with: pip install pyyaml"
            )
        data = yaml.safe_load(text) or {}
    elif p.suffix == ".json":
        data = json.loads(text)
    else:
        # Try YAML first, fall back to JSON
        try:
            if HAS_YAML:
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text)
        except Exception:
            raise ValueError(f"Cannot parse {p}: unsupported format")

    config = _dict_to_config(data)
    errors = config.validate()
    if errors:
        raise ValueError(
            f"Focus config validation failed:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    return config


def save_focus_config(
    config: FocusEngineConfig,
    path: str | Path,
    *,
    modified_by: str = "",
) -> None:
    """Save Focus Engine configuration to YAML or JSON file.

    Args:
        config: Configuration to save
        path: Output path (.yaml/.yml or .json)
        modified_by: User identifier for audit trail
    """
    from datetime import datetime, timezone

    config.last_modified = datetime.now(timezone.utc).isoformat()
    if modified_by:
        config.modified_by = modified_by

    errors = config.validate()
    if errors:
        raise ValueError(
            f"Cannot save invalid config:\n" +
            "\n".join(f"  - {e}" for e in errors)
        )

    data = config.to_dict()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            raise ImportError("PyYAML required for YAML output")
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def load_preset(name: str) -> FocusEngineConfig:
    """Load a built-in preset configuration.

    Args:
        name: Preset name (conservative, standard, research)

    Returns:
        Deep copy of the preset config

    Raises:
        KeyError: If preset doesn't exist
    """
    if name not in PRESETS:
        raise KeyError(
            f"Unknown preset '{name}'. Available: {list(PRESETS.keys())}"
        )
    return copy.deepcopy(PRESETS[name])


def get_all_param_specs() -> dict[str, dict[str, ParamSpec]]:
    """Get all parameter specifications grouped by section.

    Useful for UI rendering and documentation generation.
    """
    return {
        "input_filter": dict(INPUT_FILTER_SPECS),
        "output_filter": dict(OUTPUT_FILTER_SPECS),
        "agent_rules": dict(AGENT_RULES_SPECS),
    }


# ---------------------------------------------------------------------------
# Saved Configurations Store
# ---------------------------------------------------------------------------

class SavedConfigStore:
    """SQLite-backed store for named Focus Engine configurations.

    Allows users to:
    - Save current config under a custom name
    - List all saved configs
    - Load a saved config by name
    - Delete a saved config
    - Set one config as active
    """

    def __init__(self, db_path: str | Path):
        import sqlite3
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_configs (
                name TEXT NOT NULL,
                filter_type TEXT NOT NULL DEFAULT 'both',
                description TEXT DEFAULT '',
                config_json TEXT NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                PRIMARY KEY (name, filter_type)
            )
        """)
        self._conn.commit()

    def save(
        self,
        name: str,
        config: FocusEngineConfig,
        *,
        filter_type: str = "both",
        description: str = "",
        created_by: str = "",
        set_active: bool = False,
    ) -> dict:
        """Save or update a named configuration.

        Args:
            name: Unique name for this config
            config: FocusEngineConfig to save
            description: Optional description
            created_by: User identifier
            set_active: If True, mark this config as the active one

        Returns:
            Dict with saved config metadata
        """
        from datetime import datetime, timezone

        errors = config.validate()
        if errors:
            raise ValueError(f"Cannot save invalid config: {'; '.join(errors)}")

        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config.to_dict(), ensure_ascii=False)

        # Check if exists
        row = self._conn.execute(
            "SELECT name FROM saved_configs WHERE name = ? AND filter_type = ?",
            (name, filter_type),
        ).fetchone()

        if row:
            self._conn.execute(
                """UPDATE saved_configs
                   SET config_json = ?, description = ?, updated_at = ?, created_by = ?
                   WHERE name = ? AND filter_type = ?""",
                (config_json, description, now, created_by, name, filter_type),
            )
        else:
            self._conn.execute(
                """INSERT INTO saved_configs
                   (name, filter_type, description, config_json, is_active, created_at, updated_at, created_by)
                   VALUES (?, ?, ?, ?, 0, ?, ?, ?)""",
                (name, filter_type, description, config_json, now, now, created_by),
            )

        if set_active:
            self.set_active(name, filter_type=filter_type)

        self._conn.commit()
        return {"name": name, "description": description, "saved_at": now}

    def list(self, filter_type: str | None = None) -> list[dict]:
        """List saved configurations, optionally filtered by type.

        Args:
            filter_type: Filter by type (input/output/both). None = all.

        Returns:
            List of config metadata dicts (without full config data)
        """
        if filter_type:
            rows = self._conn.execute(
                """SELECT name, filter_type, description, is_active, created_at, updated_at, created_by
                   FROM saved_configs WHERE filter_type = ? ORDER BY updated_at DESC""",
                (filter_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT name, filter_type, description, is_active, created_at, updated_at, created_by
                   FROM saved_configs ORDER BY updated_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def load(self, name: str, filter_type: str = "both") -> FocusEngineConfig:
        """Load a saved configuration by name.

        Args:
            name: Config name to load

        Returns:
            FocusEngineConfig

        Raises:
            KeyError: If config doesn't exist
        """
        row = self._conn.execute(
            "SELECT config_json FROM saved_configs WHERE name = ? AND filter_type = ?",
            (name, filter_type),
        ).fetchone()
        if not row:
            raise KeyError(f"Saved config '{name}' (type={filter_type}) not found")

        data = json.loads(row["config_json"])
        return _dict_to_config(data)

    def delete(self, name: str, filter_type: str = "both") -> bool:
        """Delete a saved configuration.

        Args:
            name: Config name to delete

        Returns:
            True if deleted, False if not found
        """
        cursor = self._conn.execute(
            "DELETE FROM saved_configs WHERE name = ? AND filter_type = ?",
            (name, filter_type),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def set_active(self, name: str, filter_type: str = "both") -> None:
        """Set a config as the active one (deactivates others).

        Args:
            name: Config name to activate

        Raises:
            KeyError: If config doesn't exist
        """
        row = self._conn.execute(
            "SELECT name FROM saved_configs WHERE name = ? AND filter_type = ?",
            (name, filter_type),
        ).fetchone()
        if not row:
            raise KeyError(f"Saved config '{name}' (type={filter_type}) not found")

        self._conn.execute(
            "UPDATE saved_configs SET is_active = 0 WHERE filter_type = ?",
            (filter_type,),
        )
        self._conn.execute(
            "UPDATE saved_configs SET is_active = 1 WHERE name = ? AND filter_type = ?",
            (name, filter_type),
        )
        self._conn.commit()

    def get_active(self, filter_type: str = "both") -> FocusEngineConfig | None:
        """Get the currently active configuration for a filter type.

        Returns:
            FocusEngineConfig or None if no active config
        """
        row = self._conn.execute(
            "SELECT config_json FROM saved_configs WHERE is_active = 1 AND filter_type = ?",
            (filter_type,),
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["config_json"])
        return _dict_to_config(data)

    def get_active_name(self, filter_type: str = "both") -> str | None:
        """Get the name of the currently active config for a filter type."""
        row = self._conn.execute(
            "SELECT name FROM saved_configs WHERE is_active = 1 AND filter_type = ?",
            (filter_type,),
        ).fetchone()
        return row["name"] if row else None

    def close(self):
        self._conn.close()
