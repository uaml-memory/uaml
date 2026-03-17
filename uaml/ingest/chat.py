# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""ChatIngestor — ingest OpenClaw chat session JSONL files.

Extracts meaningful messages from chat sessions, skipping system noise,
heartbeats, and short/empty messages.

Supports:
- OpenClaw session JSONL format (role + content + timestamp)
- Generic JSONL with 'content' or 'text' field
- Session metadata extraction (session ID from filename)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from uaml.ingest.base import BaseIngestor, IngestStats


# Messages matching these patterns are skipped
SKIP_PATTERNS = [
    "HEARTBEAT_OK",
    "NO_REPLY",
    "heartbeat poll",
    "⏰ Heartbeat",
]

# Roles to skip
SKIP_ROLES = ["system"]

# Minimum message length to consider
MIN_MSG_LENGTH = 30


class ChatIngestor(BaseIngestor):
    """Ingest chat session files into UAML knowledge store.

    Processes JSONL files where each line is a message object with
    at minimum a 'content' or 'text' field.

    Filters out:
    - System messages
    - Heartbeat acks
    - Very short messages
    - Tool call results (unless they contain substantial content)
    """

    source_type = "chat"
    source_origin = "observed"  # Chat = observed conversation
    data_layer = "team"  # Conversations are team-level shared knowledge

    def __init__(self, store, *, min_msg_length: int = MIN_MSG_LENGTH,
                 mine_tool_results: bool = True, **kwargs):
        super().__init__(store, **kwargs)
        self.min_msg_length = min_msg_length
        self.mine_tool_results = mine_tool_results

    def ingest(
        self,
        source: str | Path,
        *,
        session_id: Optional[str] = None,
        extract_topics: bool = False,
    ) -> IngestStats:
        """Ingest a chat session JSONL file.

        Args:
            source: Path to JSONL file
            session_id: Override session ID (default: derived from filename)
            extract_topics: If True, try to extract topic from content
        """
        path = Path(source)
        stats = IngestStats(source=str(path), source_type="chat")

        if not path.exists():
            stats.errors += 1
            stats.details["error"] = f"File not found: {path}"
            return stats

        sid = session_id or path.stem
        stats.details["session_id"] = sid

        with open(path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    stats.errors += 1
                    continue

                self._process_message(msg, stats, sid, line_num)

        return stats

    def _process_message(
        self, msg: dict, stats: IngestStats, session_id: str, line_num: int
    ) -> None:
        """Process a single message from the session."""
        # Get content
        content = msg.get("content") or msg.get("text") or ""
        if isinstance(content, list):
            # Handle multi-part content (e.g. tool results)
            content = " ".join(
                part.get("text", str(part))
                for part in content
                if isinstance(part, dict)
            )

        content = content.strip()

        # Skip criteria
        role = msg.get("role", "")
        if role in SKIP_ROLES:
            stats.entries_skipped += 1
            return

        if len(content) < self.min_msg_length:
            stats.entries_skipped += 1
            return

        if any(pat in content for pat in SKIP_PATTERNS):
            stats.entries_skipped += 1
            return

        # Extract timestamp
        timestamp = msg.get("timestamp") or msg.get("created_at") or msg.get("ts")

        # Build source reference
        source_ref = f"session:{session_id}:line:{line_num}"

        # Create summary (first 100 chars)
        summary = content[:100] + ("..." if len(content) > 100 else "")

        # Determine source_origin based on role
        source_origin = "observed" if role in ("user", "human") else "generated"

        self._learn_entry(
            content,
            stats,
            summary=summary,
            source_ref=source_ref,
            valid_from=timestamp,
            tags=f"session:{session_id}",
            source_origin=source_origin,
        )

        # Mine tool results if present
        if self.mine_tool_results:
            self._mine_tool_results(msg, stats, session_id, line_num, timestamp)

    def _mine_tool_results(
        self, msg: dict, stats: IngestStats, session_id: str, line_num: int,
        timestamp: Optional[str] = None,
    ) -> None:
        """Extract knowledge from tool call results in a message.

        Looks for tool_calls/tool_results in the message structure
        and extracts meaningful content as derived knowledge.
        """
        # Check for tool results in various formats
        tool_results = []

        # OpenClaw format: content is list with tool results
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    tool_type = part.get("type", "")
                    if tool_type == "tool_result":
                        tool_results.append({
                            "name": part.get("tool_use_id", "unknown"),
                            "output": part.get("content", ""),
                        })

        # Alternative: tool_calls field
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict):
                tool_results.append({
                    "name": tc.get("function", {}).get("name", tc.get("name", "unknown")),
                    "output": tc.get("result", tc.get("output", "")),
                })

        # Alternative: tool_result role
        if msg.get("role") == "tool":
            tool_results.append({
                "name": msg.get("name", "unknown"),
                "output": msg.get("content", ""),
            })

        # Process each tool result
        for tr in tool_results:
            output = tr["output"]
            if isinstance(output, dict):
                output = json.dumps(output, indent=2)
            elif isinstance(output, list):
                output = "\n".join(str(item) for item in output)

            output = str(output).strip()
            if len(output) < self.min_msg_length:
                continue

            # Skip very long outputs (likely raw data dumps)
            if len(output) > 10000:
                output = output[:5000] + f"\n... [truncated, {len(output)} chars total]"

            tool_content = f"[Tool: {tr['name']}] {output}"
            self._learn_entry(
                tool_content,
                stats,
                summary=f"Tool result: {tr['name']}",
                source_ref=f"session:{session_id}:line:{line_num}:tool:{tr['name']}",
                valid_from=timestamp,
                tags=f"tool_result,session:{session_id}",
                source_origin="derived",
                data_layer="operational",
            )

    def can_handle(self, source: str | Path) -> bool:
        """Check if source looks like a chat JSONL file."""
        path = Path(source)
        return path.suffix == ".jsonl" and path.exists()
