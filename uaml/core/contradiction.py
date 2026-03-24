# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Contradiction Detection — pre-learn hook for UAML.

Detects when new knowledge contradicts existing entries and handles it:
1. **Supersession** — newer fact replaces older (auto-resolve)
2. **Contradiction** — conflicting claims that need review (flag)
3. **Evolution** — numerical values that naturally change over time (track)

Integrated into MemoryStore.learn() as a pre-learn hook.

Usage:
    checker = ContradictionChecker(store)
    result = checker.check(new_content, topic="neo4j", agent_id="metod")
    # result.action: "ok" | "supersede" | "flag" | "evolve"
    # result.conflicting_ids: list of entry IDs that conflict
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── Patterns for extractable factual claims ──

# IP addresses
IP_PATTERN = re.compile(
    r'(?:^|\s)(\b[\w][\w.-]*\b)\s+(?:IP|address|adresa|addr)[:\s]+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})',
    re.IGNORECASE,
)

# Port numbers
PORT_PATTERN = re.compile(
    r'(?:^|\s)(\b[\w][\w.-]*\b)\s+(?:port|PORT)[:\s]+(\d{2,5})',
    re.IGNORECASE,
)

# Version strings
VERSION_PATTERN = re.compile(
    r'(\b[\w][\w.-]*\b)\s+(?:version|verze|v\.?)[:\s]+([\d]+(?:\.[\d]+)+\S*)',
    re.IGNORECASE,
)

# Numerical metrics (e.g., "2301 nodes", "967 entries")
METRIC_PATTERN = re.compile(
    r'(\d[\d,]*)\s+(nodes?|entries|sessions?|items?|rows?|vztahů|relationships?|records?)',
    re.IGNORECASE,
)

# Status claims (e.g., "Neo4j is running", "SSH je disabled")
STATUS_PATTERN = re.compile(
    r'(\b[\w][\w.-]*\b)\s+(?:is|je|=|:)\s+(running|stopped|disabled|enabled|active|inactive|down|up|online|offline)',
    re.IGNORECASE,
)

# Boolean/decision claims (e.g., "We chose X", "Decision: Y")
DECISION_PATTERN = re.compile(
    r'(?:chose|selected|decision|rozhodnutí|schváleno|approved|rejected|zvolili|vybrali)[:\s]+(.{10,80})',
    re.IGNORECASE,
)


@dataclass
class FactClaim:
    """A single extractable factual claim from text."""
    claim_type: str  # ip, port, version, metric, status, decision
    subject: str     # what entity the claim is about
    value: str       # the claimed value
    raw: str         # original matched text


@dataclass
class ContradictionResult:
    """Result of contradiction check."""
    action: str = "ok"  # ok | supersede | flag | evolve
    conflicting_ids: list[int] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    supersede_ids: list[int] = field(default_factory=list)  # IDs to mark as superseded
    severity: str = "none"  # none | low | medium | high

    @property
    def has_conflict(self) -> bool:
        return self.action != "ok"


