# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML MCP Server — Model Context Protocol interface for UAML.

Provides 4 MCP tools:
  - memory_search: Full-text search with temporal and client isolation
  - memory_learn: Store new knowledge entries
  - memory_entity: Look up entities and their connections
  - memory_stats: Database statistics

And 2 MCP resources:
  - uaml://stats: Current database statistics
  - uaml://schema: Database schema information

Supports both stdio and HTTP/SSE transports.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

from uaml.core.store import MemoryStore


# ── Tool Definitions ─────────────────────────────────────────

TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Search the UAML knowledge base using full-text search. "
            "Supports temporal queries (point-in-time), client isolation, "
            "and filtering by topic, project, or agent. "
            "Use this to recall facts, decisions, or context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (supports FTS5: AND, OR, NOT, phrases)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default: 5)",
                    "default": 5
                },
                "topic": {
                    "type": "string",
                    "description": "Filter by topic"
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project"
                },
                "client_ref": {
                    "type": "string",
                    "description": "Client reference for data isolation"
                },
                "at_time": {
                    "type": "string",
                    "description": "ISO date for point-in-time query (temporal)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "memory_learn",
        "description": (
            "Store a new knowledge entry in the UAML memory. "
            "Automatically deduplicates identical content. "
            "Supports temporal validity, confidence scoring, and client isolation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Knowledge content to store"
                },
                "topic": {
                    "type": "string",
                    "description": "Topic for categorization",
                    "default": ""
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary",
                    "default": ""
                },
                "source_ref": {
                    "type": "string",
                    "description": "Source reference (URL, file, session ID)",
                    "default": ""
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags",
                    "default": ""
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0-1 (default: 0.8)",
                    "default": 0.8
                },
                "project": {
                    "type": "string",
                    "description": "Project name"
                },
                "client_ref": {
                    "type": "string",
                    "description": "Client reference for isolation"
                },
                "valid_from": {
                    "type": "string",
                    "description": "Valid from date (ISO format)"
                },
                "valid_until": {
                    "type": "string",
                    "description": "Valid until date (ISO format)"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "memory_entity",
        "description": (
            "Look up an entity by name and return its knowledge connections. "
            "Useful for finding all knowledge related to a person, tool, or concept."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Entity name to look up"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "memory_stats",
        "description": "Get UAML database statistics: entry counts, topics, agents.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "task_create",
        "description": (
            "Create a new task in UAML. Tasks can be linked to projects, "
            "assigned to agents, and connected to knowledge entries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description", "default": ""},
                "status": {"type": "string", "description": "Status: todo, in_progress, done, blocked", "default": "todo"},
                "project": {"type": "string", "description": "Project name"},
                "assigned_to": {"type": "string", "description": "Agent ID"},
                "priority": {"type": "integer", "description": "0=normal, 1=high, 2=urgent", "default": 0},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "client_ref": {"type": "string", "description": "Client reference for isolation"},
            },
            "required": ["title"]
        }
    },
    {
        "name": "task_list",
        "description": "List tasks with optional filters (status, project, assigned_to, client).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status"},
                "project": {"type": "string", "description": "Filter by project"},
                "assigned_to": {"type": "string", "description": "Filter by assignee"},
                "client_ref": {"type": "string", "description": "Client reference for isolation"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            }
        }
    },
    {
        "name": "task_update",
        "description": "Update a task's status, assignment, or other fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID to update"},
                "status": {"type": "string", "description": "New status"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "assigned_to": {"type": "string", "description": "New assignee"},
                "priority": {"type": "integer", "description": "New priority"},
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "memory_ethics_check",
        "description": (
            "Check content against UAML ethics rules before storing. "
            "Returns APPROVED, FLAGGED, or REJECTED verdict with details. "
            "Use this to pre-validate content before calling memory_learn."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Content to check against ethics rules"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "memory_focus_recall",
        "description": (
            "Intelligent memory recall with Focus Engine — manages token budget, "
            "temporal decay, sensitivity filtering, and deduplication. "
            "Returns selected records within the configured token budget, "
            "plus a token usage report and decision audit trail. "
            "Use this instead of memory_search for production context building."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for recall"
                },
                "preset": {
                    "type": "string",
                    "description": "Focus Engine preset: conservative (default), standard, research",
                    "default": "conservative",
                    "enum": ["conservative", "standard", "research"]
                },
                "token_budget": {
                    "type": "integer",
                    "description": "Override token budget (default: from preset)"
                },
                "model_context_window": {
                    "type": "integer",
                    "description": "Model's context window size (default: 128000)",
                    "default": 128000
                },
                "topic": {
                    "type": "string",
                    "description": "Filter by topic"
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project"
                },
                "client_ref": {
                    "type": "string",
                    "description": "Client reference for data isolation"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_guide",
        "description": (
            "Get the UAML AI Agent Integration Guide — includes Quick Start, "
            "API reference, Focus Engine tuning, license tier feature matrix, "
            "best practices, and upgrade recommendations. "
            "Use this as your first call after connecting to UAML."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Document type: guide (full integration guide), api (API reference), features (license tier matrix)",
                    "default": "guide",
                    "enum": ["guide", "api", "features"]
                }
            }
        }
    }
]

