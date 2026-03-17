# ADR-006: MCP as Universal Bridge Interface

**Status:** Accepted  
**Date:** 2026-03-06  
**Updated:** 2026-03-10  
**Decision Makers:** Pavel (Vedoucí), Metod, Cyril  
**Relates to:** ADR-001, ADR-004 (ethics)

## Context

UAML needs a standard interface for AI agents to interact with the memory layer. Multiple options exist: custom REST API, gRPC, native library calls, or MCP (Model Context Protocol).

## Decision

Use **MCP (Model Context Protocol)** as the primary bridge interface for AI agent integration.

- MCP = standard interface (discovery + invocation)
- UAML = smart implementation (ethics, temporal, PQC, knowledge graph)
- Two transport modes: stdio (local) and HTTP/SSE (remote)
- REST API as secondary consumer for dashboards and non-agent clients

### MCP Tools (8)

| Tool | Purpose | Added |
|------|---------|-------|
| `memory_search` | Full-text search with temporal, client isolation, topic/project filtering | v0.1 |
| `memory_learn` | Store knowledge with confidence, provenance, temporal validity | v0.1 |
| `memory_entity` | Entity lookup with knowledge connections | v0.1 |
| `memory_stats` | Database statistics (counts, topics, agents) | v0.1 |
| `memory_ethics_check` | Pre-validate content against ethics rules (Asimov hierarchy) | v0.1 |
| `task_create` | Create tasks linked to projects/agents | v0.1 |
| `task_list` | List/filter tasks by status, project, assignee, client | v0.1 |
| `task_update` | Update task status, assignment, priority | v0.1 |

### MCP Resources (2)

| URI | Purpose |
|-----|---------|
| `uaml://stats` | Current database statistics (JSON) |
| `uaml://schema` | Database schema version and table structure (JSON) |

### Implementation Details

- **Protocol:** JSON-RPC 2.0 over MCP
- **Protocol version:** 2024-11-05
- **Server info:** name=uaml, version=0.1.0
- **Capabilities:** tools (listChanged: false), resources (listChanged: false)
- **HTTP transport:** POST / for JSON-RPC, GET /health for health check
- **Client isolation:** All tools support `client_ref` parameter for data separation

## Consequences

### Positive
- Standard protocol: any MCP-compatible agent can use UAML immediately
- Anthropic-backed standard with growing ecosystem
- Dual transport: local (stdio, zero network) and remote (HTTP)
- Agent doesn't need UAML-specific SDK — just MCP client
- Ethics pre-validation available before writes (memory_ethics_check)
- Client isolation built into every tool — supports multi-tenant use

### Negative
- MCP is still evolving — specification may change
- JSON-RPC overhead for high-frequency operations
- Not all agent frameworks support MCP yet

### Risks
- MCP adoption stalls → mitigated by REST API as fallback
- Breaking spec changes → pin to specific MCP version

## Alternatives Considered

- **REST-only:** Universal but no standard discovery/schema mechanism — kept as secondary interface
- **gRPC:** Efficient but requires proto compilation, less accessible — rejected
- **Native Python API only:** Not language-agnostic — rejected for bridge layer
- **LangChain Tools format:** Ties to LangChain ecosystem — rejected per ADR-001

## References

- MCP specification: https://modelcontextprotocol.io
- Anthropic MCP announcement
- Implementation: `uaml/mcp/server.py`
- Tests: `tests/test_mcp.py`
- Ethics layer: ADR-004, `uaml/ethics/checker.py`

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

