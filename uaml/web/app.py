# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Web Application — serves dashboard + REST API.

Usage:
    from uaml.web.app import UAMLWebApp
    app = UAMLWebApp(db_path="memory.db")
    app.serve(host="127.0.0.1", port=8780)

Or via CLI:
    uaml web --port 8780
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from ..core.store import MemoryStore

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


class UAMLRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for UAML web dashboard."""

    store: MemoryStore  # Set by UAMLWebApp

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_json(self, data: dict | list, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())

    def _send_html(self, html: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _find_todo_db(self) -> Optional[str]:
        """Find todo.db relative to memory.db or workspace."""
        store = self.__class__.store
        db_dir = Path(store.db_path).parent
        candidates = [
            db_dir / "todo.db",
            db_dir.parent / "todo.db",
            Path.home() / ".openclaw" / "workspace" / "todo.db",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    def _send_static(self, path: str):
        """Serve static file."""
        file_path = STATIC_DIR / path.lstrip("/")
        if not file_path.is_file() or ".." in path:
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(str(file_path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def _render_page(self, page: str, **context):
        """Render a page template with layout."""
        layout = (TEMPLATES_DIR / "layout.html").read_text()
        try:
            content = (TEMPLATES_DIR / f"{page}.html").read_text()
        except FileNotFoundError:
            content = f"<h1>Page not found: {page}</h1>"

        html = layout.replace("{{CONTENT}}", content)
        html = html.replace("{{PAGE}}", page)
        for key, value in context.items():
            html = html.replace(f"{{{{{key}}}}}", str(value))
        self._send_html(html)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # Static files
        if path.startswith("/static/"):
            self._send_static(path[8:])
            return

        # API endpoints
        if path.startswith("/api/"):
            self._handle_api(path, params)
            return

        # Pages
        page_map = {
            "/": "dashboard",
            "/knowledge": "knowledge",
            "/tasks": "tasks",
            "/graph": "graph",
            "/timeline": "timeline",
            "/compliance": "compliance",
            "/export": "export",
            "/settings": "settings",
            "/input-filter": "input-filter",
            "/output-filter": "output-filter",
            "/rules-log": "rules-log",
            "/infrastructure": "infrastructure",
            "/team": "team",
            "/projects": "projects",
            "/orchestration": "orchestration",
            "/sanitize": "sanitize",
            "/license": "license",
        }

        page = page_map.get(path)
        if page:
            self._render_page(page)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            self._handle_api_post(parsed.path, body)
        else:
            self.send_error(405)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len)) if content_len else {}
            self._handle_api_put(parsed.path, body)
        else:
            self.send_error(405)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/coordination/rules/"):
            try:
                rule_id = int(parsed.path.split("/")[-1])
                det = self._get_coordinator()
                det.delete_rule(rule_id)
                self._send_json({"status": "deleted", "id": rule_id})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ─── API Handlers ─────────────────────────────────────────────

    def _handle_api(self, path: str, params: dict):
        store = self.__class__.store

        if path == "/api/system":
            import platform
            import os
            try:
                hostname = platform.node()
            except Exception:
                hostname = "unknown"
            try:
                uname = platform.uname()
                hw_info = {
                    "os": f"{uname.system} {uname.release}",
                    "arch": uname.machine,
                    "hostname": hostname,
                    "python": platform.python_version(),
                }
            except Exception:
                hw_info = {"hostname": hostname}

            # CPU info
            try:
                cpu_count = os.cpu_count() or 0
                hw_info["cpu_cores"] = cpu_count
            except Exception:
                pass

            # Memory info
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal"):
                            mem_kb = int(line.split()[1])
                            hw_info["ram_gb"] = round(mem_kb / 1024 / 1024, 1)
                            break
            except Exception:
                pass

            # GPU info (nvidia-smi)
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    gpus = []
                    for line in result.stdout.strip().split("\n"):
                        if line.strip():
                            parts = line.split(", ")
                            gpus.append({
                                "name": parts[0].strip(),
                                "vram_mb": int(parts[1].strip()) if len(parts) > 1 else 0,
                            })
                    hw_info["gpus"] = gpus
            except Exception:
                pass

            # DB size
            try:
                db_path = store.db_path if hasattr(store, 'db_path') else None
                if db_path and os.path.exists(str(db_path)):
                    hw_info["db_size_bytes"] = os.path.getsize(str(db_path))
            except Exception:
                pass

            agent_name = os.environ.get("UAML_AGENT") or getattr(store, 'agent_id', None) or "Cyril"
            agent_model = os.environ.get("UAML_MODEL", "Claude Opus 4.6")
            agent_fw = os.environ.get("UAML_FRAMEWORK", "OpenClaw")

            # DB paths (absolute)
            db_path_str = ""
            try:
                db_path_obj = store.db_path if hasattr(store, 'db_path') else None
                if db_path_obj:
                    db_path_str = str(Path(str(db_path_obj)).resolve())
            except Exception:
                pass
            todo_db_path = self._find_todo_db()
            todo_path_str = str(todo_db_path) if todo_db_path else None

            system = {
                "versions": {
                    "uaml": "1.0.0",
                    "mcp": "1.0",
                    "dashboard": "1.0",
                    "api": "v1",
                },
                "machine": hw_info,
                "database": {
                    "knowledge_db": db_path_str,
                    "todo_db": todo_path_str,
                    "size_bytes": hw_info.get("db_size_bytes", 0),
                },
                "agent": {
                    "name": agent_name,
                    "model": agent_model,
                    "framework": agent_fw,
                },
            }
            self._send_json(system)
            return

        if path == "/api/stats":
            stats = {
                "knowledge": store._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0],
                "layers": {},
            }
            for row in store._conn.execute(
                "SELECT data_layer, COUNT(*) FROM knowledge GROUP BY data_layer"
            ).fetchall():
                stats["layers"][row[0] or "unknown"] = row[1]

            # Tasks count — from todo.db (live data)
            todo_db = self._find_todo_db()
            if todo_db:
                import sqlite3 as _sql
                try:
                    c = _sql.connect(todo_db)
                    stats["tasks"] = c.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
                    for row in c.execute("SELECT status, COUNT(*) FROM entries GROUP BY status").fetchall():
                        stats.setdefault("task_status", {})[row[0]] = row[1]
                    stats["task_groups"] = c.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
                    c.close()
                except Exception:
                    stats["tasks"] = 0
            else:
                try:
                    stats["tasks"] = store._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                except Exception:
                    stats["tasks"] = 0

            # Reasoning traces
            try:
                stats["reasoning_traces"] = store._conn.execute(
                    "SELECT COUNT(*) FROM reasoning_traces"
                ).fetchone()[0]
            except Exception:
                stats["reasoning_traces"] = 0

            self._send_json(stats)

        elif path == "/api/knowledge":
            q = params.get("q", [""])[0]
            layer = params.get("layer", [""])[0]
            limit = int(params.get("limit", ["50"])[0])
            offset = int(params.get("offset", ["0"])[0])

            if q:
                results = store.search(q, limit=limit)
                entries = [{
                    "id": r.entry.id,
                    "content": r.entry.content,
                    "topic": r.entry.topic,
                    "tags": r.entry.tags,
                    "confidence": r.entry.confidence,
                    "data_layer": r.entry.data_layer,
                    "source_origin": r.entry.source_origin,
                    "created_at": r.entry.created_at,
                    "score": r.score,
                } for r in results]
            else:
                where = "WHERE data_layer = ?" if layer else ""
                p = [layer] if layer else []
                rows = store._conn.execute(
                    f"SELECT id, content, topic, tags, confidence, data_layer, source_origin, created_at "
                    f"FROM knowledge {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                    p + [limit, offset]
                ).fetchall()
                entries = [{
                    "id": r[0], "content": r[1], "topic": r[2], "tags": r[3],
                    "confidence": r[4], "data_layer": r[5], "source_origin": r[6],
                    "created_at": r[7],
                } for r in rows]

            self._send_json({"entries": entries, "count": len(entries)})

        elif path.startswith("/api/knowledge/"):
            entry_id = int(path.split("/")[-1])
            row = store._conn.execute(
                "SELECT * FROM knowledge WHERE id = ?", (entry_id,)
            ).fetchone()
            if row:
                cols = [d[0] for d in store._conn.execute("SELECT * FROM knowledge LIMIT 0").description]
                self._send_json(dict(zip(cols, row)))
            else:
                self._send_json({"error": "not found"}, 404)

        elif path == "/api/tasks":
            # Read tasks from todo.db (live data, same as TODO dashboard)
            todo_db = self._find_todo_db()
            if todo_db:
                import sqlite3 as _sql
                c = _sql.connect(todo_db)
                status_filter = params.get("status", [""])[0]
                group_filter = params.get("group", [""])[0]
                limit = int(params.get("limit", ["100"])[0])
                offset = int(params.get("offset", ["0"])[0])

                where_parts = []
                p = []
                if status_filter:
                    where_parts.append("e.status = ?")
                    p.append(status_filter)
                if group_filter:
                    where_parts.append("e.group_id = ?")
                    p.append(int(group_filter))
                where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

                rows = c.execute(
                    f"SELECT e.id, e.text, e.status, e.group_id, g.name as group_name, "
                    f"e.created_at, e.updated_at "
                    f"FROM entries e LEFT JOIN groups g ON e.group_id = g.id "
                    f"{where} ORDER BY e.updated_at DESC, e.id DESC LIMIT ? OFFSET ?",
                    p + [limit, offset]
                ).fetchall()
                tasks = [{
                    "id": r[0], "text": r[1], "status": r[2],
                    "group_id": r[3], "group_name": r[4],
                    "created_at": r[5], "updated_at": r[6],
                } for r in rows]

                # Stats
                stats = {}
                for row in c.execute("SELECT status, COUNT(*) FROM entries GROUP BY status").fetchall():
                    stats[row[0]] = row[1]
                total = sum(stats.values())

                c.close()
                self._send_json({"tasks": tasks, "count": len(tasks), "total": total, "stats": stats})
            else:
                # Fallback to internal tasks table
                try:
                    rows = store._conn.execute(
                        "SELECT * FROM tasks ORDER BY id DESC LIMIT 100"
                    ).fetchall()
                    cols = [d[0] for d in store._conn.execute("SELECT * FROM tasks LIMIT 0").description]
                    tasks = [dict(zip(cols, r)) for r in rows]
                    self._send_json({"tasks": tasks, "count": len(tasks)})
                except Exception:
                    self._send_json({"tasks": [], "count": 0})

        elif path == "/api/timeline":
            limit = int(params.get("limit", ["100"])[0])
            rows = store._conn.execute(
                "SELECT id, content, topic, data_layer, created_at FROM knowledge "
                "ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            items = [{
                "id": r[0], "content": r[1][:200], "topic": r[2],
                "layer": r[3], "timestamp": r[4], "type": "knowledge",
            } for r in rows]
            self._send_json({"items": items})

        elif path == "/api/layers":
            rows = store._conn.execute(
                "SELECT data_layer, COUNT(*), AVG(confidence) FROM knowledge GROUP BY data_layer"
            ).fetchall()
            layers = [{
                "name": r[0] or "unknown",
                "count": r[1],
                "avg_confidence": round(r[2] or 0, 3),
            } for r in rows]
            self._send_json({"layers": layers})

        elif path == "/api/projects":
            # Serve TODO groups as projects from external todo.db
            todo_db = self._find_todo_db()
            if todo_db:
                import sqlite3 as _sql
                c = _sql.connect(todo_db)
                groups = c.execute(
                    "SELECT g.id, g.name, g.created_at, "
                    "(SELECT COUNT(*) FROM entries WHERE group_id=g.id) as total, "
                    "(SELECT COUNT(*) FROM entries WHERE group_id=g.id AND status='done') as done "
                    "FROM groups g ORDER BY g.id DESC"
                ).fetchall()
                projects = [{
                    "id": r[0], "name": r[1], "created_at": r[2],
                    "total": r[3], "done": r[4],
                    "progress": round(r[4] / r[3] * 100) if r[3] > 0 else 0,
                } for r in groups if r[3] > 0]  # Only show groups with items
                c.close()
                self._send_json({"projects": projects, "count": len(projects)})
            else:
                self._send_json({"projects": [], "count": 0})

        elif path.startswith("/api/projects/"):
            # Get items for a specific group
            group_id = int(path.split("/")[-1])
            todo_db = self._find_todo_db()
            if todo_db:
                import sqlite3 as _sql
                c = _sql.connect(todo_db)
                name = c.execute("SELECT name FROM groups WHERE id=?", (group_id,)).fetchone()
                rows = c.execute(
                    "SELECT id, text, status, created_at, updated_at "
                    "FROM entries WHERE group_id=? ORDER BY status, id", (group_id,)
                ).fetchall()
                items = [{"id": r[0], "text": r[1], "status": r[2], "created_at": r[3], "updated_at": r[4]} for r in rows]
                c.close()
                self._send_json({"name": name[0] if name else "?", "items": items, "count": len(items)})
            else:
                self._send_json({"items": [], "count": 0}, 404)

        elif path == "/api/infrastructure":
            self._send_json({"machines": [
                {"name": "Notebook1 (Cyril)", "role": "GPU Agent, Knowledge Processing",
                 "os": "WSL2 Ubuntu", "ip": "localhost",
                 "hw": "2× RTX 5090 (56 GB VRAM)", "status": "online",
                 "services": ["OpenClaw", "Ollama", "Piper TTS", "Faster-Whisper", "UAML Dashboard"]},
                {"name": "VPS (Metod)", "role": "Coordinator, Infrastructure",
                 "os": "Ubuntu 24.04 LTS", "ip": "5.189.139.221",
                 "hw": "Contabo VPS", "status": "online",
                 "services": ["OpenClaw", "Dashboard (8765)", "Knowledge Browser (8766)", "Memory API (8768)", "PyPI (8769)"]},
                {"name": "Pepa-PC", "role": "GPU Compute, Neo4j Host",
                 "os": "Ubuntu", "ip": "192.168.1.155 / 82.202.14.245",
                 "hw": "RTX 5090 32GB + 249GB RAM", "status": "stopped",
                 "services": ["Neo4j", "Ollama", "ANPR Collector"]},
                {"name": "Test Server (Marketing)", "role": "Marketing Agent, Telemetry, License Server",
                 "os": "Ubuntu 24.04 LTS", "ip": "161.97.184.185",
                 "hw": "Contabo VPS", "status": "online",
                 "services": ["OpenClaw (Marketing)", "Telemetry (8775)", "License Server (8776)", "Postfix/Dovecot", "Neo4j"]},
                {"name": "Web Server", "role": "Websites, Customer Portal",
                 "os": "Ubuntu 24.04 LTS", "ip": "5.189.190.7",
                 "hw": "Contabo VPS", "status": "online",
                 "services": ["uaml.ai", "uaml-memory.com", "Customer Portal", "Neo4j", "Nginx"]},
            ]})

        elif path == "/api/team":
            # Try coordination server first, fallback to static
            try:
                import urllib.request
                coord_urls = ["http://5.189.139.221:8791/agents", "http://127.0.0.1:8791/agents"]
                coord_data = None
                for coord_url in coord_urls:
                    try:
                        req = urllib.request.Request(coord_url, headers={"Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=3) as resp:
                            coord_data = json.loads(resp.read())
                        break
                    except Exception:
                        continue
                if not coord_data:
                    raise ConnectionError("No coordination server available")
                emoji_map = {"coordinator": "🔧", "coder": "🔤", "marketing": "📢",
                             "support": "🌐", "local-compute": "🖥️"}
                members = [{"name": "Pavel (Vedoucí)", "emoji": "👑", "role": "Team Lead",
                            "description": "Human lead, final decisions", "status": "online"}]
                for a in coord_data.get("agents", []):
                    caps = a.get("capabilities", "[]")
                    if isinstance(caps, str):
                        try: caps = json.loads(caps)
                        except: caps = []
                    members.append({
                        "name": a["name"], "emoji": emoji_map.get(a.get("role"), "🤖"),
                        "role": a.get("role", "agent"), "host": a.get("machine", ""),
                        "model": a.get("model", ""), "status": a.get("status", "offline"),
                        "current_task": a.get("current_task", ""),
                        "last_seen": a.get("last_seen"),
                        "capabilities": caps,
                        "leadership_priority": a.get("leadership_priority", 99),
                        "leadership_role": a.get("leadership_role", "worker"),
                    })
                self._send_json({"members": members, "source": "coordination_server"})
            except Exception:
                # Fallback to static data
                self._send_json({"members": [
                    {"name": "Pavel (Vedoucí)", "emoji": "👑", "role": "Team Lead",
                     "description": "Human lead, final decisions"},
                    {"name": "Cyril", "emoji": "🔤", "role": "Knowledge Processor",
                     "description": "GPU inference, knowledge processing, local compute",
                     "model": "Claude Opus 4.6", "host": "Notebook1"},
                    {"name": "Metod", "emoji": "🔧", "role": "Coordinator & Infra",
                     "description": "24/7 coordination, infrastructure, admin",
                     "model": "Claude Opus 4.6", "host": "VPS Contabo"},
                    {"name": "Pepa-PC", "emoji": "🖥️", "role": "GPU Compute",
                     "description": "Heavy compute, Neo4j, entity extraction",
                     "model": "qwen3:32b (local)", "host": "Pepa-PC", "status": "stopped"},
                    {"name": "Marketing Agent", "emoji": "📢", "role": "Marketing",
                     "description": "SEO, content, sales monitoring",
                     "model": "Claude Opus 4.6", "host": "Test Server", "status": "sleeping"},
                    {"name": "Web AI", "emoji": "🌐", "role": "Support & Guardian",
                     "description": "Server monitoring, emergency response",
                     "model": "Claude Opus 4.6", "host": "Test Server", "status": "sleeping"},
                ], "source": "fallback"})
            

        # /api/system handled in do_GET only

        elif path == "/api/languages":
            langs = []
            i18n_dir = STATIC_DIR / "i18n"
            if i18n_dir.is_dir():
                for f in sorted(i18n_dir.glob("*.json")):
                    langs.append(f.stem)
            self._send_json({"languages": langs})

        elif path == "/api/license":
            # Get license status
            try:
                from uaml.licensing.manager import LicenseManager
                lm = LicenseManager()
                info = lm.get_status()
                self._send_json(info)
            except Exception:
                self._send_json({"status": "community", "plan": "Community", "note": "No license key configured"})

        elif path == "/api/health":
            self._send_json({"status": "ok", "version": "1.0.0"})

        elif path == "/api/license":
            # Get current license status
            try:
                from pathlib import Path as _P
                license_file = _P.home() / ".uaml" / "license.key"
                if license_file.exists():
                    key = license_file.read_text().strip()
                    from uaml.licensing import LicenseKey, LicenseManager
                    # Offline validation
                    offline = LicenseKey.validate(key)
                    if not offline["valid"]:
                        self._send_json({"status": "none", "error": offline["error"]})
                        return
                    # Try license server for full status
                    try:
                        import urllib.request
                        req = urllib.request.Request(
                            f"https://license.uaml.ai/api/status?key={key}",
                            headers={"Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            server_data = json.loads(resp.read())
                        if server_data.get("found"):
                            # Get features for tier
                            tier_lower = server_data.get("tier", "community").lower()
                            tier_features = self._get_tier_features(tier_lower)
                            server_data["features"] = tier_features
                            server_data["key"] = key[:9] + "****-****-****"
                            self._send_json(server_data)
                        else:
                            # Key valid offline but not on server
                            tier_features = self._get_tier_features(offline["tier"].lower())
                            self._send_json({
                                "status": "active", "tier": offline["tier"],
                                "features": tier_features,
                                "key": key[:9] + "****-****-****",
                                "activations": [], "active_nodes": 0, "max_nodes": 1
                            })
                    except Exception:
                        # Server unreachable — use offline data
                        tier_features = self._get_tier_features(offline["tier"].lower())
                        self._send_json({
                            "status": "active", "tier": offline["tier"],
                            "features": tier_features,
                            "key": key[:9] + "****-****-****",
                            "activations": [], "active_nodes": 0, "max_nodes": 1,
                            "offline": True
                        })
                else:
                    self._send_json({
                        "status": "none", "tier": "Community",
                        "features": ["Core Memory API", "CLI Interface", "Python API"],
                        "activations": [], "active_nodes": 0, "max_nodes": 1
                    })
            except Exception as e:
                self._send_json({"status": "none", "error": str(e)})

        elif path == "/api/compliance":
            # Run compliance audit
            from uaml.compliance.auditor import ComplianceAuditor
            auditor = ComplianceAuditor(store)
            check_type = params.get("type", ["full"])[0]
            if check_type == "gdpr":
                report = auditor.gdpr_check()
            elif check_type == "retention":
                max_age = int(params.get("max_age", [365])[0])
                report = auditor.retention_check(max_age_days=max_age)
            else:
                report = auditor.full_audit()
            self._send_json(report.to_dict())

        elif path == "/api/reasoning":
            # Get reasoning traces
            limit = int(params.get("limit", [10])[0])
            agent_id = params.get("agent_id", [None])[0]
            traces = store.get_reasoning_traces(limit=limit, agent_id=agent_id)
            self._send_json({"traces": [t.to_dict() if hasattr(t, 'to_dict') else t for t in traces]})

        elif path == "/api/config":
            # Get configuration info
            from uaml.core.config import discover_config
            config = discover_config(db_path=str(store.db_path) if hasattr(store, 'db_path') else None)
            self._send_json(config.to_dict())

        elif path == "/api/summaries":
            # Weekly/daily summary aggregation
            result = store.consolidate_summaries(
                start_date=params.get("start", [None])[0],
                end_date=params.get("end", [None])[0],
                topic=params.get("topic", [None])[0],
                project=params.get("project", [None])[0],
                client_ref=params.get("client_ref", [None])[0],
                group_by=params.get("group_by", ["week"])[0],
            )
            self._send_json({"summaries": result, "count": len(result)})

        elif path == "/api/v1/focus-config":
            try:
                cfg = self._get_focus_config()
                self._send_json(cfg.to_dict())
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/focus-config/presets":
            try:
                from ..core.focus_config import PRESETS
                self._send_json({"presets": {k: v.to_dict() for k, v in PRESETS.items()}})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/rules-log":
            try:
                from ..core.rules_changelog import RulesChangelog
                limit = int(params.get("limit", [50])[0])
                cl = RulesChangelog()
                entries = cl.get_entries(limit=limit)
                self._send_json({"entries": entries})
            except Exception as e:
                self._send_json({"entries": [], "error": str(e)})

        elif path == "/api/v1/rules-log/stats":
            try:
                from ..core.rules_changelog import RulesChangelog
                cl = RulesChangelog()
                stats = cl.get_stats()
                self._send_json(stats)
            except Exception as e:
                self._send_json({"total_changes": 0, "error": str(e)})

        elif path == "/api/v1/saved-configs":
            try:
                store = self._get_saved_config_store()
                ft = params.get("filter_type", [None])[0]
                configs = store.list(filter_type=ft)
                self._send_json({"configs": configs})
            except Exception as e:
                self._send_json({"configs": [], "error": str(e)})

        elif path.startswith("/api/v1/saved-configs/"):
            name = path.split("/api/v1/saved-configs/", 1)[1]
            if not name:
                self._send_json({"error": "config name required"}, 400)
                return
            try:
                store = self._get_saved_config_store()
                config = store.load(name)
                self._send_json({"name": name, "config": config.to_dict()})
            except KeyError:
                self._send_json({"error": f"Config '{name}' not found"}, 404)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/active-config":
            try:
                store = self._get_saved_config_store()
                ft = params.get("filter_type", ["both"])[0]
                name = store.get_active_name(filter_type=ft)
                self._send_json({"active": name, "filter_type": ft})
            except Exception as e:
                self._send_json({"active": None, "error": str(e)})

        # ── Coordination / Orchestration API ──
        elif path == "/api/v1/coordination/rules":
            try:
                det = self._get_coordinator()
                rules = det.get_rules()
                filter_type = params.get("type", [None])[0]
                result = []
                for r in rules:
                    d = {"id": r.id, "rule_type": r.rule_type, "trigger_pattern": r.trigger_pattern,
                         "action": r.action, "scope": r.scope, "priority": r.priority,
                         "description": r.description, "enabled": r.enabled,
                         "channel": getattr(r, 'channel', '*'), "preset": getattr(r, 'preset', None),
                         "template": getattr(r, 'template', None)}
                    if filter_type and d["rule_type"] != filter_type:
                        continue
                    result.append(d)
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/coordination/events":
            try:
                det = self._get_coordinator()
                active_only = params.get("active", ["false"])[0] == "true"
                events = det.get_active_events() if active_only else det.get_active_events()
                self._send_json(events)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/coordination/trust":
            try:
                det = self._get_coordinator()
                channel = params.get("channel", ["*"])[0]
                level = det.get_channel_trust_level(channel)
                self._send_json({"channel": channel, "trust_level": level})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def _get_coordinator(self):
        """Get or create CoordinationDetector."""
        if not hasattr(self.__class__, '_coordinator'):
            import sys as _sys
            _pkg = str(Path(__file__).parent.parent.parent)
            if _pkg not in _sys.path:
                _sys.path.insert(0, _pkg)
            from uaml.coordination import CoordinationDetector
            self.__class__._coordinator = CoordinationDetector(self.__class__.store.db_path)
        return self.__class__._coordinator

    def _get_saved_config_store(self):
        """Get or create SavedConfigStore."""
        if not hasattr(self.__class__, '_saved_config_store'):
            from ..core.focus_config import SavedConfigStore
            db_path = Path(self.__class__.store.db_path).parent / "saved_configs.db"
            self.__class__._saved_config_store = SavedConfigStore(db_path)
        return self.__class__._saved_config_store

    def _get_tier_features(self, tier: str) -> list:
        """Return feature list for a given tier."""
        features_map = {
            "community": ["Core Memory API", "CLI Interface", "Python API"],
            "starter": ["Core Memory API", "CLI Interface", "Python API", "Compliance Module", "GDPR Tools"],
            "professional": ["Core Memory API", "CLI Interface", "Python API", "Compliance Module", "GDPR Tools",
                            "Focus Engine", "Security Configurator", "Expert on Demand", "Federation"],
            "team": ["Core Memory API", "CLI Interface", "Python API", "Compliance Module", "GDPR Tools",
                    "Focus Engine", "Security Configurator", "Expert on Demand", "Federation",
                    "Neo4j Integration", "RBAC", "Approval Gates"],
            "enterprise": ["All features"],
        }
        return features_map.get(tier.lower(), features_map["community"])

    def _get_focus_config(self):
        """Get or create Focus Engine config."""
        from ..core.focus_config import FocusEngineConfig, load_focus_config
        cfg_path = Path(self.__class__.store.db_path).parent / "focus_config.yaml"
        if cfg_path.exists():
            return load_focus_config(cfg_path)
        return FocusEngineConfig()

    def _save_focus_cfg(self, cfg):
        """Save Focus Engine config."""
        from ..core.focus_config import save_focus_config
        cfg_path = Path(self.__class__.store.db_path).parent / "focus_config.yaml"
        save_focus_config(cfg, cfg_path)

    def _handle_api_put(self, path: str, body: dict):
        """Handle PUT requests."""
        if path.startswith("/api/v1/coordination/rules/"):
            try:
                rule_id = int(path.split("/")[-1])
                det = self._get_coordinator()
                conn = det._connect()
                sets = []
                vals = []
                for k in ("rule_type", "trigger_pattern", "action", "scope", "channel",
                          "priority", "description", "preset", "template", "enabled"):
                    if k in body:
                        sets.append(f"{k} = ?")
                        vals.append(body[k])
                if sets:
                    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')")
                    vals.append(rule_id)
                    conn.execute(f"UPDATE coordination_rules SET {', '.join(sets)} WHERE id = ?", vals)
                    conn.commit()
                conn.close()
                self._send_json({"status": "updated", "id": rule_id})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        elif path == "/api/v1/focus-config":
            try:
                cfg = self._get_focus_config()
                if "input_filter" in body:
                    for k, v in body["input_filter"].items():
                        if k == "categories":
                            cfg.input_filter.categories.update(v)
                        elif hasattr(cfg.input_filter, k):
                            setattr(cfg.input_filter, k, v)
                if "output_filter" in body:
                    for k, v in body["output_filter"].items():
                        if hasattr(cfg.output_filter, k):
                            setattr(cfg.output_filter, k, v)
                if "agent_rules" in body:
                    for k, v in body["agent_rules"].items():
                        if hasattr(cfg.agent_rules, k):
                            setattr(cfg.agent_rules, k, v)
                self._save_focus_cfg(cfg)
                self._send_json({"status": "saved", "config": cfg.to_dict()})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def _handle_api_post(self, path: str, body: dict):
        store = self.__class__.store

        if path == "/api/license/activate":
            key = body.get("key", "").strip().upper()
            if not key:
                self._send_json({"success": False, "error": "Missing license key"}, 400)
                return
            try:
                from uaml.licensing import LicenseKey
                # Validate offline first
                result = LicenseKey.validate(key)
                if not result["valid"]:
                    self._send_json({"success": False, "error": result["error"]})
                    return
                # Save key locally
                from pathlib import Path as _P
                import hashlib as _hl, socket as _sock
                license_dir = _P.home() / ".uaml"
                license_dir.mkdir(exist_ok=True)
                (license_dir / "license.key").write_text(key)
                # Try to activate on license server
                node_id = _hl.sha256(_sock.gethostname().encode()).hexdigest()[:16]
                hostname = _sock.gethostname()
                try:
                    import urllib.request
                    data = json.dumps({"key": key, "node_id": node_id, "hostname": hostname}).encode()
                    req = urllib.request.Request(
                        "https://license.uaml.ai/api/activate",
                        data=data,
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        server_result = json.loads(resp.read())
                    self._send_json({"success": True, "tier": result["tier"], "server": server_result})
                except Exception:
                    # Server unreachable — activate offline
                    self._send_json({"success": True, "tier": result["tier"], "offline": True,
                                     "message": "Key saved locally. Server activation will happen on next check."})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)})
            return

        elif path == "/api/license/deactivate":
            try:
                from pathlib import Path as _P
                license_file = _P.home() / ".uaml" / "license.key"
                if license_file.exists():
                    key = license_file.read_text().strip()
                    import hashlib as _hl, socket as _sock
                    node_id = _hl.sha256(_sock.gethostname().encode()).hexdigest()[:16]
                    try:
                        import urllib.request
                        data = json.dumps({"key": key, "node_id": node_id}).encode()
                        req = urllib.request.Request(
                            "https://license.uaml.ai/api/deactivate",
                            data=data,
                            headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            json.loads(resp.read())
                    except Exception:
                        pass  # Server unreachable — deactivate locally only
                    license_file.unlink()
                    self._send_json({"success": True})
                else:
                    self._send_json({"success": False, "error": "No license to deactivate"})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)})
            return

        elif path == "/api/v1/saved-configs":
            # Save a named config
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"}, 400)
                return
            try:
                # If config provided in body, save to disk first then save named
                if body.get("config"):
                    from ..core.focus_config import FocusEngineConfig
                    cfg = self._get_focus_config()
                    posted = body["config"]
                    if "input_filter" in posted:
                        for k, v in posted["input_filter"].items():
                            if k == "categories":
                                cfg.input_filter.categories.update(v)
                            elif hasattr(cfg.input_filter, k):
                                setattr(cfg.input_filter, k, v)
                    if "output_filter" in posted:
                        for k, v in posted["output_filter"].items():
                            if hasattr(cfg.output_filter, k):
                                setattr(cfg.output_filter, k, v)
                    if "agent_rules" in posted:
                        for k, v in posted["agent_rules"].items():
                            if hasattr(cfg.agent_rules, k):
                                setattr(cfg.agent_rules, k, v)
                else:
                    cfg = self._get_focus_config()
                config_store = self._get_saved_config_store()
                result = config_store.save(
                    name, cfg,
                    filter_type=body.get("filter_type", "both"),
                    description=body.get("description", ""),
                    created_by=body.get("user", "dashboard"),
                    set_active=body.get("set_active", False),
                )
                self._send_json(result, 201)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/saved-configs/activate":
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"}, 400)
                return
            try:
                ft = body.get("filter_type", "both")
                config_store = self._get_saved_config_store()
                config_store.set_active(name, filter_type=ft)
                # Also load it as the current active config
                cfg = config_store.load(name)
                self._save_focus_cfg(cfg)
                self._send_json({"status": "activated", "name": name})
            except KeyError:
                self._send_json({"error": f"Config '{name}' not found"}, 404)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/saved-configs/delete":
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"}, 400)
                return
            try:
                ft = body.get("filter_type", "both")
                config_store = self._get_saved_config_store()
                deleted = config_store.delete(name, filter_type=ft)
                if deleted:
                    self._send_json({"status": "deleted", "name": name})
                else:
                    self._send_json({"error": f"Config '{name}' not found"}, 404)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/saved-configs/load":
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "name required"}, 400)
                return
            try:
                ft = body.get("filter_type", "both")
                config_store = self._get_saved_config_store()
                cfg = config_store.load(name, filter_type=ft)
                # Apply as current config
                self._save_focus_cfg(cfg)
                config_store.set_active(name, filter_type=ft)
                self._send_json({"status": "loaded", "name": name, "config": cfg.to_dict()})
            except KeyError:
                self._send_json({"error": f"Config '{name}' not found"}, 404)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        # ── Coordination POST endpoints ──
        elif path == "/api/v1/coordination/rules":
            try:
                det = self._get_coordinator()
                rule_id = det.add_rule(
                    rule_type=body.get("rule_type", "lock"),
                    trigger_pattern=body.get("trigger_pattern", ""),
                    action=body.get("action", "block_write"),
                    scope=body.get("scope", "*"),
                    channel=body.get("channel", "*"),
                    priority=body.get("priority", "normal"),
                    description=body.get("description", ""),
                    preset=body.get("preset"),
                    created_by=body.get("created_by", "dashboard"),
                )
                self._send_json({"id": rule_id, "status": "created"}, 201)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/v1/coordination/rules/") and not path.endswith("/resolve"):
            # PUT update rule
            try:
                rule_id = int(path.split("/")[-1])
                det = self._get_coordinator()
                conn = det._connect()
                sets = []
                vals = []
                for k in ("rule_type", "trigger_pattern", "action", "scope", "channel",
                          "priority", "description", "preset", "template", "enabled"):
                    if k in body:
                        sets.append(f"{k} = ?")
                        vals.append(body[k])
                if sets:
                    sets.append("updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')")
                    vals.append(rule_id)
                    conn.execute(f"UPDATE coordination_rules SET {', '.join(sets)} WHERE id = ?", vals)
                    conn.commit()
                conn.close()
                self._send_json({"status": "updated", "id": rule_id})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/v1/coordination/events/") and path.endswith("/resolve"):
            try:
                event_id = int(path.split("/")[-2])
                det = self._get_coordinator()
                conn = det._connect()
                conn.execute(
                    "UPDATE coordination_events SET resolved = 1, resolved_at = strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE id = ?",
                    (event_id,),
                )
                conn.commit()
                conn.close()
                self._send_json({"status": "resolved", "id": event_id})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/v1/coordination/presets/"):
            try:
                preset_name = path.split("/")[-1]
                det = self._get_coordinator()
                conn = det._connect()
                # Delete old rules, re-insert preset
                conn.execute("DELETE FROM coordination_rules WHERE preset = ? OR preset IS NULL", (preset_name,))
                if preset_name == "conservative":
                    conn.executemany(
                        "INSERT INTO coordination_rules (rule_type, trigger_pattern, action, scope, channel, priority, description, preset, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                        [
                            ("lock", "CLAIM|beru|I'll do|já to", "block_write", "*", "*", "normal", "Block writes to claimed resources", "conservative", "system"),
                            ("halt", "STOP|moment|počkej|halt|wait", "block_write", "*", "*", "urgent", "Supervisor halt", "conservative", "system"),
                            ("allow", "research|read|search|recall|discuss", "pass", "*", "*", "normal", "Allow read-only", "conservative", "system"),
                            ("notify", "DONE|hotovo|done|completed|finished", "release", "*", "*", "normal", "Release claims", "conservative", "system"),
                        ],
                    )
                elif preset_name == "permissive":
                    conn.execute(
                        "INSERT INTO coordination_rules (rule_type, trigger_pattern, action, scope, channel, priority, description, preset, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                        ("allow", ".*", "pass", "*", "*", "normal", "Allow everything", "permissive", "system"),
                    )
                else:  # standard
                    conn.executemany(
                        "INSERT INTO coordination_rules (rule_type, trigger_pattern, action, scope, channel, priority, description, preset, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                        [
                            ("lock", "CLAIM|beru", "block_write", "*", "*", "normal", "Block claimed resources", "standard", "system"),
                            ("halt", "STOP|halt", "block_write", "*", "*", "urgent", "Supervisor halt", "standard", "system"),
                            ("allow", ".*", "pass", "*", "*", "normal", "Allow by default", "standard", "system"),
                        ],
                    )
                conn.commit()
                conn.close()
                self._send_json({"status": "preset_loaded", "preset": preset_name})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/v1/coordination/sanitize":
            try:
                det = self._get_coordinator()
                content = body.get("content", "")
                channel = body.get("channel", "")
                source = body.get("source", "unknown")
                sanitized = det.sanitize_input(content, channel, source)
                self._send_json({
                    "sanitized": sanitized != content,
                    "content": sanitized,
                    "trust_level": det.get_channel_trust_level(channel),
                })
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path == "/api/knowledge":
            content = body.get("content", "")
            if not content:
                self._send_json({"error": "content required"}, 400)
                return
            entry_id = store.learn(
                content,
                topic=body.get("topic", ""),
                tags=body.get("tags", ""),
                data_layer=body.get("data_layer", "knowledge"),
                source_origin=body.get("source_origin", "manual"),
            )
            self._send_json({"id": entry_id, "status": "created"}, 201)

        elif path == "/api/search":
            q = body.get("query", "")
            limit = body.get("limit", 10)
            results = store.search(q, limit=limit)
            entries = [{
                "id": r.entry.id,
                "content": r.entry.content,
                "topic": r.entry.topic,
                "score": r.score,
            } for r in results]
            self._send_json({"results": entries})

        elif path == "/api/recall":
            q = body.get("query", "")
            query_class = body.get("query_class", "operational")
            model_profile = body.get("model_profile", "cloud_standard")
            risk_level = body.get("risk_level", "low")
            try:
                result = store.policy_recall(
                    q,
                    query_class=query_class,
                    model_profile=model_profile,
                    risk_level=risk_level,
                    topic=body.get("topic"),
                    project=body.get("project"),
                    client_ref=body.get("client_ref"),
                )
                # Serialize results
                entries = [{
                    "id": getattr(r, 'id', getattr(r, 'entry', r).id if hasattr(r, 'entry') else 0),
                    "content": getattr(r, 'content', getattr(r, 'entry', r).content if hasattr(r, 'entry') else str(r)),
                    "topic": getattr(r, 'topic', ''),
                    "score": getattr(r, 'score', 0),
                } for r in result.get("results", [])]
                self._send_json({"policy": result["policy"], "results": entries})
            except (ValueError, KeyError) as e:
                self._send_json({"error": f"Invalid parameter: {e}"}, 400)

        elif path == "/api/license/activate":
            key = body.get("key", "").strip()
            if not key:
                self._send_json({"error": "License key required"}, 400)
                return
            try:
                from uaml.licensing.manager import LicenseManager
                lm = LicenseManager()
                result = lm.activate(key)
                self._send_json(result)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 400)

        elif path == "/api/license/deactivate":
            try:
                from uaml.licensing.manager import LicenseManager
                lm = LicenseManager()
                result = lm.deactivate()
                self._send_json(result)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 400)

        else:
            self._send_json({"error": "unknown endpoint"}, 404)


class UAMLWebApp:
    """UAML Web Application server."""

    def __init__(self, db_path: str = "memory.db", agent_id: str = "web"):
        self.store = MemoryStore(db_path, agent_id=agent_id)
        UAMLRequestHandler.store = self.store

    def serve(self, host: str = "127.0.0.1", port: int = 8780):
        """Start the web server (blocking)."""
        server = HTTPServer((host, port), UAMLRequestHandler)
        print(f"🌐 UAML Dashboard: http://{host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down...")
            server.shutdown()
            self.store.close()

    def serve_background(self, host: str = "127.0.0.1", port: int = 8780) -> HTTPServer:
        """Start in background thread. Returns server for shutdown."""
        server = HTTPServer((host, port), UAMLRequestHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return server