RESOURCES = [
    {
        "uri": "uaml://stats",
        "name": "UAML Statistics",
        "description": "Current database statistics",
        "mimeType": "application/json"
    },
    {
        "uri": "uaml://schema",
        "name": "UAML Schema",
        "description": "Database schema version and structure",
        "mimeType": "application/json"
    }
]


# ── Tool Handlers ────────────────────────────────────────────

def handle_tool(store: MemoryStore, name: str, arguments: dict) -> dict:
    """Execute a tool call and return the result."""

    if name == "memory_search":
        results = store.search(
            arguments["query"],
            limit=arguments.get("limit", 5),
            topic=arguments.get("topic"),
            project=arguments.get("project"),
            client_ref=arguments.get("client_ref"),
            point_in_time=arguments.get("at_time"),
        )
        return {
            "results": [
                {
                    "id": r.entry.id,
                    "score": round(r.score, 4),
                    "topic": r.entry.topic,
                    "summary": r.entry.summary,
                    "content": r.entry.content[:500],
                    "source_ref": r.entry.source_ref,
                    "confidence": r.entry.confidence,
                    "valid_from": r.entry.valid_from,
                    "valid_until": r.entry.valid_until,
                    "tags": r.entry.tags,
                }
                for r in results
            ],
            "count": len(results),
        }

    elif name == "memory_learn":
        entry_id = store.learn(
            arguments["content"],
            topic=arguments.get("topic", ""),
            summary=arguments.get("summary", ""),
            source_ref=arguments.get("source_ref", ""),
            tags=arguments.get("tags", ""),
            confidence=arguments.get("confidence", 0.8),
            project=arguments.get("project"),
            client_ref=arguments.get("client_ref"),
            valid_from=arguments.get("valid_from"),
            valid_until=arguments.get("valid_until"),
        )
        return {"id": entry_id, "status": "stored"}

    elif name == "memory_entity":
        entity = store.get_entity(arguments["name"])
        if entity is None:
            return {"error": f"Entity '{arguments['name']}' not found"}
        return entity

    elif name == "memory_stats":
        return store.stats()

    elif name == "task_create":
        task_id = store.create_task(
            arguments["title"],
            description=arguments.get("description", ""),
            status=arguments.get("status", "todo"),
            project=arguments.get("project"),
            assigned_to=arguments.get("assigned_to"),
            priority=arguments.get("priority", 0),
            tags=arguments.get("tags", ""),
            client_ref=arguments.get("client_ref"),
        )
        return {"id": task_id, "status": "created"}

    elif name == "task_list":
        tasks = store.list_tasks(
            status=arguments.get("status"),
            project=arguments.get("project"),
            assigned_to=arguments.get("assigned_to"),
            client_ref=arguments.get("client_ref"),
            limit=arguments.get("limit", 20),
        )
        return {"tasks": tasks, "count": len(tasks)}

    elif name == "task_update":
        task_id = arguments.pop("task_id")
        ok = store.update_task(task_id, **arguments)
        return {"task_id": task_id, "updated": ok}

    elif name == "memory_ethics_check":
        from uaml.ethics.checker import EthicsChecker
        checker = EthicsChecker()
        verdict = checker.check(arguments["content"])
        return verdict.to_dict()

    elif name == "memory_focus_recall":
        from uaml.core.focus_config import load_preset
        preset_name = arguments.get("preset", "conservative")
        config = load_preset(preset_name)
        # Override token budget if specified
        if "token_budget" in arguments:
            config.output_filter.token_budget_per_query = arguments["token_budget"]
        result = store.focus_recall(
            arguments["query"],
            focus_config=config,
            model_context_window=arguments.get("model_context_window", 128000),
            topic=arguments.get("topic"),
            project=arguments.get("project"),
            client_ref=arguments.get("client_ref"),
        )
        return result

    elif name == "memory_recall":
        results = store.policy_recall(
            arguments["query"],
            query_class=arguments.get("query_class", "general"),
            model_profile=arguments.get("model_profile", "standard"),
        )
        return {
            "results": [
                {
                    "id": r.entry.id,
                    "content": r.entry.content[:500],
                    "topic": r.entry.topic,
                    "score": round(r.score, 4),
                }
                for r in results
            ],
            "count": len(results),
        }

    elif name == "memory_proactive":
        results = store.proactive_recall(
            arguments["context"],
            limit=arguments.get("limit", 5),
        )
        return {
            "results": [
                {
                    "content": r.get("content", "")[:500] if isinstance(r, dict) else str(r)[:500],
                }
                for r in results
            ],
            "count": len(results),
        }

    elif name == "memory_capture_reasoning":
        trace_id = store.capture_reasoning(
            arguments["decision"],
            reasoning=arguments.get("reasoning", ""),
            confidence=arguments.get("confidence", 0.8),
        )
        return {"trace_id": trace_id, "status": "captured"}

    elif name == "memory_compliance_audit":
        from uaml.compliance.auditor import ComplianceAuditor
        auditor = ComplianceAuditor(store)
        report = auditor.full_audit()
        return {
            "score": report.score(),
            "passed": report.passed(),
            "failed": report.failed(),
            "critical": len(report.critical_findings()),
        }

    elif name == "memory_purge":
        result = store.purge(
            older_than_days=arguments.get("older_than_days"),
            data_layer=arguments.get("data_layer"),
            client_ref=arguments.get("client_ref"),
            confidence_below=arguments.get("confidence_below"),
            dry_run=arguments.get("dry_run", True),
        )
        return result

    elif name == "memory_context_summary":
        result = store.context_summary(
            size=arguments.get("size", "standard"),
            topic=arguments.get("topic"),
            project=arguments.get("project"),
        )
        return result

    elif name == "get_guide":
        from uaml.docs import get_guide, get_api_reference, get_feature_matrix
        doc_type = arguments.get("type", "guide")
        if doc_type == "api":
            return {"content": get_api_reference(), "type": "api_reference"}
        elif doc_type == "features":
            return {"content": get_feature_matrix(), "type": "feature_matrix"}
        else:
            return {"content": get_guide(), "type": "agent_guide"}

    else:
        return {"error": f"Unknown tool: {name}"}


