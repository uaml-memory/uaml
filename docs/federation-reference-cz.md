# UAML — Reference federace

> Reference pro modul `uaml.federation`. Pokrývá multi-agentní sdílení paměti, řízení přístupu a inter-agentní zasílání zpráv.

---

## Federation Hub (`federation.hub`)

**Modul:** `uaml/federation/hub.py`

Centrální koordinátor pro sdílení paměti mezi UAML agenty. Spravuje registraci agentů, sdílení na základě oprávnění, deduplikaci a sledování provenance.

### Konstanty

```python
SHAREABLE_LAYERS = {"knowledge", "team", "operational", "project"}
```

Vrstva **identity** se **nikdy nesdílí** — vynuceno na úrovni `share()`.

### ShareRequest (dataclass)

Reprezentuje požadavek na sdílení záznamů mezi agenty.

| Pole | Typ | Výchozí | Popis |
|------|-----|---------|-------|
| `from_agent` | str | — | ID zdrojového agenta |
| `to_agent` | str | — | ID cílového agenta |
| `entry_ids` | list[int] | — | ID znalostních záznamů ke sdílení |
| `layer` | str | `"team"` | Cílová datová vrstva |
| `note` | str | `""` | Volitelná poznámka |

### ShareResult (dataclass)

| Pole | Typ | Popis |
|------|-----|-------|
| `shared` | int | Počet úspěšně sdílených záznamů |
| `skipped` | int | Přeskočené záznamy (nenalezené) |
| `denied` | int | Zamítnuté záznamy (oprávnění/vrstva) |
| `errors` | list[str] | Chybové zprávy |
| `success` | bool | Vlastnost: `shared > 0 and not errors` |

### FederationHub

```python
from uaml.federation.hub import FederationHub, ShareRequest

hub = FederationHub()
hub.register_agent(store_cyril, "cyril", peers=["metod"])
hub.register_agent(store_metod, "metod", peers=["cyril"])
```

**Správa agentů:**

- `register_agent(store, agent_id, *, peers=None)` — Registrovat MemoryStore agenta. Pokud `peers` je None, agent může sdílet s kýmkoli (otevřený). Pokud seznam, pouze tito agenti jsou povoleni.
- `unregister_agent(agent_id)` — Odebrat agenta z federace.
- `list_agents() → list[dict]` — Všichni registrovaní agenti s počtem záznamů a peers.
- `can_share(from_agent, to_agent) → bool` — Ověřit, zda je sdílení povoleno.

**Sdílení:**

- `share(request: ShareRequest) → ShareResult` — Provést požadavek na sdílení. Kopíruje záznamy ze zdroje do cíle s:
  - Záznamy vrstvy identity jsou **vždy blokovány**
  - Oprávnění jsou kontrolována
  - Provenance sledována přes `source_ref=f"federation:{from_agent}:entry:{id}"`
  - Záznamy tagované `federated,from:{agent_id}`
  - Deduplikace na cíli (`dedup=True`)

- `sync_layer(from_agent, to_agent, layer="team", *, since=None) → ShareResult` — Synchronizovat všechny záznamy ve vrstvě. Volitelně filtrovat podle časového razítka pro inkrementální synchronizaci.

- `share_log(limit=20) → list[dict]` — Poslední operace sdílení s `from`, `to`, `entries`, `shared`, `timestamp`.

**Příklad — sdílení týmových znalostí:**
```python
hub = FederationHub()
hub.register_agent(cyril_store, "cyril", peers=["metod"])
hub.register_agent(metod_store, "metod", peers=["cyril"])

# Sdílení konkrétních záznamů
request = ShareRequest(from_agent="cyril", to_agent="metod", entry_ids=[1, 2, 3])
result = hub.share(request)
print(f"Sdíleno: {result.shared}, Zamítnuto: {result.denied}")

# Synchronizace celé týmové vrstvy
result = hub.sync_layer("cyril", "metod", layer="team")

# Inkrementální sync (pouze nové záznamy)
result = hub.sync_layer("cyril", "metod", layer="team", since="2026-03-01T00:00:00+00:00")
```

### Bezpečnostní model

1. **Izolace vrstev** — vrstva identity se nikdy nesdílí (hardcoded v `SHAREABLE_LAYERS`).
2. **Oprávnění peers** — každý agent definuje povolené peers při registraci. Žádný seznam peers = otevřené sdílení.
3. **Sledování provenance** — každý sdílený záznam eviduje svůj původ (`source_type="federation"`, `source_origin="derived"`).
4. **Deduplikace** — záznamy jsou deduplicovány na cílovém storu.
5. **Audit trail** — operace sdílení jsou logovány v `_share_log` hubu.

