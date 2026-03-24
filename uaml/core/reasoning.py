# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""Reasoning Traces — capture and query agent decision-making processes.

Reasoning traces record WHY decisions were made, WHAT evidence was used,
and HOW conclusions were reached. This is the 4th memory type alongside
episodic, semantic, and procedural memory.

Usage:
    from uaml.core.reasoning import ReasoningTracer

    tracer = ReasoningTracer(store)
    trace_id = tracer.record(
        decision="Chose SQLite over PostgreSQL",
        reasoning="Local-first architecture requires embedded DB. No external deps.",
        evidence_ids=[1, 5, 12],
        context="Evaluating DB options for UAML package",
    )

    # Find reasoning for a decision
    traces = tracer.search("SQLite decision")

    # Get evidence chain
    chain = tracer.evidence_chain(trace_id)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from uaml.core.store import MemoryStore


# Patterns that suggest reasoning in conversation text
REASONING_PATTERNS = [
    r"(?:rozhodli|rozhodl|rozhodla) jsme se",
    r"(?:navrhuji|navrhuju|doporučuji)",
    r"(?:protože|proto|důvod|reason)",
    r"(?:závěr|conclusion|decided|decision)",
    r"(?:po zvážení|after considering)",
    r"(?:vybrali jsme|zvolili jsme|chose|selected)",
    r"(?:výhody|nevýhody|pros|cons|trade-?off)",
    r"(?:alternativy|alternatives|options were)",
    r"(?:poučení|lesson learned|takeaway)",
    r"(?:schváleno|approved|rejected|zamítnuto)",
]


@dataclass
class ReasoningTrace:
    """A recorded reasoning trace."""

    id: int
    decision: str
    reasoning: str
    context: str = ""
    confidence: float = 0.8
    agent_id: str = ""
    evidence_ids: list[int] = field(default_factory=list)
    tags: str = ""
    created_at: str = ""

    @property
    def summary(self) -> str:
        return f"{self.decision[:80]}..." if len(self.decision) > 80 else self.decision


