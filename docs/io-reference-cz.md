# UAML — Reference I/O

> Reference pro modul `uaml.io`. Pokrývá zálohování/obnovu, export (JSONL, JSON, CSV, Markdown), import s deduplikací/etikou a šifrovaný export.

---

## Správce záloh (`io.backup`)

**Modul:** `uaml/io/backup.py`

SQLite online záloha s gzip kompresí, rotací a ověřením.

### BackupManifest (dataclass)

Vrácen metodou `backup_full()`. Pole: `backup_path`, `entry_counts`, `integrity_ok`, `size_bytes`. Vlastnost `target_path` vrací cestu jako string.

### BackupManager

```python
from uaml.io.backup import BackupManager

bm = BackupManager(store, backup_dir="/backups")
path = bm.create_backup()
```

**Konstruktor:** `BackupManager(store, backup_dir=None)` — Vytvoří adresář záloh, pokud neexistuje. Výchozí `./backups`.

**Klíčové metody:**

- `create_backup(*, compress=True, label="") → Path` — Vytvořit zálohu pomocí SQLite online backup API. Názvy souborů: `uaml_backup_YYYYMMDD_HHMMSS[_label].db.gz`. Auditováno přes `store._audit()`.

- `backup_full(target_dir=None, **kwargs) → BackupManifest` — Zpětně kompatibilní wrapper. Vrací manifest s počty záznamů a stavem integrity.

- `verify_backup(backup_path) → dict` — Ověřit integritu zálohy. Dekomprimuje `.gz` do dočasného souboru, spustí `PRAGMA integrity_check`, spočítá záznamy. Vrací `{"status": "ok"|"corrupt"|"error", "integrity": ..., "entries": ..., "size_bytes": ...}`.

- `verify(backup_path) → dict` — Zpětně kompatibilní wrapper s klíči `readable` a `checksum_ok`.

- `list_backups() → list[dict]` — Seznam všech `uaml_backup_*` souborů v adresáři záloh s cestou, názvem, velikostí a časem vytvoření.

- `rotate(max_backups=10) → int` — Odebrat nejstarší zálohy přesahující limit. Vrací počet odebraných.

- `restore_backup(backup_path) → bool` — **⚠️ Nahradí aktuální databázi.** Používá SQLite backup API obráceně. Zvládá `.gz` dekompresi. Vrací True při úspěchu.

**Příklad:**
```python
bm = BackupManager(store, backup_dir="/data/backups")

# Komprimovaná záloha s popiskem
path = bm.create_backup(label="pred-migraci")

# Ověření
result = bm.verify_backup(path)
assert result["status"] == "ok"

# Seznam a rotace
backups = bm.list_backups()
removed = bm.rotate(max_backups=5)

# Obnova (destruktivní!)
bm.restore_backup(path)
```

---

## Exportér (`io.exporter`)

**Modul:** `uaml/io/exporter.py`

Selektivní export znalostí, úkolů a artefaktů do JSONL. Podporuje filtrování, podepsané exporty a PQC-šifrované exporty.

### Bezpečnostní pravidla

- Export vrstvy **IDENTITY** vyžaduje explicitní `confirm_identity=True` — jinak vyvolá `PermissionError`.
- Export klientských dat se loguje do audit trailu.
- Každý export je auditován přes `store._audit()`.

### Exporter

```python
from uaml.io import Exporter

exporter = Exporter(store)
count = exporter.export_knowledge("output.jsonl", topic="python")
```

**Metody exportu:**

- `export_knowledge(output, *, topic, project, client_ref, agent_id, data_layer, tags, since, until, exclude_identity=True, confirm_identity=False, limit=0) → int` — Export znalostních záznamů do JSONL. Vrací počet. Filtry: topic, project, client_ref, agent_id, data_layer, tags (podřetězec), rozsah dat (since/until).

- `export_tasks(output, *, status, project, assigned_to, client_ref, limit=0) → int` — Export úkolů do JSONL.

- `export_artifacts(output, *, project, client_ref, limit=0) → int` — Export artefaktů do JSONL.

- `export_all(output, *, confirm_identity=False, client_ref=None) → dict` — Kompletní export: znalosti + úkoly + artefakty + source_links + task_knowledge linky. Vrací počty podle typu.

- `export_signed(output, *, confirm_identity=False, client_ref=None) → dict` — Export s SHA-256 manifestem integrity (soubor `.sha256`). Manifest obsahuje hash, počty, čas exportu, agent_id.

- `export_encrypted(output, *, pqc_keypair=None, confirm_identity=False, client_ref=None) → dict` — Export s PQC šifrováním (ML-KEM-768). Vytvoří podepsaný export, pak zašifruje pomocí `PQCFileEncryptor`. Pokud není poskytnut keypair, vygeneruje se s `key_id="export"`.

**JSONL formát:** Každý řádek je JSON objekt s polem `_type` (`"knowledge"`, `"task"`, `"artifact"`, `"source_link"`, `"task_knowledge"`) plus všechny sloupce databáze.

**Příklad:**
```python
exporter = Exporter(store)

# Selektivní export
exporter.export_knowledge("python.jsonl", topic="python", since="2026-01-01")

# Kompletní záloha
counts = exporter.export_all("full.jsonl")

# Podepsaný export
counts = exporter.export_signed("backup.jsonl")
# Vytvoří backup.jsonl + backup.jsonl.sha256

# Šifrovaný export
counts = exporter.export_encrypted("secure.jsonl.enc")
# {'encrypted': True, 'algorithm': 'ML-KEM-768', 'key_id': 'export', ...}
```

