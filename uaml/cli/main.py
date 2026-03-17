# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML CLI — command-line interface.

Usage:
    uaml init [--db PATH]           Initialize a new memory database
    uaml learn "content" [OPTIONS]  Store new knowledge
    uaml search "query" [OPTIONS]   Search knowledge
    uaml stats [--db PATH]          Show database statistics
    uaml serve [OPTIONS]            Start MCP server
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from uaml.core.store import MemoryStore

DEFAULT_DB = "memory.db"

EULA_ACCEPTED_PATH = Path.home() / ".uaml" / "eula_accepted"

EULA_SUMMARY = """
UAML — End User License Agreement Summary
==========================================
© 2026 GLG, a.s. All rights reserved.

By accepting this EULA you agree to the following:

 1. Personal use is free (limited features).
    Commercial use requires a paid subscription.
 2. The software collects anonymous telemetry (installation status,
    error reports, OS/Python/architecture metadata, anonymous identifier).
    No personal data, user content, or memory data is ever transmitted.
    Opt-out: uaml config set telemetry false
 3. All user data stays local — never transmitted to our servers.
 4. All intellectual property rights belong to GLG, a.s.
 5. The software is provided "as is" without warranties.
 6. Governed by the laws of the Czech Republic.

Full EULA: https://uaml-memory.com/eula
Contact:   info@uaml.ai
"""


def check_eula_accepted() -> bool:
    """Check whether the user has accepted the EULA.

    Returns True if accepted, False otherwise (with instructions printed).
    """
    if EULA_ACCEPTED_PATH.exists():
        return True
    click.echo("You must accept the EULA before using UAML.")
    click.echo("Run: uaml --accept-eula")
    return False


def _handle_accept_eula() -> None:
    """Display EULA summary, record acceptance, and exit."""
    click.echo(EULA_SUMMARY)
    EULA_ACCEPTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    EULA_ACCEPTED_PATH.write_text(
        f"accepted_at={datetime.now(timezone.utc).isoformat()}\n"
    )
    click.echo("EULA accepted. You can now use UAML.")
    sys.exit(0)


class _EULAGroup(click.Group):
    """Custom Click group that enforces EULA acceptance before dispatching."""

    def invoke(self, ctx: click.Context) -> None:  # type: ignore[override]
        args = sys.argv[1:]
        # Skip EULA check for --accept-eula, --help, and --version
        if "--accept-eula" in args:
            _handle_accept_eula()
        if not any(flag in args for flag in ("--help", "-h", "--version")):
            if not check_eula_accepted():
                sys.exit(1)
        super().invoke(ctx)


@click.group(cls=_EULAGroup)
@click.option("--accept-eula", is_flag=True, hidden=True, help="Accept the EULA")
@click.version_option(package_name="uaml")
def cli(accept_eula: bool = False):
    """UAML — Universal Agent Memory Layer.

    Persistent, temporal, ethical memory for AI agents.
    """
    pass


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
def init(db: str):
    """Initialize a new UAML memory database."""
    db_path = Path(db)
    if db_path.exists():
        click.echo(f"Database already exists: {db_path}")
        click.echo("Use --db to specify a different path.")
        return

    store = MemoryStore(db_path)
    stats = store.stats()
    store.close()

    click.echo(f"✅ UAML memory database initialized: {db_path}")
    click.echo(f"   Tables created: {len(stats)} tables")
    click.echo(f"\nNext steps:")
    click.echo(f"  uaml learn 'Your first knowledge entry' --topic hello")
    click.echo(f"  uaml search 'hello'")
    click.echo(f"  uaml serve  # Start MCP server")


@cli.command()
@click.argument("content")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--topic", default="", help="Topic for categorization")
@click.option("--summary", default="", help="Short summary")
@click.option("--agent", default="default", help="Agent ID")
@click.option("--source", default="manual", help="Source type")
@click.option("--source-ref", default="", help="Source reference (URL, file path)")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--confidence", default=0.8, type=float, help="Confidence score (0-1)")
@click.option("--project", default=None, help="Project name for isolation")
@click.option("--client", default=None, help="Client reference for isolation")
@click.option("--valid-from", default=None, help="Valid from date (ISO format)")
@click.option("--valid-until", default=None, help="Valid until date (ISO format)")
@click.option("--layer", default=None, type=click.Choice(["identity", "knowledge", "team", "operational", "project"]),
              help="Data layer (5-layer architecture)")
@click.option("--source-origin", default=None, type=click.Choice(["external", "generated", "derived", "observed"]),
              help="Source origin classification")
