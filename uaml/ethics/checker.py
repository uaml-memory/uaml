# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Ethics Checker — rule-based content gate for knowledge entries.

Checks content against configurable rules before storage or promotion.
Supports hard rules (reject), soft rules (flag for review), and custom rules.

Pipeline position:
    Input → [Ethics Checker] → Store (approved) / Quarantine (flagged) / Reject

Verdicts:
    - APPROVED: Content passes all rules
    - FLAGGED: Soft rule violation — needs human review
    - REJECTED: Hard rule violation — blocked from storage

Usage:
    from uaml.ethics import EthicsChecker

    checker = EthicsChecker()
    verdict = checker.check("Some content to evaluate")
    if verdict.approved:
        store.learn(content)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class Action(str, Enum):
    REJECT = "reject"
    FLAG = "flag"


class AsimovTier(int, Enum):
    """Asimov's Laws hierarchy — higher tier always overrides lower.

    Tier 0 (Zeroth Law): Do not harm humanity / society
    Tier 1 (First Law):  Do not harm an individual
    Tier 2 (Second Law): Obey user commands (unless violating T0/T1)
    Tier 3 (Third Law):  Protect self (unless violating T0/T1/T2)
    """
    HUMANITY = 0     # Data weaponization, mass surveillance, discrimination
    INDIVIDUAL = 1   # PII leak, GDPR, attorney-client privilege, client harm
    COMMAND = 2      # User instruction compliance, audit trail
    SELF = 3         # Backup integrity, audit immutability, anti-tampering


@dataclass
class EthicsRule:
    """A single ethics rule with regex pattern matching and Asimov tier.

    The tier determines rule priority in conflict resolution:
    Tier 0 (humanity) > Tier 1 (individual) > Tier 2 (commands) > Tier 3 (self)
    """

    name: str
    description: str
    pattern: str
    severity: Severity = Severity.SOFT
    action: Action = Action.FLAG
    enabled: bool = True
    tier: AsimovTier = AsimovTier.COMMAND  # Default: Tier 2 (standard rules)
    scope: str = "input"  # "input", "output", "both"

    def matches(self, text: str) -> Optional[re.Match]:
        """Check if this rule matches the given text."""
        if not self.enabled:
            return None
        try:
            return re.search(self.pattern, text)
        except re.error:
            return None


@dataclass
class RuleMatch:
    """A single rule match with context."""

    rule: EthicsRule
    matched_text: str
    position: int


@dataclass
class EthicsVerdict:
    """Result of ethics check on content."""

    verdict: str  # "APPROVED", "FLAGGED", "REJECTED"
    matches: list[RuleMatch] = field(default_factory=list)
    content_length: int = 0

    @property
    def approved(self) -> bool:
        return self.verdict == "APPROVED"

    @property
    def flagged(self) -> bool:
        return self.verdict == "FLAGGED"

    @property
    def rejected(self) -> bool:
        return self.verdict == "REJECTED"

    @property
    def rules_triggered(self) -> list[str]:
        return [m.rule.name for m in self.matches]

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "rules_triggered": self.rules_triggered,
            "highest_tier": min((m.rule.tier.value for m in self.matches), default=None),
            "highest_tier_name": AsimovTier(min(m.rule.tier.value for m in self.matches)).name if self.matches else None,
            "matches": [
                {
                    "rule": m.rule.name,
                    "severity": m.rule.severity.value,
                    "action": m.rule.action.value,
                    "tier": m.rule.tier.value,
                    "tier_name": m.rule.tier.name,
                    "scope": m.rule.scope,
                    "matched_text": m.matched_text[:50],  # Truncate for safety
                    "position": m.position,
                }
                for m in self.matches
            ],
            "content_length": self.content_length,
        }


# ── Default Rules ────────────────────────────────────────────

