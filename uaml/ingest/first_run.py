# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML First-Run Discovery & Indexation.

When UAML is installed into an existing OpenClaw system, this module
scans and indexes ALL existing data sources — sessions, memory files,
workspace docs, databases, git history, and config.

Usage:
    python3 -m uaml.ingest.first_run           # full discovery + index
    python3 -m uaml.ingest.first_run --scan     # just show what would be indexed
    python3 -m uaml.ingest.first_run --reindex  # force re-index everything
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Any, Callable, Optional

from uaml.core.store import MemoryStore
from uaml.ingest.base import IngestStats


# Keys in openclaw.json that are safe to index (no secrets)
SAFE_CONFIG_KEYS = {
    "gateway.bind", "gateway.remote.url", "agents", "models",
    "channels", "tools", "skills", "plugins",
}

# Config keys that must NEVER be indexed
SECRET_PATTERNS = re.compile(
    r"(key|token|secret|password|credential|apikey|api_key)", re.IGNORECASE
)


class FirstRunDiscovery:
    """Discover and index all existing OpenClaw data sources."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        state_path: Optional[str | Path] = None,
        agent_id: str = "uaml-indexer",
    ):
        self.store = store
        self.agent_id = agent_id
        self._workspace = os.environ.get(
            "OPENCLAW_WORKSPACE",
            os.path.expanduser("~/.openclaw/workspace"),
        )
        if state_path is None:
            state_path = os.path.join(self._workspace, "data", "first_run_state.json")
        self.state_path = Path(state_path)
        self._state = self._load_state()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_openclaw(self) -> dict[str, Any]:
        """Find all OpenClaw data sources on this system."""
        sources: dict[str, Any] = {}

        # Session files
        sessions_dir = os.path.expanduser("~/.openclaw/agents/")
        for f in sorted(glob(f"{sessions_dir}/*/sessions/*.jsonl")):
            sources.setdefault("sessions", []).append(f)

        # Memory markdown files
        for md in sorted(glob(f"{self._workspace}/memory/*.md")):
            sources.setdefault("memory_files", []).append(md)

        # Key workspace files
        for name in [
            "MEMORY.md", "TOOLS.md", "AGENTS.md", "SOUL.md",
            "USER.md", "IDENTITY.md",
        ]:
            path = os.path.join(self._workspace, name)
            if os.path.exists(path):
                sources.setdefault("workspace_files", []).append(path)

        # Project docs
        for md in sorted(
            glob(f"{self._workspace}/projects/**/*.md", recursive=True)
        ):
            sources.setdefault("project_docs", []).append(md)

        # Existing databases
        for db_name in [
            "chat_history.db", "todo.db", "file_registry.db", "summary_index.db",
        ]:
            for search_dir in [
                self._workspace,
                os.path.join(self._workspace, "data"),
            ]:
                path = os.path.join(search_dir, db_name)
                if os.path.exists(path):
                    sources.setdefault("databases", []).append(path)

        # Git repos
        if os.path.exists(os.path.join(self._workspace, ".git")):
            sources.setdefault("git_repos", []).append(self._workspace)

        # OpenClaw config
        config = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config):
            sources["config"] = config

        return sources

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"indexed": {}, "last_run": None, "total_records": 0}

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state, indent=2))

    def _needs_indexing(self, path: str, force: bool = False) -> bool:
        """Check if a file needs (re-)indexing."""
        if force:
            return True
        prev = self._state["indexed"].get(path)
        if prev is None:
            return True
        try:
            mtime = os.path.getmtime(path)
            return mtime > prev.get("mtime", 0)
        except OSError:
            return False

    def _mark_indexed(self, path: str, count: int):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = time.time()
        self._state["indexed"][path] = {
            "mtime": mtime,
            "count": count,
            "indexed_at": datetime.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Indexation per source type
    # ------------------------------------------------------------------

    def index_source(self, source_type: str, path: str, force: bool = False) -> IngestStats:
        """Index a single source. Returns stats."""
        stats = IngestStats(source=path, source_type=source_type)

        if not self._needs_indexing(path, force):
            stats.entries_skipped = 1
            stats.details["reason"] = "already indexed, not modified"
            return stats

        try:
            handler = {
                "sessions": self._index_session,
                "memory_files": self._index_markdown,
                "workspace_files": self._index_markdown,
                "project_docs": self._index_project_doc,
                "databases": self._index_database,
                "git_repos": self._index_git,
                "config": self._index_config,
            }.get(source_type)

            if handler is None:
                stats.errors = 1
                stats.details["error"] = f"Unknown source type: {source_type}"
                return stats

            count = handler(path, source_type)
            stats.entries_created = count
            self._mark_indexed(path, count)
        except Exception as e:
            stats.errors = 1
            stats.details["error"] = str(e)

        return stats

    def _index_session(self, path: str, source_type: str) -> int:
        """Parse JSONL session, extract messages."""
        from uaml.ingest.chat import ChatIngestor
        ingestor = ChatIngestor(self.store)
        result = ingestor.ingest(path)
        return result.entries_created

    def _index_markdown(self, path: str, source_type: str) -> int:
        """Split markdown by ## headers, index each section."""
        from uaml.ingest.markdown import MarkdownIngestor
        ingestor = MarkdownIngestor(self.store)
        result = ingestor.ingest(path, split_sections=True)
        return result.entries_created

    def _index_project_doc(self, path: str, source_type: str) -> int:
        """Index project doc with project metadata."""
        # Extract project name from path
        rel = os.path.relpath(path, self._workspace)
        parts = rel.split(os.sep)
        project = ""
        if len(parts) >= 3 and parts[0] == "projects":
            project = parts[2] if parts[1] in ("_active", "_archive") else parts[1]

        from uaml.ingest.markdown import MarkdownIngestor
        ingestor = MarkdownIngestor(self.store, default_project=project)
        result = ingestor.ingest(path, split_sections=True)
        return result.entries_created

    def _index_database(self, path: str, source_type: str) -> int:
        """Extract records from legacy SQLite databases."""
        db_name = os.path.basename(path)
        count = 0
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row

            if db_name == "chat_history.db":
                count = self._index_chat_db(conn, path)
            elif db_name == "todo.db":
                count = self._index_todo_db(conn, path)
            elif db_name == "file_registry.db":
                count = self._index_file_registry(conn, path)
            elif db_name == "summary_index.db":
                count = self._index_summary_db(conn, path)

            conn.close()
        except sqlite3.Error as e:
            raise RuntimeError(f"Failed to read {path}: {e}")
        return count

    def _index_chat_db(self, conn: sqlite3.Connection, path: str) -> int:
        """Index chat_history.db — table: chat_messages."""
        count = 0
        try:
            rows = conn.execute(
                "SELECT id, session_id, role, text, ts FROM chat_messages "
                "WHERE length(text) > 30 ORDER BY ts LIMIT 10000"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            ref = f"db:chat_history:chat_messages:{row['id']}"
            self.store.learn(
                row["text"][:2000],
                agent_id=self.agent_id,
                source_type="legacy_db",
                source_ref=ref,
                topic=f"chat:{row['session_id'] or 'unknown'}",
                data_layer="operational",
                confidence=0.6,
            )
            count += 1
        return count

    def _index_todo_db(self, conn: sqlite3.Connection, path: str) -> int:
        """Index todo.db — table: entries."""
        count = 0
        try:
            rows = conn.execute(
                "SELECT e.id, e.text, e.status, g.name as grp "
                "FROM entries e LEFT JOIN groups g ON e.group_id = g.id "
                "ORDER BY e.id"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            content = f"[{row['status']}] {row['text']} (group: {row['grp'] or 'none'})"
            ref = f"db:todo:entries:{row['id']}"
            self.store.learn(
                content,
                agent_id=self.agent_id,
                source_type="legacy_db",
                source_ref=ref,
                topic="todo",
                data_layer="operational",
                confidence=0.7,
            )
            count += 1
        return count

    def _index_file_registry(self, conn: sqlite3.Connection, path: str) -> int:
        """Index file_registry.db — table: documents."""
        count = 0
        try:
            rows = conn.execute(
                "SELECT id, path, notes, project FROM documents ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            content = f"File: {row['path']}"
            if row["notes"]:
                content += f" — {row['notes']}"
            ref = f"db:file_registry:documents:{row['id']}"
            self.store.learn(
                content,
                agent_id=self.agent_id,
                source_type="legacy_db",
                source_ref=ref,
                topic="file_registry",
                project=row.get("project", ""),
                data_layer="operational",
                confidence=0.7,
            )
            count += 1
        return count

    def _index_summary_db(self, conn: sqlite3.Connection, path: str) -> int:
        """Index summary_index.db — table: summaries."""
        count = 0
        try:
            rows = conn.execute(
                "SELECT id, date_key, kind, body FROM summaries ORDER BY date_key"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0

        for row in rows:
            ref = f"db:summary_index:summaries:{row['id']}"
            self.store.learn(
                row["body"][:3000],
                agent_id=self.agent_id,
                source_type="legacy_db",
                source_ref=ref,
                topic=f"summary:{row['kind']}",
                data_layer="knowledge",
                confidence=0.8,
            )
            count += 1
        return count

    def _index_git(self, path: str, source_type: str) -> int:
        """Index last 100 git commits."""
        count = 0
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--no-decorate", "-100"],
                capture_output=True, text=True, cwd=path, timeout=30,
            )
            if result.returncode != 0:
                return 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return 0

        for line in result.stdout.strip().splitlines():
            if len(line) < 10:
                continue
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue
            sha, msg = parts
            ref = f"git:{sha}"
            self.store.learn(
                f"Commit {sha}: {msg}",
                agent_id=self.agent_id,
                source_type="git",
                source_ref=ref,
                topic="git_history",
                data_layer="operational",
                confidence=0.9,
            )
            count += 1
        return count

    def _index_config(self, path: str, source_type: str) -> int:
        """Index safe config keys (never secrets)."""
        try:
            raw = Path(path).read_text()
            # Strip comments (JSON5)
            raw = re.sub(r"//.*$", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
            config = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            return 0

        count = 0
        safe_entries = self._extract_safe_config(config)
        for key, value in safe_entries:
            content = f"OpenClaw config: {key} = {value}"
            ref = f"config:{key}"
            self.store.learn(
                content,
                agent_id=self.agent_id,
                source_type="config",
                source_ref=ref,
                topic="openclaw_config",
                data_layer="operational",
                confidence=0.95,
            )
            count += 1
        return count

    def _extract_safe_config(
        self, obj: Any, prefix: str = ""
    ) -> list[tuple[str, str]]:
        """Recursively extract non-secret config entries."""
        entries = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}.{k}" if prefix else k
                if SECRET_PATTERNS.search(k):
                    continue  # skip secrets
                if isinstance(v, (dict, list)):
                    entries.extend(self._extract_safe_config(v, full_key))
                else:
                    val_str = str(v)
                    if SECRET_PATTERNS.search(val_str):
                        continue
                    if len(val_str) > 200:
                        val_str = val_str[:200] + "..."
                    entries.append((full_key, val_str))
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:20]):  # cap list items
                entries.extend(
                    self._extract_safe_config(item, f"{prefix}[{i}]")
                )
        return entries

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        force: bool = False,
        callback: Optional[Callable] = None,
    ) -> dict[str, IngestStats]:
        """Run full discovery + indexation with progress.

        Returns dict of source_type → aggregated IngestStats.
        """
        sources = self.discover_openclaw()
        total_files = sum(
            len(v) if isinstance(v, list) else 1 for v in sources.values()
        )
        processed = 0
        results: dict[str, IngestStats] = {}

        for source_type, paths in sources.items():
            agg = IngestStats(source=source_type, source_type=source_type)
            path_list = paths if isinstance(paths, list) else [paths]
            for path in path_list:
                stats = self.index_source(source_type, path, force=force)
                agg.entries_created += stats.entries_created
                agg.entries_skipped += stats.entries_skipped
                agg.errors += stats.errors
                processed += 1
                if callback:
                    callback(processed, total_files, source_type, path)
            results[source_type] = agg

        self._state["last_run"] = datetime.utcnow().isoformat()
        self._state["total_records"] = sum(
            s.entries_created for s in results.values()
        )
        self._save_state()
        return results

    def scan(self) -> dict[str, Any]:
        """Scan only — show what would be indexed without indexing."""
        sources = self.discover_openclaw()
        report: dict[str, Any] = {}
        for source_type, paths in sources.items():
            path_list = paths if isinstance(paths, list) else [paths]
            items = []
            for p in path_list:
                needs = self._needs_indexing(p)
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                items.append({
                    "path": p,
                    "needs_indexing": needs,
                    "size_bytes": size,
                })
            report[source_type] = items
        return report


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def _print_progress(processed: int, total: int, source_type: str, path: str):
    short = os.path.basename(path)
    pct = int(processed / total * 100) if total else 0
    print(f"  [{processed}/{total} {pct}%] {source_type}: {short}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="UAML First-Run Discovery — index existing OpenClaw data"
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Show what would be indexed without indexing",
    )
    parser.add_argument(
        "--reindex", action="store_true",
        help="Force re-index everything (ignore previous state)",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to UAML memory.db (default: data/memory.db)",
    )
    args = parser.parse_args()

    workspace = os.environ.get(
        "OPENCLAW_WORKSPACE",
        os.path.expanduser("~/.openclaw/workspace"),
    )
    db_path = args.db or os.path.join(workspace, "data", "memory.db")

    store = MemoryStore(db_path, agent_id="uaml-indexer")

    discovery = FirstRunDiscovery(store)

    if args.scan:
        print("[UAML] Scanning for data sources...\n")
        report = discovery.scan()
        total = 0
        for stype, items in report.items():
            needs = [i for i in items if i["needs_indexing"]]
            skip = len(items) - len(needs)
            total_size = sum(i["size_bytes"] for i in needs)
            print(f"  {stype}: {len(needs)} new, {skip} already indexed "
                  f"({total_size / 1024:.0f} KB)")
            total += len(needs)
        print(f"\nTotal: {total} sources to index")
        if total > 0:
            print("Run without --scan to index.")
        return

    print(f"[UAML] First-run discovery — indexing into {db_path}")
    print()

    results = discovery.run(force=args.reindex, callback=_print_progress)

    print("\n" + "=" * 50)
    print("Results:")
    total_created = 0
    total_skipped = 0
    total_errors = 0
    for stype, stats in results.items():
        total_created += stats.entries_created
        total_skipped += stats.entries_skipped
        total_errors += stats.errors
        print(f"  {stype}: {stats.entries_created} created, "
              f"{stats.entries_skipped} skipped, {stats.errors} errors")
    print(f"\nTotal: {total_created} records created, "
          f"{total_skipped} skipped, {total_errors} errors")

    store.close()


if __name__ == "__main__":
    main()