def learn(content, db, topic, summary, agent, source, source_ref, tags, confidence,
          project, client, valid_from, valid_until, layer, source_origin):
    """Store a new knowledge entry."""
    store = MemoryStore(db, agent_id=agent)
    entry_id = store.learn(
        content,
        topic=topic,
        summary=summary,
        source_type=source,
        source_ref=source_ref,
        tags=tags,
        confidence=confidence,
        project=project,
        client_ref=client,
        valid_from=valid_from,
        valid_until=valid_until,
        data_layer=layer,
        source_origin=source_origin,
    )
    store.close()
    click.echo(f"✅ Stored knowledge entry #{entry_id}")


@cli.command()
@click.argument("query")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--limit", "-n", default=5, help="Max results")
@click.option("--agent", default=None, help="Filter by agent")
@click.option("--topic", default=None, help="Filter by topic")
@click.option("--project", default=None, help="Filter by project")
@click.option("--client", default=None, help="Filter by client (isolation)")
@click.option("--at-time", default=None, help="Point-in-time query (ISO date)")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def search(query, db, limit, agent, topic, project, client, at_time, json_output):
    """Search knowledge entries."""
    store = MemoryStore(db)
    results = store.search(
        query,
        limit=limit,
        agent_id=agent,
        topic=topic,
        project=project,
        client_ref=client,
        point_in_time=at_time,
    )
    store.close()

    if not results:
        click.echo("No results found.")
        return

    if json_output:
        output = [
            {
                "id": r.entry.id,
                "score": round(r.score, 4),
                "topic": r.entry.topic,
                "summary": r.entry.summary or r.entry.content[:100],
                "content": r.entry.content,
                "source_ref": r.entry.source_ref,
                "confidence": r.entry.confidence,
            }
            for r in results
        ]
        click.echo(json.dumps(output, indent=2, ensure_ascii=False))
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n{'─' * 60}")
        click.echo(f"  #{r.entry.id}  score={r.score:.2f}  topic={r.entry.topic}")
        if r.entry.summary:
            click.echo(f"  {r.entry.summary}")
        else:
            click.echo(f"  {r.entry.content[:200]}")
        if r.entry.source_ref:
            click.echo(f"  📎 {r.entry.source_ref}")

    click.echo(f"\n{'─' * 60}")
    click.echo(f"Found {len(results)} result(s).")


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def stats(db, json_output):
    """Show database statistics."""
    store = MemoryStore(db)
    data = store.stats()
    store.close()

    if json_output:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    click.echo("\n📊 UAML Memory Statistics")
    click.echo("=" * 40)
    for table in ["knowledge", "team_knowledge", "personality", "entities",
                   "entity_mentions", "knowledge_relations", "audit_log",
                   "session_summaries"]:
        count = data.get(table, 0)
        if count > 0:
            click.echo(f"  {table}: {count}")

    if data.get("top_topics"):
        click.echo("\nTop topics:")
        for topic, cnt in data["top_topics"].items():
            if topic:
                click.echo(f"  {topic}: {cnt}")

    if data.get("agents"):
        click.echo("\nAgents:")
        for agent, cnt in data["agents"].items():
            click.echo(f"  {agent}: {cnt}")


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def layers(db, json_output):
    """Show data distribution across 5 layers."""
    store = MemoryStore(db)
    data = store.layer_stats()
    store.close()

    if json_output:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    icons = {
        "identity": "🧠", "knowledge": "📚", "team": "👥",
        "operational": "⚙️", "project": "📁",
    }
    click.echo("\n📊 UAML Data Layer Distribution")
    click.echo("=" * 50)
    total = sum(v["count"] for v in data.values())
    for layer_name in ["identity", "knowledge", "team", "operational", "project"]:
        info = data.get(layer_name, {"count": 0, "total_bytes": 0})
        icon = icons.get(layer_name, "•")
        pct = (info["count"] / total * 100) if total > 0 else 0
        size_kb = info["total_bytes"] / 1024 if info["total_bytes"] else 0
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        click.echo(f"  {icon} {layer_name:12s} {info['count']:>6d} ({pct:4.1f}%) {size_kb:>8.1f}KB")
    click.echo(f"  {'─' * 48}")
    click.echo(f"  {'':12s}  Total: {total:>6d}")


@cli.group()
def task():
    """Task management — create, list, update, complete tasks."""
    pass


@task.command("add")
@click.argument("title")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--description", "-d", default="", help="Task description")
@click.option("--project", "-p", default=None, help="Project name")
@click.option("--assigned", "-a", default=None, help="Assigned agent")
@click.option("--priority", type=int, default=0, help="Priority (0=normal, 1=high, 2=urgent)")
@click.option("--tags", default="", help="Comma-separated tags")
@click.option("--client", default=None, help="Client reference")
def task_add(title, db, description, project, assigned, priority, tags, client):
    """Create a new task."""
    store = MemoryStore(db)
    tid = store.create_task(
        title, description=description, project=project,
        assigned_to=assigned, priority=priority, tags=tags, client_ref=client,
    )
    store.close()
    click.echo(f"✅ Created task #{tid}: {title}")