DEFAULT_RULES = [
    # ── Tier 0: Humanity (Zeroth Law) ──────────────────────
    EthicsRule(
        name="no_data_weaponization",
        description="Block content enabling data weaponization or mass surveillance",
        pattern=r"(?i)(mass\s+surveillance|weapon(iz|is)e?\s+data|target(ing)?\s+(ethnic|racial|religious)|social\s+credit\s+scor)",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.HUMANITY,
        scope="both",
    ),
    EthicsRule(
        name="no_discrimination",
        description="Block content promoting systematic discrimination",
        pattern=r"(?i)(deny\s+service\s+based\s+on\s+(race|gender|religion|ethnicity|disability)|profil(e|ing)\s+(ethnic|racial))",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.HUMANITY,
        scope="both",
    ),

    # ── Tier 1: Individual (First Law) ─────────────────────
    EthicsRule(
        name="no_credentials",
        description="Block entries containing plaintext credentials",
        pattern=r"(?i)(password|passwd|api[_-]?key|secret[_-]?key|token|bearer)\s*[:=]\s*['\"]?\S{8,}",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.INDIVIDUAL,
        scope="both",
    ),
    EthicsRule(
        name="no_private_keys",
        description="Block entries containing private key material",
        pattern=r"(?i)(BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY|age1[a-z0-9]{58}|sk-ant-|sk-[a-zA-Z0-9]{20,})",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.INDIVIDUAL,
        scope="both",
    ),
    EthicsRule(
        name="no_personal_data",
        description="Flag entries with PII (emails, phone numbers, national IDs)",
        pattern=r"(?i)(\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b|\b\+?\d{3}[\s-]?\d{3}[\s-]?\d{3,4}\b|\brodné\s+číslo\b|\bIČO?\b\s*:?\s*\d{8})",
        severity=Severity.SOFT,
        action=Action.FLAG,
        tier=AsimovTier.INDIVIDUAL,
        scope="both",
    ),
    EthicsRule(
        name="no_client_data_leak",
        description="Block entries mixing data from different clients",
        pattern=r"(?i)(client[_-]?ref\s*[:=]\s*\S+.*client[_-]?ref\s*[:=]\s*\S+)",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.INDIVIDUAL,
        scope="both",
    ),
    EthicsRule(
        name="no_attorney_privilege",
        description="Block disclosure of attorney-client privileged information to unauthorized parties",
        pattern=r"(?i)(advokátní\s+tajemství|attorney[_-]?client\s+privilege|legal\s+privilege|důvěrné.*klient)",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.INDIVIDUAL,
        scope="output",
    ),

    # ── Tier 2: Commands (Second Law) ──────────────────────
    EthicsRule(
        name="no_fabrication_markers",
        description="Flag entries with typical AI fabrication markers",
        pattern=r"(?i)(as an ai|i cannot|i don'?t have access|i'?m sorry.*but|hypothetically|it'?s worth noting that|in my experience as)",
        severity=Severity.SOFT,
        action=Action.FLAG,
        tier=AsimovTier.COMMAND,
        scope="both",
    ),
    EthicsRule(
        name="no_internal_paths",
        description="Flag entries exposing internal infrastructure paths",
        pattern=r"(/root/\.openclaw|/home/\w+/\.openclaw|/etc/shadow|/etc/passwd)",
        severity=Severity.SOFT,
        action=Action.FLAG,
        tier=AsimovTier.COMMAND,
        scope="output",
    ),
    EthicsRule(
        name="no_spam_content",
        description="Flag likely spam or noise content",
        pattern=r"(?i)(buy now|click here|limited offer|act fast|congratulations you won|nigerian prince)",
        severity=Severity.SOFT,
        action=Action.FLAG,
        tier=AsimovTier.COMMAND,
        scope="input",
    ),
    EthicsRule(
        name="min_content_length",
        description="Flag entries with very short content (likely noise)",
        pattern=r"^.{0,10}$",
        severity=Severity.SOFT,
        action=Action.FLAG,
        tier=AsimovTier.COMMAND,
        scope="input",
    ),

    # ── Tier 3: Self-Protection (Third Law) ────────────────
    EthicsRule(
        name="no_audit_tampering",
        description="Block attempts to delete or modify audit logs",
        pattern=r"(?i)(delete\s+from\s+audit|drop\s+table\s+audit|truncate\s+audit|clear\s+(all\s+)?logs)",
        severity=Severity.HARD,
        action=Action.REJECT,
        tier=AsimovTier.SELF,
        scope="input",
    ),
    EthicsRule(
        name="no_memory_wipe",
        description="Flag attempts to bulk-delete knowledge without authorization",
        pattern=r"(?i)(delete\s+all|wipe\s+(all\s+)?memory|drop\s+table\s+knowledge|forget\s+everything|erase\s+(all|entire))",
        severity=Severity.SOFT,
        action=Action.FLAG,
        tier=AsimovTier.SELF,
        scope="input",
    ),
]