def handle_resource(store: MemoryStore, uri: str) -> dict:
    """Read a resource and return its content."""
    if uri == "uaml://stats":
        return store.stats()
    elif uri == "uaml://schema":
        from uaml.core.schema import SCHEMA_VERSION
        return {
            "version": SCHEMA_VERSION,
            "tables": ["knowledge", "team_knowledge", "personality",
                       "entities", "entity_mentions", "knowledge_relations",
                       "audit_log", "session_summaries", "schema_version"],
        }
    else:
        return {"error": f"Unknown resource: {uri}"}


# ── JSON-RPC Protocol ────────────────────────────────────────

def make_response(id: Any, result: Any) -> dict:
    """Create a JSON-RPC 2.0 response."""
    return {"jsonrpc": "2.0", "id": id, "result": result}


def make_error(id: Any, code: int, message: str) -> dict:
    """Create a JSON-RPC 2.0 error response."""
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def handle_message(store: MemoryStore, msg: dict) -> Optional[dict]:
    """Handle a single JSON-RPC 2.0 message."""
    method = msg.get("method", "")
    params = msg.get("params", {})
    msg_id = msg.get("id")

    # Notifications (no id) — no response
    if msg_id is None and method == "notifications/initialized":
        return None

    if method == "initialize":
        return make_response(msg_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False},
            },
            "serverInfo": {
                "name": "uaml",
                "version": "0.1.0",
            }
        })

    elif method == "tools/list":
        return make_response(msg_id, {"tools": TOOLS})

    elif method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            result = handle_tool(store, name, arguments)
            return make_response(msg_id, {
                "content": [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                ]
            })
        except Exception as e:
            return make_error(msg_id, -32000, str(e))

    elif method == "resources/list":
        return make_response(msg_id, {"resources": RESOURCES})

    elif method == "resources/read":
        uri = params.get("uri", "")
        try:
            result = handle_resource(store, uri)
            return make_response(msg_id, {
                "contents": [
                    {"uri": uri, "mimeType": "application/json",
                     "text": json.dumps(result, ensure_ascii=False, indent=2)}
                ]
            })
        except Exception as e:
            return make_error(msg_id, -32000, str(e))

    elif method == "ping":
        return make_response(msg_id, {})

    else:
        return make_error(msg_id, -32601, f"Method not found: {method}")