@task.command("list")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--status", "-s", default=None, help="Filter by status")
@click.option("--project", "-p", default=None, help="Filter by project")
@click.option("--assigned", "-a", default=None, help="Filter by assignee")
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def task_list(db, status, project, assigned, limit, json_output):
    """List tasks."""
    store = MemoryStore(db)
    tasks = store.list_tasks(status=status, project=project, assigned_to=assigned, limit=limit)
    store.close()

    if json_output:
        click.echo(json.dumps(tasks, indent=2, ensure_ascii=False))
        return

    if not tasks:
        click.echo("No tasks found.")
        return

    icons = {"todo": "📋", "in_progress": "🔧", "done": "✅", "blocked": "🚫",
             "review": "👀", "backlog": "📦", "cancelled": "❌"}
    for t in tasks:
        icon = icons.get(t["status"], "•")
        pri = "🔴" if t["priority"] >= 2 else "🟡" if t["priority"] >= 1 else ""
        proj = f" [{t['project']}]" if t["project"] else ""
        assigned_str = f" → {t['assigned_to']}" if t["assigned_to"] else ""
        click.echo(f"  {icon} #{t['id']}{pri}{proj}{assigned_str}: {t['title']}")

    click.echo(f"\n{len(tasks)} task(s)")


@task.command("update")
@click.argument("task_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--status", "-s", default=None, help="New status")
@click.option("--title", default=None, help="New title")
@click.option("--assigned", "-a", default=None, help="New assignee")
@click.option("--priority", type=int, default=None, help="New priority")
def task_update(task_id, db, status, title, assigned, priority):
    """Update a task."""
    store = MemoryStore(db)
    kwargs = {}
    if status: kwargs["status"] = status
    if title: kwargs["title"] = title
    if assigned: kwargs["assigned_to"] = assigned
    if priority is not None: kwargs["priority"] = priority

    ok = store.update_task(task_id, **kwargs)
    store.close()

    if ok:
        click.echo(f"✅ Updated task #{task_id}")
    else:
        click.echo(f"❌ Task #{task_id} not found")


@task.command("done")
@click.argument("task_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database path")
def task_done(task_id, db):
    """Mark a task as done."""
    store = MemoryStore(db)
    ok = store.update_task(task_id, status="done")
    store.close()

    if ok:
        click.echo(f"✅ Task #{task_id} completed!")
    else:
        click.echo(f"❌ Task #{task_id} not found")


@task.command("search")
@click.argument("query")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--limit", "-n", default=10, help="Max results")
def task_search(query, db, limit):
    """Search tasks by text."""
    store = MemoryStore(db)
    results = store.search_tasks(query, limit=limit)
    store.close()

    if not results:
        click.echo("No tasks found.")
        return

    for t in results:
        click.echo(f"  #{t['id']} [{t['status']}]: {t['title']}")


@cli.group()
def ethics():
    """Ethics pipeline — check content, manage rules."""
    pass


@ethics.command("check")
@click.argument("content")
@click.option("--rules-file", default=None, help="Custom YAML rules file")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def ethics_check(content, rules_file, json_output):
    """Check content against ethics rules."""
    from uaml.ethics.checker import EthicsChecker

    if rules_file:
        checker = EthicsChecker.from_yaml(rules_file)
    else:
        checker = EthicsChecker()

    verdict = checker.check(content)

    if json_output:
        click.echo(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False))
        return

    icon = {"APPROVED": "✅", "FLAGGED": "⚠️", "REJECTED": "❌"}
    click.echo(f"\n{icon.get(verdict.verdict, '?')} Verdict: {verdict.verdict}")

    if verdict.matches:
        click.echo(f"\nRules triggered ({len(verdict.matches)}):")
        for m in verdict.matches:
            sev = "🔴" if m.rule.severity.value == "hard" else "🟡"
            click.echo(f"  {sev} {m.rule.name} ({m.rule.severity.value}/{m.rule.action.value})")
            click.echo(f"     {m.rule.description}")
            click.echo(f"     Matched: \"{m.matched_text[:60]}\"")


@ethics.command("rules")
@click.option("--rules-file", default=None, help="Custom YAML rules file")
def ethics_rules(rules_file):
    """List all ethics rules."""
    from uaml.ethics.checker import EthicsChecker

    if rules_file:
        checker = EthicsChecker.from_yaml(rules_file)
    else:
        checker = EthicsChecker()

    click.echo(f"\n🛡️ UAML Ethics Rules ({len(checker.all_rules)} total)")
    click.echo("=" * 60)
    for r in checker.all_rules:
        status = "✅" if r.enabled else "⏸️"
        sev = "🔴" if r.severity.value == "hard" else "🟡"
        click.echo(f"  {status} {sev} {r.name} → {r.action.value}")
        click.echo(f"       {r.description}")


