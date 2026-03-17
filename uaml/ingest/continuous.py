# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Continuous Learner — auto-ingest knowledge from live sessions.

Watches session JSONL files for new messages and automatically extracts
knowledge from tool results, decisions, and significant content.

Usage:
    from uaml.ingest.continuous import ContinuousLearner

    learner = ContinuousLearner(store)
    learner.process_message(msg)            # Single message
    learner.process_session_file("sess.jsonl")  # Incremental file processing
    stats = learner.stats()
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from uaml.core.store import MemoryStore


# Tool result patterns to extract knowledge from
VALUABLE_TOOLS = {
    "web_search", "web_fetch", "read", "exec",
    "search", "browse", "calculate", "analyze",
}

# Minimum content length to consider valuable
MIN_CONTENT_LENGTH = 50

# Patterns that indicate a decision or conclusion
DECISION_PATTERNS = [
    r"(?:decided|concluded|determined|chose|selected|opted)\s+(?:to|for|that)",
    r"(?:rozhodl|zvolil|vybral|usoudil)\s+",
    r"the (?:best|correct|right|optimal) (?:approach|solution|way|option)",
    r"(?:therefore|thus|hence|consequently|proto|tedy|tudíž)",
]


@dataclass
class LearnerStats:
    """Statistics from continuous learning."""
    messages_processed: int = 0
    tool_results_extracted: int = 0
    decisions_captured: int = 0
    knowledge_created: int = 0
    skipped: int = 0
    errors: int = 0


class ContinuousLearner:
    """Auto-extract knowledge from live agent sessions."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        min_content_length: int = MIN_CONTENT_LENGTH,
        extract_tool_results: bool = True,
        extract_decisions: bool = True,
        auto_reasoning: bool = True,
    ):
        self.store = store
        self.min_content_length = min_content_length
        self.extract_tool_results = extract_tool_results
        self.extract_decisions = extract_decisions
        self.auto_reasoning = auto_reasoning
        self._stats = LearnerStats()
        self._processed_lines: dict[str, int] = {}  # file → last processed line

    def process_message(self, msg: dict, *, session_id: str = "") -> int:
        """Process a single message and extract knowledge.

        Returns number of knowledge entries created.
        """
        self._stats.messages_processed += 1
        created = 0

        # Extract tool results
        if self.extract_tool_results:
            created += self._extract_tool_results(msg, session_id)

        # Extract decisions/conclusions
        if self.extract_decisions:
            created += self._extract_decisions(msg, session_id)

        # Auto-capture reasoning
        if self.auto_reasoning:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > self.min_content_length:
                trace_id = self.store.auto_capture_reasoning(content)
                if trace_id:
                    self._stats.decisions_captured += 1

        self._stats.knowledge_created += created
        return created

    def process_session_file(self, path: str | Path, *, incremental: bool = True) -> LearnerStats:
        """Process a session JSONL file, optionally incrementally.

        Args:
            path: Path to session JSONL file
            incremental: If True, only process new lines since last call

        Returns:
            Stats for this processing run
        """
        path = Path(path)
        if not path.exists():
            return self._stats

        file_key = str(path)
        start_line = self._processed_lines.get(file_key, 0) if incremental else 0
        session_id = path.stem

        run_stats = LearnerStats()

        with open(path) as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue

                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                    created = self.process_message(msg, session_id=session_id)
                    run_stats.messages_processed += 1
                    run_stats.knowledge_created += created
                except json.JSONDecodeError:
                    run_stats.errors += 1
                except Exception:
                    run_stats.errors += 1

        self._processed_lines[file_key] = i + 1 if 'i' in dir() else start_line

        return run_stats

    def _extract_tool_results(self, msg: dict, session_id: str) -> int:
        """Extract knowledge from tool call results."""
        created = 0
        content = msg.get("content")

        # Handle list content (tool results)
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_content = part.get("content", "")
                    tool_id = part.get("tool_use_id", "unknown")
                    if isinstance(tool_content, str) and len(tool_content) >= self.min_content_length:
                        self._store_tool_result(tool_content, tool_id, session_id)
                        created += 1

        # Handle tool_calls field
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict):
                output = tc.get("result", tc.get("output", ""))
                name = tc.get("function", {}).get("name", tc.get("name", "unknown"))
                if isinstance(output, str) and len(output) >= self.min_content_length:
                    self._store_tool_result(output, name, session_id)
                    created += 1

        # Handle role=tool messages
        if msg.get("role") == "tool":
            tool_content = msg.get("content", "")
            tool_name = msg.get("name", "unknown")
            if isinstance(tool_content, str) and len(tool_content) >= self.min_content_length:
                self._store_tool_result(tool_content, tool_name, session_id)
                created += 1

        self._stats.tool_results_extracted += created
        return created

    def _store_tool_result(self, content: str, tool_name: str, session_id: str) -> None:
        """Store a tool result as knowledge."""
        # Truncate very long results
        if len(content) > 5000:
            content = content[:5000] + f"\n[truncated, {len(content)} chars]"

        self.store.learn(
            f"[Tool: {tool_name}] {content}",
            source_type="tool_result",
            source_origin="derived",
            data_layer="operational",
            tags=f"tool:{tool_name},session:{session_id}",
            source_ref=f"session:{session_id}:tool:{tool_name}",
            dedup=True,
        )

    def _extract_decisions(self, msg: dict, session_id: str) -> int:
        """Extract decisions and conclusions from message content."""
        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) < self.min_content_length:
            return 0

        role = msg.get("role", "")
        if role not in ("assistant", "ai"):
            return 0

        # Check for decision patterns
        for pattern in DECISION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                # Extract the sentence containing the decision
                sentences = re.split(r'[.!?\n]', content)
                for sentence in sentences:
                    if re.search(pattern, sentence, re.IGNORECASE) and len(sentence.strip()) >= 30:
                        self.store.learn(
                            sentence.strip(),
                            source_type="decision",
                            source_origin="generated",
                            data_layer="knowledge",
                            tags=f"decision,session:{session_id}",
                            source_ref=f"session:{session_id}",
                            dedup=True,
                        )
                        self._stats.decisions_captured += 1
                        return 1
        return 0

    def stats(self) -> dict:
        """Get learner statistics."""
        return {
            "messages_processed": self._stats.messages_processed,
            "tool_results_extracted": self._stats.tool_results_extracted,
            "decisions_captured": self._stats.decisions_captured,
            "knowledge_created": self._stats.knowledge_created,
            "skipped": self._stats.skipped,
            "errors": self._stats.errors,
            "tracked_files": len(self._processed_lines),
        }