# ── Transport: stdio ─────────────────────────────────────────

def run_stdio(store: MemoryStore) -> None:
    """Run MCP server over stdio (stdin/stdout)."""
    import io

    # Use binary mode for consistent line handling
    stdin = sys.stdin.buffer if hasattr(sys.stdin, 'buffer') else sys.stdin
    stdout = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout

    for line in io.TextIOWrapper(stdin, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_message(store, msg)
        if response is not None:
            out = json.dumps(response, ensure_ascii=False) + "\n"
            if hasattr(stdout, 'write'):
                if isinstance(stdout, io.RawIOBase):
                    stdout.write(out.encode('utf-8'))
                else:
                    stdout.write(out.encode('utf-8'))
                stdout.flush()
            else:
                print(out, flush=True)


# ── Transport: HTTP/SSE ──────────────────────────────────────

def run_http(store: MemoryStore, host: str, port: int) -> None:
    """Run MCP server over HTTP with SSE support.

    Uses minimal stdlib HTTP server — no external dependencies.
    """
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class MCPHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')

            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                self.send_error(400, "Invalid JSON")
                return

            response = handle_message(store, msg)
            if response is None:
                self.send_response(204)
                self.end_headers()
                return

            out = json.dumps(response, ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out.encode('utf-8'))))
            self.end_headers()
            self.wfile.write(out.encode('utf-8'))

        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                out = json.dumps({"status": "ok", "version": "0.1.0"})
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out.encode('utf-8'))
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            # Suppress default logging
            pass

    server = HTTPServer((host, port), MCPHandler)
    print(f"UAML MCP Server listening on http://{host}:{port}", file=sys.stderr)
    print(f"  POST / — JSON-RPC 2.0 endpoint", file=sys.stderr)
    print(f"  GET /health — health check", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)
        server.shutdown()


# ── Entry Point ──────────────────────────────────────────────

def run_server(
    db_path: str = "memory.db",
    host: str = "localhost",
    port: int = 8768,
    transport: str = "stdio",
) -> None:
    """Start the UAML MCP server.

    Args:
        db_path: Path to SQLite database
        host: Bind address (HTTP only)
        port: Bind port (HTTP only)
        transport: "stdio" or "http"
    """
    store = MemoryStore(db_path)

    try:
        if transport == "stdio":
            run_stdio(store)
        elif transport == "http":
            run_http(store, host, port)
        else:
            raise ValueError(f"Unknown transport: {transport}")
    finally:
        store.close()