@ethics.command("stats")
@click.option("--rules-file", default=None, help="Custom YAML rules file")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def ethics_stats(rules_file, json_output):
    """Show ethics pipeline statistics."""
    from uaml.ethics.checker import EthicsChecker

    if rules_file:
        checker = EthicsChecker.from_yaml(rules_file)
    else:
        checker = EthicsChecker()

    s = checker.stats()

    if json_output:
        click.echo(json.dumps(s, indent=2))
        return

    click.echo(f"\n🛡️ Ethics Pipeline Stats")
    click.echo(f"  Total rules: {s['total_rules']}")
    click.echo(f"  Active: {s['active_rules']}")
    click.echo(f"  Hard (reject): {s['hard_rules']}")
    click.echo(f"  Soft (flag): {s['soft_rules']}")


# ── Focus Engine commands ──

@cli.group()
def focus():
    """Focus Engine — intelligent recall with token budget management."""
    pass


@focus.command("recall")
@click.argument("query")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--preset", type=click.Choice(["conservative", "standard", "research"]),
              default="conservative", help="Focus Engine preset")
@click.option("--budget", type=int, help="Override token budget")
@click.option("--topic", help="Filter by topic")
@click.option("--project", help="Filter by project")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def focus_recall(query, db, preset, budget, topic, project, json_output):
    """Intelligent recall with Focus Engine — token budget, temporal decay, sensitivity."""
    from uaml.core.focus_config import load_preset

    store = MemoryStore(db)
    config = load_preset(preset)
    if budget:
        config.output_filter.token_budget_per_query = budget

    result = store.focus_recall(
        query,
        focus_config=config,
        topic=topic,
        project=project,
    )
    store.close()

    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        report = result["token_report"]
        click.echo(f"📤 Focus Engine recall: {result['total_selected']} records selected")
        click.echo(f"   Budget: {report['used']}/{report['budget']} tokens ({result['utilization_pct']:.0f}%)")
        click.echo(f"   Cost: ~${report['estimated_cost_usd']:.4f}")
        click.echo(f"   Tier: {report['recall_tier']}")
        click.echo()
        for rec in result["records"]:
            click.echo(f"  [{rec['entry_id']}] (rel={rec['relevance_score']:.3f}, ~{rec['tokens_estimate']} tok)")
            content = rec["content"][:200]
            click.echo(f"      {content}")
            click.echo()


@focus.command("config")
@click.option("--preset", type=click.Choice(["conservative", "standard", "research"]),
              help="Show preset config")