class ContradictionChecker:
    """Check new content against existing knowledge for contradictions.

    Strategies:
    1. Extract factual claims (IPs, ports, versions, metrics, status)
    2. Find existing entries with same topic/subject
    3. Compare claims — if same subject + different value → contradiction
    4. Determine resolution: supersede (newer wins) or flag (ambiguous)
    """

    def __init__(self, store):
        """Initialize with a MemoryStore instance.
        
        Args:
            store: MemoryStore instance (imported at runtime to avoid circular deps)
        """
        self.store = store

    def check(
        self,
        content: str,
        *,
        topic: str = "",
        agent_id: str = "",
        project: str = "",
        client_ref: Optional[str] = None,
    ) -> ContradictionResult:
        """Check new content for contradictions against existing knowledge.

        Returns a ContradictionResult with action recommendation.
        """
        result = ContradictionResult()

        # 1. Extract factual claims from new content
        new_claims = self.extract_claims(content)
        if not new_claims:
            return result  # No extractable facts → no contradiction possible

        # 2. Find existing entries that might conflict
        candidates = self._find_candidates(content, topic, project, client_ref)
        if not candidates:
            return result  # No existing knowledge to conflict with

        # 3. Extract claims from candidates and compare
        for candidate in candidates:
            old_claims = self.extract_claims(candidate.get("content") or "")
            conflicts = self._compare_claims(new_claims, old_claims)

            for conflict in conflicts:
                ctype = conflict["type"]
                
                if ctype == "metric_evolution":
                    # Numbers naturally change (e.g., node counts growing)
                    result.action = "evolve" if result.action == "ok" else result.action
                    result.severity = max(result.severity, "low", key=_severity_order)
                    result.details.append(
                        f"Metric evolution: {conflict['subject']} "
                        f"{conflict['old_value']} → {conflict['new_value']}"
                    )
                    result.supersede_ids.append(candidate["id"])

                elif ctype == "value_change":
                    # Same subject, different value (IP, port, version, status)
                    result.action = "supersede"
                    result.severity = max(result.severity, "medium", key=_severity_order)
                    result.conflicting_ids.append(candidate["id"])
                    result.supersede_ids.append(candidate["id"])
                    result.details.append(
                        f"Value changed: {conflict['subject']} "
                        f"{conflict['claim_type']}={conflict['old_value']} → {conflict['new_value']}"
                    )

                elif ctype == "decision_conflict":
                    # Conflicting decisions — needs human review
                    result.action = "flag"
                    result.severity = max(result.severity, "high", key=_severity_order)
                    result.conflicting_ids.append(candidate["id"])
                    result.details.append(
                        f"Conflicting decision: old='{conflict['old_value'][:60]}' "
                        f"vs new='{conflict['new_value'][:60]}'"
                    )

        return result

    def extract_claims(self, text: str) -> list[FactClaim]:
        """Extract factual claims from text."""
        claims = []
        if not text:
            return claims

        for match in IP_PATTERN.finditer(text):
            claims.append(FactClaim(
                claim_type="ip",
                subject=match.group(1).lower(),
                value=match.group(2),
                raw=match.group(0).strip(),
            ))

        for match in PORT_PATTERN.finditer(text):
            claims.append(FactClaim(
                claim_type="port",
                subject=match.group(1).lower(),
                value=match.group(2),
                raw=match.group(0).strip(),
            ))

        for match in VERSION_PATTERN.finditer(text):
            claims.append(FactClaim(
                claim_type="version",
                subject=match.group(1).lower(),
                value=match.group(2),
                raw=match.group(0).strip(),
            ))

        for match in METRIC_PATTERN.finditer(text):
            claims.append(FactClaim(
                claim_type="metric",
                subject=match.group(2).rstrip('s').lower(),
                value=match.group(1).replace(',', ''),
                raw=match.group(0).strip(),
            ))

        for match in STATUS_PATTERN.finditer(text):
            claims.append(FactClaim(
                claim_type="status",
                subject=match.group(1).lower(),
                value=match.group(2).lower(),
                raw=match.group(0).strip(),
            ))

        for match in DECISION_PATTERN.finditer(text):
            claims.append(FactClaim(
                claim_type="decision",
                subject="decision",
                value=match.group(1).strip(),
                raw=match.group(0).strip(),
            ))

        return claims

    def _find_candidates(
        self,
        content: str,
        topic: str,
        project: str,
        client_ref: Optional[str],
    ) -> list[dict]:
        """Find existing entries that might conflict with new content.

        Uses topic match + FTS search to find relevant candidates.
        """
        candidates = []
        seen_ids = set()

        # Detect which column holds the main text (content vs summary)
        # Production DB uses 'summary', UAML package uses 'content'
        try:
            cols = [r[1] for r in self.store.conn.execute("PRAGMA table_info(knowledge)").fetchall()]
            has_content = "content" in cols
            has_summary = "summary" in cols
            # Use COALESCE to check both columns
            if has_content and has_summary:
                text_col = "COALESCE(NULLIF(k.content,''), k.summary)"
            elif has_content:
                text_col = "k.content"
            else:
                text_col = "k.summary"
        except Exception:
            text_col = "content"

        # Strategy 1: Same topic entries (highest relevance)
        if topic:
            rows = self.store.conn.execute(
                f"SELECT k.id, {text_col} as content, k.topic, k.created_at, k.confidence, k.superseded_by "
                "FROM knowledge k WHERE k.topic = ? AND k.superseded_by IS NULL "
                "ORDER BY k.created_at DESC LIMIT 20",
                (topic,),
            ).fetchall()
            for r in rows:
                if r["id"] not in seen_ids:
                    candidates.append(dict(r))
                    seen_ids.add(r["id"])

        # Strategy 2: FTS search for content overlap (broader)
        # Extract key terms for searching
        words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
        tech_terms = re.findall(
            r'\b(?:Neo4j|SQLite|Ollama|UAML|MCP|SSH|VPS|GPU|CUDA|RTX|Whisper|WSL2?|HTTP|API|LND|'
            r'Docker|systemd|nginx|Redis|PostgreSQL|Kubernetes|Grafana|Prometheus)\b',
            content, re.IGNORECASE,
        )
        query_terms = list(set(words + tech_terms))[:5]

        if query_terms:
            fts_query = " OR ".join(t.replace("'", "''") for t in query_terms)
            try:
                rows = self.store.conn.execute(
                    f"SELECT k.id, {text_col} as content, k.topic, k.created_at, k.confidence, k.superseded_by "
                    "FROM knowledge k "
                    "JOIN knowledge_fts ON k.id = knowledge_fts.rowid "
                    "WHERE knowledge_fts MATCH ? AND k.superseded_by IS NULL "
                    "ORDER BY knowledge_fts.rank LIMIT 30",
                    (fts_query,),
                ).fetchall()
                for r in rows:
                    if r["id"] not in seen_ids:
                        candidates.append(dict(r))
                        seen_ids.add(r["id"])
            except Exception:
                pass  # FTS query syntax error — skip

        return candidates

    def _compare_claims(
        self,
        new_claims: list[FactClaim],
        old_claims: list[FactClaim],
    ) -> list[dict]:
        """Compare new claims against old claims for contradictions."""
        conflicts = []

        for new_claim in new_claims:
            for old_claim in old_claims:
                # Must be same type and subject to conflict
                if new_claim.claim_type != old_claim.claim_type:
                    continue

                # Subject matching (fuzzy — lowercase comparison)
                if not self._subjects_match(new_claim.subject, old_claim.subject):
                    continue

                # Same value = no conflict
                if new_claim.value == old_claim.value:
                    continue

                # Determine conflict type
                if new_claim.claim_type == "metric":
                    # Metrics evolve naturally (node counts, session counts, etc.)
                    conflicts.append({
                        "type": "metric_evolution",
                        "claim_type": "metric",
                        "subject": new_claim.subject,
                        "old_value": old_claim.value,
                        "new_value": new_claim.value,
                    })
                elif new_claim.claim_type == "decision":
                    # Decisions changing = potential real conflict
                    conflicts.append({
                        "type": "decision_conflict",
                        "claim_type": "decision",
                        "subject": "decision",
                        "old_value": old_claim.value,
                        "new_value": new_claim.value,
                    })
                else:
                    # IP, port, version, status changes
                    conflicts.append({
                        "type": "value_change",
                        "claim_type": new_claim.claim_type,
                        "subject": new_claim.subject,
                        "old_value": old_claim.value,
                        "new_value": new_claim.value,
                    })

        return conflicts

    def _subjects_match(self, subj1: str, subj2: str) -> bool:
        """Check if two subjects refer to the same entity (fuzzy match)."""
        s1, s2 = subj1.lower().strip(), subj2.lower().strip()

        # Exact match
        if s1 == s2:
            return True

        # One contains the other
        if s1 in s2 or s2 in s1:
            return True

        # Strip common suffixes/prefixes
        for suffix in ['-pc', '-vps', '-server', '-node', '-service']:
            if s1.rstrip(suffix) == s2.rstrip(suffix):
                return True

        return False


def _severity_order(s: str) -> int:
    """Map severity to integer for comparison."""
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(s, 0)
