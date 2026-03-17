# UAML — I/O Reference

> Reference for the `uaml.io` module. Covers backup/restore, export (JSONL, JSON, CSV, Markdown), import with dedup/ethics, and encrypted export.

---

## Backup Manager (`io.backup`)

**Module:** `uaml/io/backup.py`

SQLite online backup with gzip compression, rotation, and verification.

### BackupManifest (dataclass)

Returned by `backup_full()`. Fields: `backup_path`, `entry_counts`, `integrity_ok`, `size_bytes`. Property `target_path` returns string path.

### BackupManager

```python
from uaml.io.backup import BackupManager

bm = BackupManager(store, backup_dir="/backups")
path = bm.create_backup()
```

**Constructor:** `BackupManager(store, backup_dir=None)` — Creates backup directory if missing. Defaults to `./backups`.

**Key methods:**

- `create_backup(*, compress=True, label="") → Path` — Create a backup using SQLite online backup API. Filenames: `uaml_backup_YYYYMMDD_HHMMSS[_label].db.gz`. Audited via `store._audit()`.

- `backup_full(target_dir=None, **kwargs) → BackupManifest` — Backward-compatible wrapper. Returns manifest with entry counts and integrity status.

- `verify_backup(backup_path) → dict` — Verify backup integrity. Decompresses `.gz` to temp file, runs `PRAGMA integrity_check`, counts entries. Returns `{"status": "ok"|"corrupt"|"error", "integrity": ..., "entries": ..., "size_bytes": ...}`.

- `verify(backup_path) → dict` — Backward-compat wrapper adding `readable` and `checksum_ok` keys.

- `list_backups() → list[dict]` — List all `uaml_backup_*` files in backup directory with path, name, size, creation time.

- `rotate(max_backups=10) → int` — Remove oldest backups exceeding limit. Returns number removed.

- `restore_backup(backup_path) → bool` — **⚠️ Replaces current database.** Uses SQLite backup API in reverse. Handles `.gz` decompression. Returns True on success.

**Example:**
```python
bm = BackupManager(store, backup_dir="/data/backups")

# Create compressed backup with label
path = bm.create_backup(label="pre-migration")

# Verify
result = bm.verify_backup(path)
assert result["status"] == "ok"

# List and rotate
backups = bm.list_backups()
removed = bm.rotate(max_backups=5)

# Restore (destructive!)
bm.restore_backup(path)
```

---

## Exporter (`io.exporter`)

**Module:** `uaml/io/exporter.py`

Selective export of knowledge, tasks, and artifacts to JSONL. Supports filtering, signed exports, and PQC-encrypted exports.

### Security Rules

- **IDENTITY layer** export requires explicit `confirm_identity=True` — raises `PermissionError` otherwise.
- Client data export is logged to audit trail.
- Every export is audited via `store._audit()`.

### Exporter

```python
from uaml.io import Exporter

exporter = Exporter(store)
count = exporter.export_knowledge("output.jsonl", topic="python")
```

**Export methods:**

- `export_knowledge(output, *, topic, project, client_ref, agent_id, data_layer, tags, since, until, exclude_identity=True, confirm_identity=False, limit=0) → int` — Export knowledge entries to JSONL. Returns count. Filters: topic, project, client_ref, agent_id, data_layer, tags (substring), date range (since/until).

- `export_tasks(output, *, status, project, assigned_to, client_ref, limit=0) → int` — Export tasks to JSONL.

- `export_artifacts(output, *, project, client_ref, limit=0) → int` — Export artifacts to JSONL.

- `export_all(output, *, confirm_identity=False, client_ref=None) → dict` — Full export: knowledge + tasks + artifacts + source_links + task_knowledge links. Returns counts per type.

- `export_signed(output, *, confirm_identity=False, client_ref=None) → dict` — Export with SHA-256 integrity manifest (`.sha256` file). Manifest includes file hash, entry counts, export timestamp, agent_id.

- `export_encrypted(output, *, pqc_keypair=None, confirm_identity=False, client_ref=None) → dict` — Export with PQC encryption (ML-KEM-768). Creates signed export, then encrypts with `PQCFileEncryptor`. If no keypair provided, generates one with `key_id="export"`.

**JSONL format:** Each line is a JSON object with `_type` field (`"knowledge"`, `"task"`, `"artifact"`, `"source_link"`, `"task_knowledge"`) plus all database columns.