@click.option("--save", type=click.Path(), help="Save config to file")
@click.option("--load", type=click.Path(exists=True), help="Load and display config")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def focus_config(preset, save, load, json_output):
    """View or manage Focus Engine configuration."""
    from uaml.core.focus_config import load_preset, load_focus_config, save_focus_config

    if load:
        config = load_focus_config(load)
    elif preset:
        config = load_preset(preset)
    else:
        config = load_preset("conservative")

    if save:
        save_focus_config(config, save)
        click.echo(f"✅ Config saved to {save}")
        return

    if json_output:
        click.echo(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
    else:
        d = config.to_dict()
        click.echo("📋 Focus Engine Configuration")
        click.echo(f"   Version: {d['version']}")
        click.echo()
        click.echo("   Input Filter:")
        for k, v in d["input_filter"].items():
            if k != "categories":
                click.echo(f"     {k}: {v}")
        click.echo(f"     categories: {d['input_filter'].get('categories', {})}")
        click.echo()
        click.echo("   Output Filter:")
        for k, v in d["output_filter"].items():
            click.echo(f"     {k}: {v}")
        click.echo()
        click.echo("   Agent Rules:")
        for k, v in d["agent_rules"].items():
            click.echo(f"     {k}: {v}")


@focus.command("params")
@click.option("--section", type=click.Choice(["input_filter", "output_filter", "agent_rules"]),
              help="Show only one section")
@click.option("--cert-only", is_flag=True, help="Show only certification-relevant params")
def focus_params(section, cert_only):
    """Show Focus Engine parameter specifications — types, ranges, defaults."""
    from uaml.core.focus_config import get_all_param_specs

    specs = get_all_param_specs()
    for sec_name, params in specs.items():
        if section and sec_name != section:
            continue
        click.echo(f"\n📊 {sec_name}:")
        for name, spec in params.items():
            if cert_only and not spec.certification_relevant:
                continue
            range_str = ""
            if spec.min_val is not None or spec.max_val is not None:
                range_str = f" [{spec.min_val}..{spec.max_val}]"
            cert_flag = " 🔒" if spec.certification_relevant else ""
            click.echo(f"  {name} ({spec.type}, default={spec.default}{range_str}){cert_flag}")
            click.echo(f"    {spec.description}")


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--host", default="localhost", help="Bind host")
@click.option("--port", default=8768, help="Bind port")
@click.option("--transport", type=click.Choice(["stdio", "http"]), default="stdio",
              help="MCP transport mode")
def serve(db, host, port, transport):
    """Start UAML MCP server."""
    click.echo(f"🚀 UAML MCP Server starting...")
    click.echo(f"   DB: {db}")
    click.echo(f"   Transport: {transport}")

    if transport == "http":
        click.echo(f"   Endpoint: http://{host}:{port}")

    # MCP server implementation will be in uaml.mcp module
    try:
        from uaml.mcp.server import run_server
        run_server(db_path=db, host=host, port=port, transport=transport)
    except ImportError:
        click.echo("⚠️  MCP server requires: pip install uaml[mcp]")
        click.echo("   Or install mcp package: pip install mcp")
        sys.exit(1)


# ── Export/Import commands ──

@cli.group()
def io():
    """Export and import data."""
    pass


@io.command("export")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--output", "-o", required=True, help="Output JSONL file")
@click.option("--topic", help="Filter by topic")
@click.option("--project", help="Filter by project")
@click.option("--client", help="Filter by client")
@click.option("--agent", help="Filter by agent")
@click.option("--layer", help="Filter by data layer")
@click.option("--type", "export_type", type=click.Choice(["knowledge", "tasks", "artifacts", "all"]),
              default="all", help="What to export")
@click.option("--confirm-identity", is_flag=True, help="Allow exporting IDENTITY layer")
@click.option("--json-output", "-j", is_flag=True, help="Output stats as JSON")
def io_export(db, output, topic, project, client, agent, layer, export_type, confirm_identity, json_output):
    """Export data to JSONL file."""
    from uaml.io import Exporter

    store = MemoryStore(db)
    exporter = Exporter(store)

    if export_type == "all":
        counts = exporter.export_all(
            output,
            confirm_identity=confirm_identity,
            client_ref=client,
        )
        if json_output:
            click.echo(json.dumps(counts, indent=2))
        else:
            click.echo(f"📦 Exported to {output}:")
            for k, v in counts.items():
                click.echo(f"   {k}: {v}")
    elif export_type == "knowledge":
        count = exporter.export_knowledge(
            output, topic=topic, project=project, client_ref=client,
            agent_id=agent, data_layer=layer, confirm_identity=confirm_identity,
        )
        click.echo(f"📦 Exported {count} knowledge entries to {output}")
    elif export_type == "tasks":
        count = exporter.export_tasks(output, project=project, client_ref=client)
        click.echo(f"📦 Exported {count} tasks to {output}")
    elif export_type == "artifacts":
        count = exporter.export_artifacts(output, project=project, client_ref=client)
        click.echo(f"📦 Exported {count} artifacts to {output}")

    store.close()


@io.command("import")
@click.argument("input_file")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--override-agent", help="Override agent_id on all entries")
@click.option("--override-project", help="Override project on all entries")
@click.option("--override-client", help="Override client_ref on all entries")
@click.option("--json-output", "-j", is_flag=True, help="Output stats as JSON")
def io_import(input_file, db, override_agent, override_project, override_client, json_output):
    """Import data from JSONL file."""
    from uaml.io import Importer

    store = MemoryStore(db)
    importer = Importer(store)
    stats = importer.import_file(
        input_file,
        override_agent=override_agent,
        override_project=override_project,
        override_client=override_client,
    )

    if json_output:
        click.echo(json.dumps(stats.to_dict(), indent=2))
    else:
        click.echo(f"📥 Import complete:")
        click.echo(f"   Imported: {stats.imported}")
        click.echo(f"   Skipped (dedup): {stats.skipped_dedup}")
        click.echo(f"   Skipped (ethics): {stats.skipped_ethics}")
        click.echo(f"   Errors: {stats.errors}")
        if stats.by_type:
            click.echo(f"   By type: {stats.by_type}")

    store.close()


@io.command("access-report")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--client", required=True, help="Client reference")
@click.option("--output", "-o", help="Output JSON file (default: stdout)")
def io_access_report(db, client, output):
    """Generate GDPR Art. 15 access report for a client."""
    store = MemoryStore(db)
    report = store.access_report(client)
    store.close()

    formatted = json.dumps(report, indent=2, ensure_ascii=False, default=str)

    if output:
        with open(output, "w") as f:
            f.write(formatted)
        click.echo(f"📋 Access report saved to {output}")
        click.echo(f"   Knowledge: {report['summary']['total_knowledge']}")
        click.echo(f"   Tasks: {report['summary']['total_tasks']}")
        click.echo(f"   Artifacts: {report['summary']['total_artifacts']}")
        click.echo(f"   Active consents: {report['summary']['active_consents']}")
    else:
        click.echo(formatted)


# ── Backup commands ──

@cli.group()
def backup():
    """Backup and restore UAML database."""
    pass


@backup.command("run")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--target", "-t", required=True, help="Backup target directory")
@click.option("--label", "-l", default="", help="Optional backup label")
@click.option("--type", "backup_type", type=click.Choice(["full", "incremental"]),
              default="full", help="Backup type")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def backup_run(db, target, label, backup_type, json_output):
    """Create a backup."""
    from uaml.io.backup import BackupManager

    store = MemoryStore(db)
    mgr = BackupManager(store)

    if backup_type == "full":
        manifest = mgr.backup_full(target, label=label)
    else:
        manifest = mgr.backup_incremental(target)

    if json_output:
        click.echo(json.dumps(manifest.to_dict(), indent=2))
        return

    click.echo(f"✅ Backup created: {manifest.backup_id}")
    click.echo(f"   Type: {manifest.backup_type.value}")
    click.echo(f"   Size: {manifest.db_size_bytes:,} bytes")
    click.echo(f"   Path: {manifest.target_path}")
    click.echo(f"   SHA-256: {manifest.checksum_sha256[:16]}...")
    click.echo(f"   Entries: {manifest.entry_counts}")


@backup.command("list")
@click.option("--target", "-t", required=True, help="Backup target directory")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def backup_list(target, json_output):
    """List available backups."""
    from uaml.io.backup import BackupManager

    store = MemoryStore(":memory:")
    mgr = BackupManager(store)
    backups = mgr.list_backups(target)

    if json_output:
        click.echo(json.dumps([b.to_dict() for b in backups], indent=2))
        return

    if not backups:
        click.echo("No backups found.")
        return

    click.echo(f"📦 {len(backups)} backup(s) in {target}:\n")
    for b in backups:
        icon = "🟢" if b.backup_type.value == "full" else "🔵"
        click.echo(f"  {icon} {b.backup_id}")
        click.echo(f"     Created: {b.created_at}")
        click.echo(f"     Size: {b.db_size_bytes:,} bytes")
        click.echo(f"     Entries: {b.entry_counts}")
        click.echo()


@backup.command("verify")
@click.argument("backup_path")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
def backup_verify(backup_path, json_output):
    """Verify backup integrity."""
    from uaml.io.backup import BackupManager

    store = MemoryStore(":memory:")
    mgr = BackupManager(store)
    result = mgr.verify(backup_path)

    if json_output:
        click.echo(json.dumps(result, indent=2))
        return

    if result["exists"]:
        checksum_status = "✅" if result["checksum_ok"] else ("⚠️ Unknown" if result["checksum_ok"] is None else "❌ MISMATCH")
        readable_status = "✅" if result["readable"] else "❌"
        click.echo(f"📋 Backup verification: {backup_path}")
        click.echo(f"   Exists: ✅")
        click.echo(f"   Checksum: {checksum_status}")
        click.echo(f"   Readable: {readable_status}")
        click.echo(f"   Tables: {', '.join(result['tables'])}")
        click.echo(f"   Counts: {result['counts']}")
    else:
        click.echo(f"❌ Backup not found: {backup_path}")


@backup.command("restore")
@click.argument("backup_path")
@click.option("--db", default=DEFAULT_DB, help="Target database path")
@click.option("--no-verify", is_flag=True, help="Skip checksum verification")
@click.confirmation_option(prompt="⚠️ This will REPLACE current database. Continue?")
def backup_restore(backup_path, db, no_verify):
    """Restore database from backup."""
    from uaml.io.backup import BackupManager

    store = MemoryStore(db)
    mgr = BackupManager(store)
    manifest = mgr.restore(backup_path, verify_checksum=not no_verify)

    click.echo(f"✅ Restored from: {manifest.backup_id}")
    click.echo(f"   Entries: {manifest.entry_counts}")


@backup.command("cleanup")
@click.option("--target", "-t", required=True, help="Backup target directory")
@click.option("--retention", "-r", default=14, help="Retention in days (default: 14)")
@click.confirmation_option(prompt="Remove old backups?")
def backup_cleanup(target, retention):
    """Remove backups older than retention period."""
    from uaml.io.backup import BackupManager

    store = MemoryStore(":memory:")
    mgr = BackupManager(store)
    removed = mgr.cleanup(target, retention_days=retention)
    click.echo(f"🗑️ Removed {removed} old backup(s)")


# ── API server command ──

@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8780, help="Bind port")
def api(db, host, port):
    """Start UAML REST API server."""
    from uaml.api.server import APIServer

    click.echo(f"🌐 UAML REST API starting...")
    click.echo(f"   DB: {db}")
    click.echo(f"   Endpoint: http://{host}:{port}/api/v1/")
    click.echo(f"   Health: http://{host}:{port}/api/v1/health")
    click.echo()

    store = MemoryStore(db)
    server = APIServer(store, host=host, port=port)
    server.serve()