### Objevování peers

Objevování peers je manuální — agenti musí být explicitně registrováni přes `register_agent()`. Hub udržuje in-memory registr (dict `_agents`). Neexistuje automatický protokol pro objevování; hub je navržen jako lokální koordinátor.

---

## Inter-agentní zasílání zpráv (`federation.messaging`)

**Modul:** `uaml/federation/messaging.py`

Strukturovaná sběrnice zpráv pro typovanou komunikaci mezi agenty.

### MessageType (enum)

| Hodnota | Účel |
|---------|------|
| `QUERY` | Položit otázku |
| `RESPONSE` | Odpovědět na dotaz |
| `TASK` | Přiřadit úkol |
| `TASK_RESULT` | Vrátit výsledek úkolu |
| `NOTIFICATION` | Jednosměrná notifikace |
| `SYNC_REQUEST` | Požadavek na synchronizaci dat |
| `SYNC_ACK` | Potvrzení synchronizace |
| `HEARTBEAT` | Kontrola živosti |

### AgentMessage (dataclass)

| Pole | Typ | Popis |
|------|-----|-------|
| `id` | int | Automaticky inkrementované ID zprávy |
| `sender` | str | ID odesílajícího agenta |
| `recipient` | str | ID příjemce |
| `msg_type` | MessageType | Typ zprávy |
| `payload` | dict | Obsah zprávy |
| `timestamp` | float | Unix časové razítko |
| `read` | bool | Stav přečtení |
| `reply_to` | Optional[int] | ID zprávy, na kterou se odpovídá |

### MessageBus

In-memory sběrnice zpráv s registrací handlerů.

```python
from uaml.federation.messaging import MessageBus, MessageType

bus = MessageBus()
bus.send("cyril", "metod", MessageType.QUERY, {"question": "Jaký je stav?"})
messages = bus.receive("metod")
```

**Odesílání:**
- `send(sender, recipient, msg_type, payload, *, reply_to=None) → int` — Odeslat zprávu. Vrací ID. Spouští registrované handlery okamžitě.

**Příjem:**
- `receive(recipient, *, msg_type=None, unread_only=True, limit=50) → list[AgentMessage]` — Získat zprávy pro agenta s volitelným filtrem typu.
- `mark_read(message_ids: list[int]) → int` — Označit zprávy jako přečtené.

**Odpovídání:**
- `reply(original_id, sender, payload) → Optional[int]` — Odpovědět na zprávu. Automaticky nastaví `msg_type=RESPONSE` a `reply_to`.

**Vlákna:**
- `get_thread(message_id) → list[AgentMessage]` — Získat všechny zprávy v řetězci odpovědí, seřazené podle času.

**Handlery:**
- `on_message(agent_id, msg_type, handler: Callable)` — Registrovat callback pro specifické typy zpráv.

**Statistiky:**
- `stats() → dict` — Celkový počet zpráv, nepřečtené, aktivní agenti, rozložení podle typu.

**Příklad — delegování úkolu:**
```python
bus = MessageBus()

# Registrace handleru
def handle_task(msg: AgentMessage):
    print(f"Přijat úkol: {msg.payload}")

bus.on_message("metod", MessageType.TASK, handle_task)

# Odeslání úkolu
task_id = bus.send("cyril", "metod", MessageType.TASK, {
    "action": "deploy",
    "target": "production",
})

# Odpověď s výsledkem
bus.reply(task_id, "metod", {"status": "nasazeno", "version": "1.0.3"})
```

### Poznámky k architektuře

- **In-memory** — MessageBus ukládá zprávy v Python listu. Žádná persistence. Navrženo pro multi-agentní setupy v jednom procesu.
- **Synchronní handlery** — handlery se volají inline během `send()`. Výjimky v handlerech jsou tiše zachyceny.
- **Bez routingu** — přímá komunikace agent-agent. Žádné topicy, žádný pub/sub.
- **Bezstavová ID** — sekvenční celá čísla, reset při restartu busu.

---

## Přehled modulů

| Třída | Modul | Účel |
|-------|-------|------|
| `FederationHub` | `federation.hub` | Multi-agentní sdílení paměti s řízením přístupu |
| `ShareRequest` | `federation.hub` | Specifikace požadavku na sdílení |
| `ShareResult` | `federation.hub` | Výsledek operace sdílení |
| `MessageBus` | `federation.messaging` | Inter-agentní sběrnice zpráv |
| `MessageType` | `federation.messaging` | Enum typů zpráv |
| `AgentMessage` | `federation.messaging` | Datový kontejner zprávy |

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