class EthicsChecker:
    """Ethics checker with configurable rules.

    Rules can be:
    - Built-in defaults (DEFAULT_RULES)
    - Custom rules added via add_rule()
    - Loaded from YAML configuration

    Usage:
        checker = EthicsChecker()
        verdict = checker.check("Some content")

        # With custom rules
        checker.add_rule(EthicsRule(
            name="no_competitor_data",
            description="Block competitor proprietary info",
            pattern=r"(?i)confidential.*competitor",
            severity=Severity.HARD,
            action=Action.REJECT,
        ))
    """

    def __init__(self, rules: Optional[list[EthicsRule]] = None, use_defaults: bool = True):
        """Initialize with optional custom rules.

        Args:
            rules: Custom rules to add (on top of or instead of defaults)
            use_defaults: Whether to include DEFAULT_RULES (default: True)
        """
        self._rules: list[EthicsRule] = []
        if use_defaults:
            self._rules.extend(DEFAULT_RULES)
        if rules:
            self._rules.extend(rules)

    @property
    def rules(self) -> list[EthicsRule]:
        """Get active rules."""
        return [r for r in self._rules if r.enabled]

    @property
    def all_rules(self) -> list[EthicsRule]:
        """Get all rules including disabled."""
        return list(self._rules)

    def add_rule(self, rule: EthicsRule) -> None:
        """Add a custom rule."""
        # Replace if name exists
        self._rules = [r for r in self._rules if r.name != rule.name]
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if found."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def disable_rule(self, name: str) -> bool:
        """Disable a rule by name. Returns True if found."""
        for r in self._rules:
            if r.name == name:
                r.enabled = False
                return True
        return False

    def enable_rule(self, name: str) -> bool:
        """Enable a rule by name. Returns True if found."""
        for r in self._rules:
            if r.name == name:
                r.enabled = True
                return True
        return False

    def check(self, content: str) -> EthicsVerdict:
        """Check content against all active rules (both input and output scopes).

        Returns an EthicsVerdict with the overall result and any matches.
        Matches are sorted by Asimov tier (highest priority first).
        """
        return self._check_with_scope(content, scope=None)

    def check_input(self, content: str) -> EthicsVerdict:
        """Check incoming content (before storage). Applies rules with scope 'input' or 'both'."""
        return self._check_with_scope(content, scope="input")

    def check_output(self, content: str) -> EthicsVerdict:
        """Check outgoing content (before delivery to user/external).

        Applies rules with scope 'output' or 'both'.
        Critical for: PII masking, attorney-client privilege, internal path leaks.
        """
        return self._check_with_scope(content, scope="output")

    def _check_with_scope(self, content: str, scope: Optional[str] = None) -> EthicsVerdict:
        """Internal check with optional scope filtering."""
        matches: list[RuleMatch] = []

        for rule in self.rules:
            # Filter by scope if specified
            if scope and rule.scope != "both" and rule.scope != scope:
                continue

            match = rule.matches(content)
            if match:
                matches.append(RuleMatch(
                    rule=rule,
                    matched_text=match.group(0),
                    position=match.start(),
                ))

        # Sort matches by Asimov tier (highest priority = lowest tier number)
        matches.sort(key=lambda m: m.rule.tier.value)

        # Determine verdict using Asimov hierarchy:
        # Higher tier rules ALWAYS take precedence
        if not matches:
            verdict = "APPROVED"
        elif any(m.rule.action == Action.REJECT for m in matches):
            verdict = "REJECTED"
        else:
            verdict = "FLAGGED"

        return EthicsVerdict(
            verdict=verdict,
            matches=matches,
            content_length=len(content),
        )

    def resolve_conflict(self, content: str, user_intent: str = "") -> dict:
        """Resolve conflicts between Asimov tiers.

        When a user command (Tier 2) conflicts with individual protection (Tier 1)
        or humanity protection (Tier 0), the higher tier wins.

        Returns a dict with the resolution and explanation.

        Example:
            User: "Delete all records about client X" (Tier 2: obey command)
            Rule: "no_client_data_leak" (Tier 1: protect individual)
            → Tier 1 wins: "Cannot delete — client data protection overrides user command"
        """
        input_verdict = self.check_input(content)
        combined_text = f"{content} {user_intent}".strip() if user_intent else content

        resolution = {
            "allowed": input_verdict.approved,
            "verdict": input_verdict.verdict,
            "conflicts": [],
            "explanation": "",
        }

        if not input_verdict.matches:
            resolution["explanation"] = "No ethics rules triggered. Action allowed."
            return resolution

        # Group matches by tier
        tier_matches: dict[int, list[RuleMatch]] = {}
        for m in input_verdict.matches:
            tier_matches.setdefault(m.rule.tier.value, []).append(m)

        # Find the highest priority (lowest number) tier with rejections
        blocking_tier = None
        for tier_val in sorted(tier_matches.keys()):
            if any(m.rule.action == Action.REJECT for m in tier_matches[tier_val]):
                blocking_tier = tier_val
                break

        if blocking_tier is not None:
            tier_name = AsimovTier(blocking_tier).name
            blocking_rules = [m.rule.name for m in tier_matches[blocking_tier]
                              if m.rule.action == Action.REJECT]
            resolution["allowed"] = False
            resolution["conflicts"] = [
                {
                    "blocking_tier": tier_name,
                    "blocking_rules": blocking_rules,
                    "overrides_tier": "COMMAND",
                    "reason": f"Tier {blocking_tier} ({tier_name}) overrides Tier 2 (COMMAND)",
                }
            ]
            resolution["explanation"] = (
                f"Action blocked by {tier_name} tier (Asimov Law {blocking_tier}). "
                f"Rules: {', '.join(blocking_rules)}. "
                f"Higher-priority laws cannot be overridden by user commands."
            )
        else:
            flagging_tiers = sorted(tier_matches.keys())
            resolution["explanation"] = (
                f"Action flagged for review by tier(s): "
                f"{', '.join(AsimovTier(t).name for t in flagging_tiers)}. "
                f"No hard block — proceed with caution."
            )

        return resolution

    def check_entry(self, content: str, summary: str = "", tags: str = "") -> EthicsVerdict:
        """Check a full knowledge entry (content + summary + tags).

        Concatenates all fields for comprehensive checking.
        """
        full_text = f"{content} {summary} {tags}".strip()
        return self.check(full_text)

    @classmethod
    def from_yaml(cls, path: str) -> "EthicsChecker":
        """Load rules from a YAML file.

        YAML format:
            rules:
              - name: no_credentials
                description: Block plaintext credentials
                pattern: "(?i)password\\s*[:=]\\s*\\S{8,}"
                severity: hard
                action: reject
                enabled: true
        """
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML required for YAML rules: pip install pyyaml")

        with open(path) as f:
            data = yaml.safe_load(f)

        rules = []
        for r in data.get("rules", []):
            rules.append(EthicsRule(
                name=r["name"],
                description=r.get("description", ""),
                pattern=r["pattern"],
                severity=Severity(r.get("severity", "soft")),
                action=Action(r.get("action", "flag")),
                enabled=r.get("enabled", True),
            ))

        return cls(rules=rules, use_defaults=False)

    def to_yaml(self) -> str:
        """Export rules as YAML string."""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML required: pip install pyyaml")

        data = {
            "rules": [
                {
                    "name": r.name,
                    "description": r.description,
                    "pattern": r.pattern,
                    "severity": r.severity.value,
                    "action": r.action.value,
                    "enabled": r.enabled,
                }
                for r in self._rules
            ]
        }
        return yaml.dump(data, default_flow_style=False, allow_unicode=True)

    def stats(self) -> dict:
        """Return rule statistics including Asimov tier distribution."""
        active = [r for r in self._rules if r.enabled]
        tier_counts = {}
        for tier in AsimovTier:
            tier_counts[tier.name.lower()] = len([r for r in active if r.tier == tier])

        return {
            "total_rules": len(self._rules),
            "active_rules": len(active),
            "hard_rules": len([r for r in active if r.severity == Severity.HARD]),
            "soft_rules": len([r for r in active if r.severity == Severity.SOFT]),
            "reject_actions": len([r for r in active if r.action == Action.REJECT]),
            "flag_actions": len([r for r in active if r.action == Action.FLAG]),
            "tiers": tier_counts,
            "scopes": {
                "input": len([r for r in active if r.scope in ("input", "both")]),
                "output": len([r for r in active if r.scope in ("output", "both")]),
            },
        }