# ── Ingest commands ─────────────────────────────────────────


@cli.group()
def ingest():
    """Ingest data from external sources into UAML."""
    pass


@ingest.command("chat")
@click.argument("source", type=click.Path(exists=True))
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--session-id", default=None, help="Override session ID")
@click.option("--topic", default="", help="Default topic for entries")
@click.option("--project", default=None, help="Project name")
@click.option("--client", default=None, help="Client reference")
@click.option("--min-length", default=30, type=int, help="Minimum message length")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def ingest_chat(source, db, session_id, topic, project, client, min_length, json_output):
    """Ingest an OpenClaw chat session JSONL file."""
    from uaml.ingest import ChatIngestor

    store = MemoryStore(db)
    ingestor = ChatIngestor(
        store,
        default_topic=topic,
        default_project=project,
        default_client_ref=client,
        min_msg_length=min_length,
    )
    stats = ingestor.ingest(source, session_id=session_id)
    store.close()

    if json_output:
        click.echo(json.dumps({
            "source": stats.source,
            "created": stats.entries_created,
            "skipped": stats.entries_skipped,
            "rejected": stats.entries_rejected,
            "errors": stats.errors,
            "details": stats.details,
        }, indent=2))
    else:
        click.echo(f"📝 Chat ingestion: {source}")
        click.echo(f"   Created:  {stats.entries_created}")
        click.echo(f"   Skipped:  {stats.entries_skipped}")
        click.echo(f"   Rejected: {stats.entries_rejected}")
        click.echo(f"   Errors:   {stats.errors}")
        if stats.details.get("session_id"):
            click.echo(f"   Session:  {stats.details['session_id']}")