---

## Importér (`io.importer`)

**Modul:** `uaml/io/importer.py`

Import znalostí, úkolů, artefaktů a vazeb z JSONL s deduplikací, etickou kontrolou a přemapováním ID.

### ImportStats

Sleduje statistiky importu: `imported`, `skipped_dedup`, `skipped_ethics`, `errors`, `by_type` (dict).

### Importer

```python
from uaml.io import Importer

importer = Importer(store)
stats = importer.import_file("backup.jsonl")
print(stats)  # ImportStats(imported=150, skipped_dedup=3, skipped_ethics=0, errors=0)
```

**Konstruktor:** `Importer(store, remap_ids=True)` — Pokud `remap_ids=True` (výchozí), přiřadí nová ID, aby se předešlo konfliktům při merge importu. Udržuje interní `_id_map` pro přemapování křížových odkazů.

**Klíčová metoda:**

- `import_file(input_path, *, override_agent=None, override_project=None, override_client=None) → ImportStats` — Import z JSONL souboru. Zpracovává záznamy v pořadí: knowledge → tasks → artifacts → source_links → task_knowledge (pro sestavení mapy ID pro přemapování vazeb). Overrides umožňují přepojit všechny záznamy na jiného agenta/projekt/klienta.

**Import pipeline podle typu záznamu:**

| Typ | Chování |
|-----|---------|
| `knowledge` | Importováno přes `store.learn()` s `dedup=True`. Etický checker běží, pokud je nakonfigurován — porušení zvyšují `skipped_ethics`. |
| `task` | Importováno přes `store.create_task()`. ID přemapována. |
| `artifact` | Importováno přes `store.create_artifact()`. `task_id` přemapováno z mapy ID. |
| `source_link` | `source_id` i `target_id` přemapovány. Importováno přes `store.link_source()`. |
| `task_knowledge` | `task_id` i `entry_id` přemapovány. Importováno přes `store.link_task_knowledge()`. |

Všechny importy jsou auditovány.

---

## Exportní formáty (`io.formats`)

**Modul:** `uaml/io/formats.py`

Multi-formátový export s filtrováním. Doplňuje JSONL-zaměřený `Exporter` o výstup v JSON, CSV a Markdown.

### ExportFormatter

```python
from uaml.io.formats import ExportFormatter

formatter = ExportFormatter(store)
```

**Společné filtry** (dostupné na všech metodách): `topic` (podřetězec), `data_layer`, `min_confidence` (float, výchozí 0.0), `limit` (výchozí 10 000).

**Metody exportu:**

- `to_json(*, pretty=True, **filters) → str` — JSON s `{"entries": [...], "count": N}`.
- `to_jsonl(**filters) → str` — JSON Lines (jeden objekt na řádek).
- `to_csv(**filters) → str` — CSV se všemi sloupci znalostí jako záhlaví.
- `to_markdown(*, include_content=True, **filters) → str` — Markdown dokument se záznamy jako sekcemi. Obsah oříznut na 1 000 znaků.
- `to_dict_list(**filters) → list[dict]` — Surový seznam dictů pro programové použití.
- `summary_report(**filters) → str` — Markdown shrnutí s rozložením podle topic/layer a průměrnou confidence.

**Exportované sloupce:** `id`, `topic`, `summary`, `content`, `confidence`, `data_layer`, `tags`, `source_ref`, `source_type`, `source_origin`, `created_at`, `updated_at`, `valid_from`, `valid_until`.

**Příklad:**
```python
formatter = ExportFormatter(store)

# JSON export filtrovaný podle topic
json_data = formatter.to_json(topic="python", min_confidence=0.7)

# CSV pro tabulkový procesor
csv_data = formatter.to_csv(data_layer="knowledge")
with open("export.csv", "w") as f:
    f.write(csv_data)

# Markdown report
md = formatter.to_markdown(topic="security", include_content=False)

# Shrnutí
print(formatter.summary_report())
```

---

## Přehled modulů

| Třída | Modul | Účel |
|-------|-------|------|
| `BackupManager` | `io.backup` | SQLite záloha s kompresí, rotací, obnovou |
| `Exporter` | `io.exporter` | JSONL export s filtrováním, podpisem, PQC šifrováním |
| `Importer` | `io.importer` | JSONL import s deduplikací, etikou, přemapováním ID |
| `ExportFormatter` | `io.formats` | Multi-formátový export (JSON, CSV, JSONL, Markdown) |

## Podpora šifrování

- **Podepsané exporty** používají SHA-256 hash manifesty pro detekci neoprávněné manipulace.
- **Šifrované exporty** používají ML-KEM-768 (NIST FIPS 203) post-kvantovou kryptografii přes `uaml.crypto.pqc.PQCFileEncryptor`.
- Šifrování se aplikuje na podepsané exporty — manifest je také zašifrován.
- Správa klíčů: automaticky generované s `key_id="export"`, pokud není poskytnut keypair.

---
© 2026 GLG, a.s. All rights reserved. / Všechna práva vyhrazena.
License: Non-commercial use only. Commercial use requires a paid license from GLG, a.s.

