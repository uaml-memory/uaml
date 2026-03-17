# UAML — Federation Reference

> Reference for the `uaml.federation` module. Covers multi-agent memory sharing, access control, and inter-agent messaging.

---

## Federation Hub (`federation.hub`)

**Module:** `uaml/federation/hub.py`

Central coordinator for memory sharing between UAML agents. Manages agent registration, permission-based sharing, deduplication, and provenance tracking.

### Constants

```python
SHAREABLE_LAYERS = {"knowledge", "team", "operational", "project"}
```

The **identity** layer is **never shared** — this is enforced at the `share()` level.

### ShareRequest (dataclass)

Represents a request to share entries between agents.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `from_agent` | str | — | Source agent ID |
| `to_agent` | str | — | Target agent ID |
| `entry_ids` | list[int] | — | Knowledge entry IDs to share |
| `layer` | str | `"team"` | Target data layer |
| `note` | str | `""` | Optional note |

### ShareResult (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `shared` | int | Number of entries successfully shared |
| `skipped` | int | Entries skipped (not found) |
| `denied` | int | Entries denied (permission/layer) |
| `errors` | list[str] | Error messages |
| `success` | bool | Property: `shared > 0 and not errors` |

### FederationHub

```python
from uaml.federation.hub import FederationHub, ShareRequest

hub = FederationHub()
hub.register_agent(store_cyril, "cyril", peers=["metod"])
hub.register_agent(store_metod, "metod", peers=["cyril"])
```

**Agent management:**

- `register_agent(store, agent_id, *, peers=None)` — Register an agent's MemoryStore. If `peers` is None, agent can share with anyone (open). If a list, only those agents are allowed.
- `unregister_agent(agent_id)` — Remove agent from federation.
- `list_agents() → list[dict]` — All registered agents with entry count and peers.
- `can_share(from_agent, to_agent) → bool` — Check if sharing is permitted.

**Sharing:**

- `share(request: ShareRequest) → ShareResult` — Execute a share request. Copies entries from source to target with:
  - Identity layer entries are **always blocked**
  - Permissions are checked
  - Provenance tracked via `source_ref=f"federation:{from_agent}:entry:{id}"`
  - Entries tagged with `federated,from:{agent_id}`
  - Deduplication on target (`dedup=True`)

- `sync_layer(from_agent, to_agent, layer="team", *, since=None) → ShareResult` — Sync all entries in a given layer. Optionally filter by timestamp for incremental sync.

- `share_log(limit=20) → list[dict]` — Recent share operations with `from`, `to`, `entries`, `shared`, `timestamp`.

**Example — sharing team knowledge:**
```python
hub = FederationHub()
hub.register_agent(cyril_store, "cyril", peers=["metod"])
hub.register_agent(metod_store, "metod", peers=["cyril"])

# Share specific entries
request = ShareRequest(from_agent="cyril", to_agent="metod", entry_ids=[1, 2, 3])
result = hub.share(request)
print(f"Shared: {result.shared}, Denied: {result.denied}")

# Sync entire team layer
result = hub.sync_layer("cyril", "metod", layer="team")

# Incremental sync (only new entries)
result = hub.sync_layer("cyril", "metod", layer="team", since="2026-03-01T00:00:00+00:00")
```

### Security Model

1. **Layer isolation** — identity layer is never shared (hardcoded in `SHAREABLE_LAYERS`).
2. **Peer permissions** — each agent defines allowed peers at registration. No peers list = open sharing.
3. **Provenance tracking** — every shared entry records its origin (`source_type="federation"`, `source_origin="derived"`).
4. **Deduplication** — entries are deduplicated on the target store to prevent data bloat.
5. **Audit trail** — share operations are logged in the hub's `_share_log`.

### Peer Discovery

Peer discovery is manual — agents must be explicitly registered with `register_agent()`. The hub maintains an in-memory registry (`_agents` dict). There is no automatic discovery protocol; the hub is designed as a local coordinator.

---

## Inter-Agent Messaging (`federation.messaging`)

**Module:** `uaml/federation/messaging.py`

Structured message bus for typed communication between agents.

### MessageType (enum)

| Value | Purpose |
|-------|---------|
| `QUERY` | Ask a question |
| `RESPONSE` | Reply to a query |
| `TASK` | Assign a task |
| `TASK_RESULT` | Return task result |
| `NOTIFICATION` | One-way notification |
| `SYNC_REQUEST` | Request data sync |
| `SYNC_ACK` | Acknowledge sync |
| `HEARTBEAT` | Liveness check |

### AgentMessage (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Auto-incrementing message ID |
| `sender` | str | Sender agent ID |
| `recipient` | str | Recipient agent ID |
| `msg_type` | MessageType | Message type |
| `payload` | dict | Message content |
| `timestamp` | float | Unix timestamp |
| `read` | bool | Read status |
| `reply_to` | Optional[int] | ID of message being replied to |

### MessageBus

In-memory message bus with handler registration.

```python
from uaml.federation.messaging import MessageBus, MessageType

bus = MessageBus()
bus.send("cyril", "metod", MessageType.QUERY, {"question": "What's the status?"})
messages = bus.receive("metod")
```

**Sending:**
- `send(sender, recipient, msg_type, payload, *, reply_to=None) → int` — Send a message. Returns message ID. Triggers registered handlers immediately.

**Receiving:**
- `receive(recipient, *, msg_type=None, unread_only=True, limit=50) → list[AgentMessage]` — Get messages for an agent with optional type filter.
- `mark_read(message_ids: list[int]) → int` — Mark messages as read.

**Replying:**
- `reply(original_id, sender, payload) → Optional[int]` — Reply to a message. Automatically sets `msg_type=RESPONSE` and `reply_to`.

**Threads:**
- `get_thread(message_id) → list[AgentMessage]` — Get all messages in a reply chain, sorted by timestamp.

**Handlers:**
- `on_message(agent_id, msg_type, handler: Callable)` — Register a callback for specific message types. Handler receives `AgentMessage`.

**Statistics:**
- `stats() → dict` — Total messages, unread count, active agents, message type breakdown.

**Example — task delegation:**
```python
bus = MessageBus()

# Register handler
def handle_task(msg: AgentMessage):
    print(f"Got task: {msg.payload}")

bus.on_message("metod", MessageType.TASK, handle_task)

# Send task
task_id = bus.send("cyril", "metod", MessageType.TASK, {
    "action": "deploy",
    "target": "production",
})

# Reply with result
bus.reply(task_id, "metod", {"status": "deployed", "version": "1.0.3"})

# Check thread
thread = bus.get_thread(task_id)
```

### Architecture Notes

- **In-memory** — the MessageBus stores all messages in a Python list. No persistence. Designed for same-process multi-agent setups.
- **Synchronous handlers** — handlers are called inline during `send()`. Exceptions in handlers are silently caught.
- **No routing** — direct agent-to-agent messaging. No topics, no pub/sub.
- **Stateless IDs** — sequential integer IDs, reset on bus restart.

---

## Module Summary

| Class | Module | Purpose |
|-------|--------|---------|
| `FederationHub` | `federation.hub` | Multi-agent memory sharing with access control |
| `ShareRequest` | `federation.hub` | Share request specification |
| `ShareResult` | `federation.hub` | Share operation result |
| `MessageBus` | `federation.messaging` | Inter-agent message bus |
| `MessageType` | `federation.messaging` | Message type enum |
| `AgentMessage` | `federation.messaging` | Message data container |

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