@ingest.command("md")
@click.argument("source", type=click.Path(exists=True))
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--topic", default="", help="Default topic")
@click.option("--project", default=None, help="Project name")
@click.option("--client", default=None, help="Client reference")
@click.option("--no-split", is_flag=True, help="Don't split by headings")
@click.option("--heading-level", default=2, type=int, help="Heading level to split on (2=##, 3=###)")
@click.option("--recursive/--no-recursive", default=True, help="Recurse into subdirectories")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def ingest_md(source, db, topic, project, client, no_split, heading_level, recursive, json_output):
    """Ingest markdown files or directories."""
    from uaml.ingest import MarkdownIngestor

    store = MemoryStore(db)
    ingestor = MarkdownIngestor(
        store,
        default_topic=topic,
        default_project=project,
        default_client_ref=client,
    )
    stats = ingestor.ingest(
        source,
        split_sections=not no_split,
        heading_level=heading_level,
        recursive=recursive,
    )
    store.close()

    if json_output:
        click.echo(json.dumps({
            "source": stats.source,
            "created": stats.entries_created,
            "skipped": stats.entries_skipped,
            "rejected": stats.entries_rejected,
            "errors": stats.errors,
        }, indent=2))
    else:
        click.echo(f"📄 Markdown ingestion: {source}")
        click.echo(f"   Created:  {stats.entries_created}")
        click.echo(f"   Skipped:  {stats.entries_skipped}")
        click.echo(f"   Rejected: {stats.entries_rejected}")
        click.echo(f"   Errors:   {stats.errors}")