**Example:**
```python
exporter = Exporter(store)

# Selective export
exporter.export_knowledge("python.jsonl", topic="python", since="2026-01-01")

# Full backup
counts = exporter.export_all("full.jsonl")
# {'knowledge': 150, 'tasks': 12, 'artifacts': 3, 'source_links': 8, ...}

# Signed export
counts = exporter.export_signed("backup.jsonl")
# Creates backup.jsonl + backup.jsonl.sha256

# Encrypted export
counts = exporter.export_encrypted("secure.jsonl.enc")
# {'encrypted': True, 'algorithm': 'ML-KEM-768', 'key_id': 'export', ...}
```

---

## Importer (`io.importer`)

**Module:** `uaml/io/importer.py`

Import knowledge, tasks, artifacts, and links from JSONL with deduplication, ethics re-checking, and ID remapping.

### ImportStats

Tracks import statistics: `imported`, `skipped_dedup`, `skipped_ethics`, `errors`, `by_type` (dict).

### Importer

```python
from uaml.io import Importer

importer = Importer(store)
stats = importer.import_file("backup.jsonl")
print(stats)  # ImportStats(imported=150, skipped_dedup=3, skipped_ethics=0, errors=0)
```

**Constructor:** `Importer(store, remap_ids=True)` — If `remap_ids=True` (default), assigns new IDs to avoid conflicts during merge imports. Maintains an internal `_id_map` for cross-reference remapping.

**Key method:**

- `import_file(input_path, *, override_agent=None, override_project=None, override_client=None) → ImportStats` — Import from JSONL file. Processes entries in order: knowledge → tasks → artifacts → source_links → task_knowledge (to build ID map for link remapping). Overrides let you rebind all entries to a different agent/project/client.

**Import pipeline per entry type:**

| Type | Behavior |
|------|----------|
| `knowledge` | Imported via `store.learn()` with `dedup=True`. Ethics checker runs if configured — violations increment `skipped_ethics`. |
| `task` | Imported via `store.create_task()`. IDs remapped. |
| `artifact` | Imported via `store.create_artifact()`. `task_id` remapped from ID map. |
| `source_link` | Both `source_id` and `target_id` remapped. Imported via `store.link_source()`. |
| `task_knowledge` | Both `task_id` and `entry_id` remapped. Imported via `store.link_task_knowledge()`. |

All imports are audited.

---

## Export Formats (`io.formats`)

**Module:** `uaml/io/formats.py`

Multi-format export with filtering. Complements the JSONL-focused `Exporter` with JSON, CSV, and Markdown output.

### ExportFormatter

```python
from uaml.io.formats import ExportFormatter

formatter = ExportFormatter(store)
```

**Common filters** (available on all methods): `topic` (substring match), `data_layer`, `min_confidence` (float, default 0.0), `limit` (default 10,000).

**Export methods:**

- `to_json(*, pretty=True, **filters) → str` — JSON with `{"entries": [...], "count": N}`.
- `to_jsonl(**filters) → str` — JSON Lines (one object per line).
- `to_csv(**filters) → str` — CSV with all knowledge columns as headers.
- `to_markdown(*, include_content=True, **filters) → str` — Markdown document with entries as sections. Content truncated at 1,000 chars.
- `to_dict_list(**filters) → list[dict]` — Raw list of dicts for programmatic use.
- `summary_report(**filters) → str` — Markdown summary with topic/layer breakdown and average confidence.

**Exported columns:** `id`, `topic`, `summary`, `content`, `confidence`, `data_layer`, `tags`, `source_ref`, `source_type`, `source_origin`, `created_at`, `updated_at`, `valid_from`, `valid_until`.

**Example:**
```python
formatter = ExportFormatter(store)

# JSON export filtered by topic
json_data = formatter.to_json(topic="python", min_confidence=0.7)

# CSV for spreadsheet
csv_data = formatter.to_csv(data_layer="knowledge")
with open("export.csv", "w") as f:
    f.write(csv_data)

# Markdown report
md = formatter.to_markdown(topic="security", include_content=False)

# Summary
print(formatter.summary_report())
```

---

## Module Summary

| Class | Module | Purpose |
|-------|--------|---------|
| `BackupManager` | `io.backup` | SQLite backup with compression, rotation, restore |
| `Exporter` | `io.exporter` | JSONL export with filtering, signing, PQC encryption |
| `Importer` | `io.importer` | JSONL import with dedup, ethics, ID remapping |
| `ExportFormatter` | `io.formats` | Multi-format export (JSON, CSV, JSONL, Markdown) |

## Encryption Support

- **Signed exports** use SHA-256 hash manifests for tamper detection.
- **Encrypted exports** use ML-KEM-768 (NIST FIPS 203) post-quantum cryptography via `uaml.crypto.pqc.PQCFileEncryptor`.
- Encryption is applied on top of signed exports — the manifest is also encrypted.
- Key management: auto-generated with `key_id="export"` if no keypair provided.

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

