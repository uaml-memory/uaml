# ADR-007: Federated Architecture — Each Agent is an Autonomous Unit

**Status:** accepted  
**Date:** 2026-03-08  
**Decision makers:** Pavel (Vedoucí), Cyril, Metod  
**Context source:** Team discussion on Discord, architectural review

## Context

Current architecture is centralized: VPS holds master SQLite databases, other machines get copies via git. Neo4j runs only on Pepa-PC. This creates problems:

- Binary SQLite files in git cause merge conflicts and data corruption
- Data duplication across machines with no clear ownership
- Race conditions when multiple agents restart services on the same machine
- Logs and session data shared unnecessarily — they only make sense locally
- Single point of failure for Neo4j (Pepa-PC)

Pavel's insight: each machine should own its own data. Shared data flows through explicit sync, not full DB replication.

## Decision

**Federated architecture:** Each agent machine is an autonomous unit with its own complete data stack.

### Per-machine stack
```
┌──────────────────────┐
│  Agent (OpenClaw)     │
│  ↓                    │
│  SQLite (own raw data)│ ← sessions, logs, heartbeat, identity
│  ↓                    │
│  Neo4j (own graph)    │ ← local knowledge graph
│  ↓                    │
│  Dashboard (own view) │ ← reads only local data
└──────────┬───────────┘
           │
    git/API sync (selective)
           │
    Only SHARED layers:
    • verified knowledge
    • team tasks
    • code, skills, ADRs
```

### Data ownership by layer

| Data Layer | Scope | Sync | Example |
|-----------|-------|------|---------|
| **Identity** | LOCAL only | Never shared | Agent personality, preferences, keys |
| **Operational** | LOCAL only | Never shared | Logs, sessions, heartbeat, metrics, temp files |
| **Knowledge** | LOCAL → shared | Export/import via git or API | Verified facts, learned skills |
| **Team** | SHARED | Git sync | Tasks, decisions, ADRs, documentation |
| **Project** | SHARED (per-project) | Git sync | Client data, deliverables |

### Sync mechanism

- **Code, skills, config, ADRs:** Git (as today)
- **Knowledge exchange:** JSON export/import (not binary DB files)
- **Tasks/TODO:** JSON or API sync (not binary todo.db in git)
- **Logs, sessions, identity:** NEVER synced — stay on origin machine

### Key change: No binary DB files in git

Instead of committing `memory.db` and `todo.db` as binary blobs:
1. Each machine maintains its own SQLite databases
2. Shared knowledge exported as JSON/JSONL
3. Import happens through UAML API (`/api/knowledge` POST)
4. Dedup check on import (content_hash)

## Consequences

### Positive
- **No more merge conflicts** on binary DB files
- **No more data corruption** from concurrent access
- **Clear ownership:** each machine responsible for its own data
- **Security:** compromise of one machine doesn't expose raw data of others
- **Scalability:** adding a new agent = add a new autonomous node
- **Resilience:** each machine operates independently, survives network outages
- **Privacy:** logs and operational data stay where they belong
- **Aligns with 5-layer model** (ADR-004): identity+operational=local, knowledge+team+project=shared

### Negative
- **More infrastructure per machine:** each needs Neo4j (lightweight: Community Edition)
- **Eventual consistency:** shared knowledge has sync delay
- **Initial migration:** must split current centralized data into per-machine ownership
- **Complexity:** need import/export tooling for knowledge exchange

### Risks
- Knowledge divergence if sync fails silently (mitigation: sync health checks)
- Neo4j on VPS adds memory pressure (mitigation: lightweight config, Community Edition)
- Conflict resolution for shared tasks edited on multiple machines

## Migration Path

1. **Phase 1:** Stop committing binary DB files to git (use .gitignore)
2. **Phase 2:** Build JSON export/import for knowledge and tasks
3. **Phase 3:** Deploy Neo4j on VPS (Metod) and Notebook1 (Cyril)
4. **Phase 4:** Each machine runs its own continuous learner → own memory.db
5. **Phase 5:** Shared knowledge sync via UAML API (JSON, with dedup)

## Compliance Impact

- **GDPR:** Data minimization — each machine stores only what it needs
- **ISO 27001:** Clear data ownership and access boundaries per machine
- **Certification:** Smaller audit surface — certify each node independently
- **Security:** Blast radius of compromise limited to one machine

## References

- ADR-004: Five-Layer Data Classification Model
- ADR-006: Dual-Database Architecture (SQLite + Neo4j)
- Pavel's architectural vision: "každý stroj má své vlastní SQL, plní do vlastní Neo4j"
- Today's incident: memory.db corruption from concurrent git sync + server restarts

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