@ingest.command("web")
@click.argument("url")
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--title", default=None, help="Override page title")
@click.option("--topic", default="", help="Default topic")
@click.option("--project", default=None, help="Project name")
@click.option("--client", default=None, help="Client reference")
@click.option("--no-chunk", is_flag=True, help="Don't chunk long content")
@click.option("--chunk-size", default=4000, type=int, help="Chunk size in chars")
@click.option("--timeout", default=15, type=int, help="HTTP timeout in seconds")
@click.option("--json", "json_output", is_flag=True, help="JSON output")
def ingest_web(url, db, title, topic, project, client, no_chunk, chunk_size, timeout, json_output):
    """Ingest a web page (URL or local HTML file)."""
    from uaml.ingest import WebIngestor

    store = MemoryStore(db)
    ingestor = WebIngestor(
        store,
        default_topic=topic,
        default_project=project,
        default_client_ref=client,
        chunk_size=chunk_size,
    )
    stats = ingestor.ingest(url, title=title, topic=topic, chunk=not no_chunk, timeout=timeout)
    store.close()

    if json_output:
        click.echo(json.dumps({
            "source": stats.source,
            "created": stats.entries_created,
            "skipped": stats.entries_skipped,
            "rejected": stats.entries_rejected,
            "errors": stats.errors,
            "title": stats.details.get("title", ""),
        }, indent=2))
    else:
        click.echo(f"🌐 Web ingestion: {url}")
        if stats.details.get("title"):
            click.echo(f"   Title:    {stats.details['title']}")
        click.echo(f"   Created:  {stats.entries_created}")
        click.echo(f"   Skipped:  {stats.entries_skipped}")
        click.echo(f"   Rejected: {stats.entries_rejected}")
        click.echo(f"   Errors:   {stats.errors}")


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=8780, type=int, help="Port number")
def web(db, host, port):
    """Start the UAML web dashboard."""
    from uaml.web.app import UAMLWebApp
    app = UAMLWebApp(db_path=db)
    app.serve(host=host, port=port)


@cli.group()
def compliance():
    """Compliance audit commands."""
    pass


@compliance.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--json-output", is_flag=True, help="JSON output")
def audit(db, json_output):
    """Run full compliance audit (GDPR + ISO 27001)."""
    from uaml.core.store import MemoryStore
    from uaml.compliance.auditor import ComplianceAuditor

    store = MemoryStore(db)
    auditor = ComplianceAuditor(store)
    report = auditor.full_audit()

    if json_output:
        click.echo(report.to_json())
    else:
        click.echo(f"🔍 Compliance Audit Report")
        click.echo(f"   Score:    {report.score():.1%}")
        click.echo(f"   Passed:   {report.passed()}")
        click.echo(f"   Failed:   {report.failed()}")
        click.echo(f"   Critical: {len(report.critical_findings())}")
        click.echo()

        if report.critical_findings():
            click.echo("⚠️  Critical findings:")
            for f in report.critical_findings():
                click.echo(f"   [{f.standard}] {f.check}: {f.message}")
                click.echo(f"   → {f.recommendation}")
                click.echo()

    store.close()


@compliance.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--json-output", is_flag=True, help="JSON output")
def gdpr(db, json_output):
    """Run GDPR compliance check only."""
    from uaml.core.store import MemoryStore
    from uaml.compliance.auditor import ComplianceAuditor

    store = MemoryStore(db)
    auditor = ComplianceAuditor(store)
    report = auditor.gdpr_check()

    if json_output:
        click.echo(report.to_json())
    else:
        click.echo(f"🇪🇺 GDPR Compliance Check")
        click.echo(f"   Score: {report.score():.1%} ({report.passed()}/{report.passed() + report.failed()})")
        for f in report.findings:
            icon = "✅" if f.passed else "❌"
            click.echo(f"   {icon} {f.check} ({f.article})")

    store.close()


@compliance.command()
@click.option("--db", default=DEFAULT_DB, help="Database path")
@click.option("--max-age", default=365, type=int, help="Max entry age in days")
@click.option("--json-output", is_flag=True, help="JSON output")
def retention(db, max_age, json_output):
    """Check data retention compliance."""
    from uaml.core.store import MemoryStore
    from uaml.compliance.auditor import ComplianceAuditor

    store = MemoryStore(db)
    auditor = ComplianceAuditor(store)
    report = auditor.retention_check(max_age_days=max_age)

    if json_output:
        click.echo(report.to_json())
    else:
        click.echo(f"📅 Retention Check (max {max_age} days)")
        click.echo(f"   Score: {report.score():.1%}")
        for f in report.findings:
            icon = "✅" if f.passed else "⚠️"
            click.echo(f"   {icon} {f.message}")

    store.close()


@cli.command()
@click.option("--api", is_flag=True, help="Show API reference instead of full guide")
@click.option("--features", is_flag=True, help="Show feature matrix by license tier")
@click.option("--json-output", is_flag=True, help="JSON output with all docs")
def guide(api, features, json_output):
    """Show the AI Agent Integration Guide.

    Bundled documentation for AI assistants to understand how to use UAML,
    which features are available per license tier, and how to tune the system.
    """
    from uaml.docs import get_guide, get_api_reference, get_feature_matrix, list_docs

    if json_output:
        import json
        click.echo(json.dumps({
            "guide": get_guide(),
            "api_reference": get_api_reference(),
            "feature_matrix": get_feature_matrix(),
        }, indent=2))
    elif api:
        click.echo(get_api_reference())
    elif features:
        click.echo(get_feature_matrix())
    else:
        click.echo(get_guide())


if __name__ == "__main__":
    cli()
