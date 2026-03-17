# UAML v1.0 — Referenční přehled modulů

> Kompletní přehled všech UAML modulů. Pro rychlý start viz [Facade API](#facade-api).

## Facade API

Nejjednodušší způsob použití UAML. Jeden import, všechny funkce.

```python
from uaml.facade import UAML

uaml = UAML()
uaml.learn("Python 3.13 odstranil GIL")
results = uaml.search("Python vlákna")
uaml.audit_report()
```

---

## Jádrové moduly (`uaml.core`)

### MemoryStore (`core.store`)
SQLite databázové úložiště znalostí. Srdce UAML.
- `learn(content, topic, source_type, confidence)` — uložení znalosti
- `search(query, limit, topic)` — fulltextové vyhledávání
- `get(id)` — načtení dle ID
- `update(id, content)` — aktualizace záznamu
- `delete_entry(id)` — smazání s kaskádou
- `purge(dry_run=True)` — hromadné čištění (bezpečné výchozí nastavení)
- `stats()` — statistiky databáze

### Schema (`core.schema`)
Správa databázového schématu s automatickou migrací.
- 5vrstvá architektura: identita, znalosti, tým, operační, projekt
- Tabulky: `knowledge`, `audit_log`, `source_links`, `provenance`, `personality`

### Policy Engine (`core.policy`)
Klasifikace dotazů a směrování modelů.
- `QueryClass`: FACTUAL, ANALYTICAL, CREATIVE, SENSITIVE
- `ModelProfile`: LOCAL_FAST, LOCAL_QUALITY, CLOUD_QUALITY
- `RiskLevel`: LOW, MEDIUM, HIGH, CRITICAL
- Směrování dotazů na vhodné modely podle citlivosti

### Config Manager (`core.config`)
YAML/env konfigurace s prefixem `UAML_`.
- Vrstvená konfigurace: výchozí → soubor → prostředí
- Podpora hot reload

### Embeddings (`core.embeddings`)
Generování vektorových embeddingů pro sémantické vyhledávání.

### Validace (`core.validation`)
Validace a sanitizace vstupů pro všechna API.

### Verzování (`core.versioning`)
Sledování verzí znalostních záznamů s diffem.

### Snímky (`core.snapshot`)
Point-in-time snímky databáze pro temporální dotazy.

### Změnový log (`core.changelog`)
Sledování všech změn znalostních záznamů.

### Dávkové operace (`core.batch`)
Hromadný import/export se sledováním průběhu.

### Vyhledávání (`core.search`)
Pokročilé vyhledávání s filtry, facety a řazením.

### Tagování (`core.tagging`)
Automatické tagování a správa tagů.

### Šablony (`core.templates`)
Šablony odpovědí pro konzistentní formátování.

### Události (`core.events`)
Event bus pro komunikaci mezi moduly.

### Health Check (`core.health`)
Monitorování zdraví systému a diagnostika.

### Plánovač (`core.scheduler`)
Plánování údržbových úloh (čištění, optimalizace).

### Retence (`core.retention`)
Politiky uchovávání dat: archivace, smazání, revize, snížení důvěry.

### Deduplikace (`core.dedup`)
Detekce duplikátů se strategiemi: keep_newest, keep_highest_confidence, keep_first.

### Detekce kontradikcí (`core.contradiction`)
Detekce konfliktních znalostních záznamů analýzou překryvu slov.

### Notifikace (`core.notifications`)
Vícekanálové notifikace s throttlingem.

### Metriky (`core.metrics`)
Sběr výkonnostních a uživatelských metrik.

### Migrace (`core.migration`)
Správa migrací databázového schématu.

### Asociativní paměť (`core.associative`)
Propojení souvisejících znalostních záznamů.

---

## Reasoning (`uaml.reasoning`)

### Temporální reasoner (`reasoning.temporal`)
Časově uvědomělé dotazy s hodnocením čerstvosti (exponenciální pokles).

### Context Builder (`reasoning.context`)
Sestavení optimálního kontextu pro LLM s rozpočtováním.

### Sumarizér (`reasoning.summarizer`)
Automatická sumarizace znalostí a konverzací.

### Řešení konfliktů (`reasoning.conflicts`)
Řešení rozporů mezi znalostními záznamy.

### Hodnocení znalostí (`reasoning.scoring`)
Skóre: úplnost 0.25, čerstvost 0.20, důvěra 0.30, kvalita 0.25.

### Extrakce entit (`reasoning.entities`)
Extrakce pojmenovaných entit z textu.

### Auto-tagger (`reasoning.tagger`)
Automatické tagování témat a kategorií.

### Linker znalostí (`reasoning.linker`)
Objevování a vytváření vazeb mezi záznamy.

### Clustering (`reasoning.clustering`)
Seskupování podobných znalostí pomocí Jaccardovy podobnosti.

### Cache vyhledávání (`reasoning.cache`)
LRU cache s TTL pro výsledky hledání.

### Analytika (`reasoning.analytics`)
Analytika používání a přehledy knowledge base.

### Detekce incidentů (`reasoning.incidents`)
Detekce clusterů chyb a anomálií v logách.

### Optimalizér (`reasoning.optimizer`)
Doporučení pro optimalizaci databáze a dotazů.

---

## Bezpečnost (`uaml.security`)

### Security Configurator (`security.configurator`)
Webový průvodce pro hardening OS. Viz [dokumentace](security-configurator-cz.md).

### Expert Mode (`security.configurator.ExpertMode`)
Kontrolovaný, časově omezený přístup AI agenta k hostitelskému OS.

### Hardening (`security.hardening`)
Bezpečnostní audit a doporučení.
- `SecurityAuditor.score()`: 100 základ, -20 za kritické, -5 za varování

### Rate Limiter (`security.ratelimit`)
Token bucket rate limiting per agent per operace.

### RBAC (`security.rbac`)
Řízení přístupu na základě rolí pro multi-agent prostředí.

### Sanitizér dat (`security.sanitizer`)
Detekce PII: email, telefon, IP, platební karta, API klíč, pole hesla.

---

## Compliance (`uaml.compliance`)

### Compliance Auditor (`compliance.auditor`)
Automatizované kontroly shody s GDPR, ISO 27001.

### Správa souhlasů (`compliance.consent`)
Sledování a správa záznamů o souhlasech subjektů údajů.

### DPIA Generátor (`compliance.dpia`)
Posouzení vlivu na ochranu osobních údajů s automatickým hodnocením rizik.

### Inventář dat (`compliance.inventory`)
Katalog všech činností zpracování dat.

---

## Kryptografie (`uaml.crypto`)

### Post-kvantové šifrování (`crypto.pqc`)
ML-KEM-768 (NIST FIPS 203) — šifrování odolné proti kvantovým počítačům.

### Úschova klíčů (`crypto.escrow`)
Shamirovo sdílení tajemství pro obnovu klíčů.

### Digitální podpisy (`crypto.signatures`)
Podepisování a ověřování znalostních záznamů a exportů.

---

## Audit (`uaml.audit`)

### Přístupový log (`audit.access`)
Sledování všech přístupů k datům: kdo, co, kdy.

### Audit Collector (`audit.collector`)
Agregace auditních událostí ze všech modulů.

### Log Store (`audit.logs`)
Strukturované aplikační logování v tabulce `app_logs`.

### Provenance Tracker (`audit.provenance`)
Sledování datové linie a historie transformací.

### Audit Stream (`audit.stream`)
Streamování auditních událostí v reálném čase.

---

## Federace (`uaml.federation`)

### Federation Hub (`federation.hub`)
Sdílení znalostí mezi agenty s řízením přístupu.
- Vrstva identity se NIKDY nesdílí
- Selektivní synchronizace podle tématu/tagu

### Messaging (`federation.messaging`)
Komunikační protokol mezi agenty.

---

## Graf (`uaml.graph`)

### Lokální graf (`graph.local`)
SQLite knowledge graf (bez závislosti na Neo4j).
- BFS nejkratší cesta s konfigurovatelnou max_depth
- CRUD operace na uzlech a hranách

### Synchronizace grafu (`graph.sync`)
Synchronizace grafu se store znalostí.

---

## Ingest (`uaml.ingest`)

### Chat Ingestor (`ingest.chat`)
Import chatové historie (OpenClaw, Discord, Telegram formáty).

### Markdown Ingestor (`ingest.markdown`)
Import znalostí z Markdown souborů.

### Web Ingestor (`ingest.web`)
Extrakce a ukládání znalostí z webových stránek.

### Continuous Ingestor (`ingest.continuous`)
Sledování adresářů a automatický import nových souborů.

### Pipeline (`ingest.pipeline`)
Vícekroková ingestion s transformačními kroky.

### Search Ingestor (`ingest.search`)
Import z výsledků vyhledávačů.

---

## I/O (`uaml.io`)

### Zálohy (`io.backup`)
Šifrované zálohy databáze s rotací.

### Exporter (`io.exporter`)
Export znalostí ve více formátech (JSON, CSV, Markdown).

### Importer (`io.importer`)
Import z externích formátů.

### Formáty (`io.formats`)
Detekce a konverze formátů.

---

## Hlas (`uaml.voice`)

### Text-to-Speech (`voice.tts`)
- **Starter:** Piper TTS (běží na Raspberry Pi)
- **Enterprise:** XTTS v2 (klonování hlasu)

### Speech-to-Text (`voice.stt`)
- **Starter:** Whisper.cpp
- **Enterprise:** faster-whisper s GPU akcelerací

---

## Pluginy (`uaml.plugins`)

### Plugin Manager (`plugins.manager`)
Načítání/odlehčování pluginů s error handlingem a lifecycle hooky.
- ON_ERROR hooky pro graceful degradaci
- Izolace pluginů

---

## API & Integrace

### REST API (`api.server`)
HTTP API server pro externí integrace.

### API Klient (`api.client`)
Python klient pro REST API.

### MCP Server (`mcp.server`)
Model Context Protocol bridge pro integraci s LLM nástroji.

---

## Web (`uaml.web`)

### Webový dashboard (`web.app`)
Správa znalostí v prohlížeči.

---

## CLI (`uaml.cli`)

```bash
uaml init          # Inicializace databáze
uaml learn "..."   # Uložení znalosti
uaml search "..."  # Vyhledávání
uaml export        # Export dat
uaml audit         # Spuštění auditu
uaml serve         # Spuštění API serveru
```

---

## Focus Engine (`uaml.core.focus_engine`)

Inteligentní engine pro výběr kontextu s rozpočtováním tokenů, skórováním relevance, temporálním úpadkem a deduplikací.

- **`FocusEngine`** — hlavní třída
  - `process(query, records, config)` → filtrované, seřazené záznamy v rámci rozpočtu
  - `get_token_usage_report()` → statistiky využití
- **3 úrovně recallu**: Tier 1 (pouze shrnutí), Tier 2 (shrnutí + nedávné), Tier 3 (plný recall)
- **3 presety**: `conservative` (1500 tokenů), `standard` (3000), `research` (8000)

### Focus Config (`core.focus_config`)

Typovaná správa konfigurací pro Focus Engine.

- **Datové třídy**: `FocusEngineConfig`, `InputFilterConfig`, `OutputFilterConfig`, `AgentRulesConfig`
- **Funkce**: `load_focus_config()`, `save_focus_config()`, `load_preset(name)`
- **`SavedConfigStore`** — SQLite úložiště pojmenovaných konfigurací s oddělením `filter_type` (input/output/both)

### Rules Changelog (`core.rules_changelog`)

SQLite append-only audit trail pro změny konfigurace Focus Engine.

- Záznamy: kdo, kdy, co se změnilo, proč, očekávaný dopad
- `RulesChangelog.log_change(field, old, new, changed_by, reason)`

---

## Vstupní filtry (`uaml.ingest.filters`)

Pipeline filtry pro vstupní cestu Focus Engine.

- **6 fází**: `fe_length_filter`, `fe_max_tokens_filter`, `fe_rate_limit`, `fe_category_filter`, `fe_pii_detector`, `fe_relevance_gate`
- **`setup_input_filter(pipeline, config)`** — registrace všech fází
- **`detect_pii(text)`** — detekce PII s českými vzory (IČO, DIČ, rodné číslo)

---

## Feature Gate (`uaml.feature_gate`)

Systém přepínačů funkcí podle licenční úrovně.

- **`FeatureGate`** — kontrola dostupnosti funkcí
- **`TrialManager`** — správa trial období (freeze model)
- **`@require_feature`** dekorátor — ochrana přístupu k funkcím
- 17 funkcí v `FEATURE_MATRIX` přes Starter/Pro/Enterprise

---

## Licencování (`uaml.licensing`)

Generování, validace a správa licenčních klíčů.

- **`LicenseKey`** — HMAC-SHA256 podepsané klíče s tier, expirací, funkcemi
- **`LicenseManager`** — životní cyklus: generovat, validovat, odvolat, obnovit
- Úrovně: `starter`, `pro`, `enterprise`

---

## Zákaznický portál (`uaml.customer`)

Webový portál pro registraci, přihlášení a dashboard.

- **`CustomerDB`** — SQLite s PBKDF2 hashováním hesel
- **`CustomerPortal`** — HTTP handler pro `/portal` routy
- Dvojjazyčný: čeština + angličtina

---

## Etický kontrolor (`uaml.ethics.checker`)

Evaluační engine pro etická pravidla.

- **14 výchozích pravidel** napříč kategoriemi citlivosti
- **Asimovova hierarchie**: bezpečnost > lidská kontrola > shoda > užitečnost
- `EthicsChecker.check(data)` → `APPROVED` / `FLAGGED` / `REJECTED`

---

## Modely (`uaml.core.models`)

Datové modely a typy používané napříč systémem.

- **Enumy**: `DataLayer`, `MemoryType`, `SourceOrigin`, `LegalBasis`
- **Datové třídy**: `KnowledgeEntry`, `Entity`, `Task`, `Artifact`

### Základ ingestoru (`ingest.base`)

Bázové třídy pro fáze ingest pipeline.

- **`BaseIngestor`** — abstraktní bázová třída s metodou `ingest()`
- **`IngestStats`** — sledování zpracovaných/přeskočených/chybných záznamů

---

## Architektura

```
┌──────────────────────────────────────────────────────────────┐
│                      UAML Facade API                          │
├──────────────────────────────────────────────────────────────┤
│  Reasoning    │  Bezpečnost   │  Compliance   │  Federace    │
│  - Temporální │  - Konfigurátor│ - Auditor     │  - Hub       │
│  - Kontext    │  - Expert Mode│  - Souhlas    │  - Messaging │
│  - Skóring    │  - RBAC       │  - DPIA       │              │
│  - Clustering │  - Sanitizér  │  - Inventář   │              │
├──────────────────────────────────────────────────────────────┤
│                    Jádro (MemoryStore)                        │
│  Schema │ Policy │ Config │ Events │ Health │ Retence        │
├──────────────────────────────────────────────────────────────┤
│  Krypto (PQC)  │  Audit Trail  │  Graf   │  Ingest Pipeline │
├──────────────────────────────────────────────────────────────┤
│  I/O (Zálohy/Export)  │  Hlas (TTS/STT)   │  Pluginy        │
├──────────────────────────────────────────────────────────────┤
│                    SQLite (Local-First)                       │
└──────────────────────────────────────────────────────────────┘
```

---

*© 2026 GLG, a.s. — UAML v1.0*