class ReasoningTracer:
    """Record and query agent reasoning traces.

    Reasoning traces capture the decision-making process:
    - What was decided
    - Why (the reasoning chain)
    - What evidence was used
    - What alternatives were considered
    """

    def __init__(self, store: MemoryStore):
        self.store = store
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create reasoning_traces table if it doesn't exist."""
        self.store.conn.executescript("""
            CREATE TABLE IF NOT EXISTS reasoning_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision TEXT NOT NULL,
                reasoning TEXT NOT NULL,
                context TEXT DEFAULT '',
                confidence REAL DEFAULT 0.8,
                agent_id TEXT DEFAULT 'default',
                tags TEXT DEFAULT '',
                project TEXT,
                client_ref TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reasoning_evidence (
                trace_id INTEGER NOT NULL,
                entry_id INTEGER NOT NULL,
                role TEXT DEFAULT 'supports',  -- supports, contradicts, context
                notes TEXT DEFAULT '',
                PRIMARY KEY (trace_id, entry_id),
                FOREIGN KEY (trace_id) REFERENCES reasoning_traces(id),
                FOREIGN KEY (entry_id) REFERENCES knowledge(id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS reasoning_fts
                USING fts5(decision, reasoning, context, content=reasoning_traces, content_rowid=id);

            CREATE TRIGGER IF NOT EXISTS reasoning_ai AFTER INSERT ON reasoning_traces BEGIN
                INSERT INTO reasoning_fts(rowid, decision, reasoning, context)
                VALUES (new.id, new.decision, new.reasoning, new.context);
            END;

            CREATE TRIGGER IF NOT EXISTS reasoning_ad AFTER DELETE ON reasoning_traces BEGIN
                INSERT INTO reasoning_fts(reasoning_fts, rowid, decision, reasoning, context)
                VALUES ('delete', old.id, old.decision, old.reasoning, old.context);
            END;
        """)

    def record(
        self,
        decision: str,
        reasoning: str,
        *,
        evidence_ids: list[int] | None = None,
        context: str = "",
        confidence: float = 0.8,
        agent_id: Optional[str] = None,
        tags: str = "",
        project: Optional[str] = None,
        client_ref: Optional[str] = None,
    ) -> int:
        """Record a reasoning trace.

        Args:
            decision: What was decided
            reasoning: Why (the reasoning chain)
            evidence_ids: Knowledge entry IDs used as evidence
            context: What prompted this decision
            confidence: How confident in this reasoning (0-1)
            agent_id: Which agent made this decision
            tags: Comma-separated tags
            project: Project context
            client_ref: Client reference for isolation
        """
        agent = agent_id or self.store.agent_id

        cursor = self.store.conn.execute(
            """INSERT INTO reasoning_traces
            (decision, reasoning, context, confidence, agent_id, tags, project, client_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision, reasoning, context, confidence, agent, tags, project, client_ref),
        )
        trace_id = cursor.lastrowid

        # Link evidence
        if evidence_ids:
            for eid in evidence_ids:
                self.store.conn.execute(
                    "INSERT OR IGNORE INTO reasoning_evidence (trace_id, entry_id) VALUES (?, ?)",
                    (trace_id, eid),
                )

        self.store.conn.commit()

        # Audit
        self.store._audit(
            "record_reasoning", "reasoning_traces", trace_id, agent,
            details=f"evidence={len(evidence_ids or [])}"
        )

        return trace_id

    def search(self, query: str, *, limit: int = 10) -> list[ReasoningTrace]:
        """Search reasoning traces via FTS."""
        rows = self.store.conn.execute(
            """SELECT rt.*, reasoning_fts.rank
            FROM reasoning_traces rt
            JOIN reasoning_fts ON rt.id = reasoning_fts.rowid
            WHERE reasoning_fts MATCH ?
            ORDER BY reasoning_fts.rank
            LIMIT ?""",
            (query, limit),
        ).fetchall()

        return [self._row_to_trace(r) for r in rows]

    def get(self, trace_id: int) -> Optional[ReasoningTrace]:
        """Get a single reasoning trace with evidence."""
        row = self.store.conn.execute(
            "SELECT * FROM reasoning_traces WHERE id = ?", (trace_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_trace(row)

    def evidence_chain(self, trace_id: int) -> list[dict]:
        """Get the evidence chain for a reasoning trace.

        Returns knowledge entries linked as evidence, with their roles.
        """
        rows = self.store.conn.execute(
            """SELECT k.*, re.role, re.notes as evidence_notes
            FROM reasoning_evidence re
            JOIN knowledge k ON re.entry_id = k.id
            WHERE re.trace_id = ?
            ORDER BY re.role, k.id""",
            (trace_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_traces(
        self,
        *,
        project: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[ReasoningTrace]:
        """List reasoning traces with optional filters."""
        where_parts = []
        params: list = []

        if project:
            where_parts.append("project = ?")
            params.append(project)
        if agent_id:
            where_parts.append("agent_id = ?")
            params.append(agent_id)

        where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
        rows = self.store.conn.execute(
            f"SELECT * FROM reasoning_traces {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def detect_reasoning(self, text: str) -> bool:
        """Detect if text contains reasoning patterns.

        Used for auto-capturing reasoning from conversation.
        """
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in REASONING_PATTERNS)

    def auto_extract(self, text: str, *, agent_id: Optional[str] = None, context: str = "") -> Optional[int]:
        """Auto-extract and record reasoning from text if detected.

        Returns trace_id if reasoning was found and recorded, None otherwise.
        """
        if not self.detect_reasoning(text):
            return None

        if len(text) < 30:
            return None

        # Split into decision (first sentence) and reasoning (rest)
        sentences = re.split(r'[.!?]\s+', text, maxsplit=1)
        decision = sentences[0].strip()
        reasoning = sentences[1].strip() if len(sentences) > 1 else text

        return self.record(
            decision=decision[:500],
            reasoning=reasoning[:2000],
            context=context,
            agent_id=agent_id,
            confidence=0.6,  # Auto-extracted = lower confidence
            tags="auto-extracted",
        )

    def stats(self) -> dict:
        """Get reasoning trace statistics."""
        total = self.store.conn.execute("SELECT COUNT(*) FROM reasoning_traces").fetchone()[0]
        with_evidence = self.store.conn.execute(
            "SELECT COUNT(DISTINCT trace_id) FROM reasoning_evidence"
        ).fetchone()[0]
        by_agent = self.store.conn.execute(
            "SELECT agent_id, COUNT(*) as count FROM reasoning_traces GROUP BY agent_id"
        ).fetchall()

        return {
            "total_traces": total,
            "with_evidence": with_evidence,
            "by_agent": {r["agent_id"]: r["count"] for r in by_agent},
        }

    def _row_to_trace(self, row) -> ReasoningTrace:
        d = dict(row)
        # Get evidence IDs
        evidence = self.store.conn.execute(
            "SELECT entry_id FROM reasoning_evidence WHERE trace_id = ?",
            (d["id"],),
        ).fetchall()

        return ReasoningTrace(
            id=d["id"],
            decision=d["decision"],
            reasoning=d["reasoning"],
            context=d.get("context", ""),
            confidence=d.get("confidence", 0.8),
            agent_id=d.get("agent_id", ""),
            evidence_ids=[r["entry_id"] for r in evidence],
            tags=d.get("tags", ""),
            created_at=d.get("created_at", ""),
        )
