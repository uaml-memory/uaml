"""
UAML Quality Pipeline — enriches knowledge records with quality metadata.

Never modifies raw content. Only adds tags, scores, and audit entries.
Every record maintains source_ref for full traceability.

Community edition includes: language detection, noise classification, importance scoring.
Pro/Enterprise tiers add: semantic dedup, contradiction detection, trust scoring.
"""

import re
import sqlite3
import json
import logging
from typing import Optional

log = logging.getLogger("uaml.quality")


# ── Language Detection ──────────────────────────────────────

_CZ_CHARS = set("áčďéěíňóřšťúůýž")
_CZ_WORDS = {
    "je", "na", "se", "to", "že", "ale", "tak", "jak", "pro", "aby",
    "byl", "být", "má", "jsou", "mám", "máme", "bylo", "bude", "kde",
    "ten", "tam", "tady", "když", "nebo", "než", "ani", "jenom",
    "tento", "která", "který", "které", "toto", "takže", "protože",
    "potřebujeme", "funguje", "opravit", "nasadit", "zkontrolovat",
}

def detect_language(text: str) -> str:
    """Detect language: 'cs', 'en', or 'mixed'."""
    words = text.lower().split()
    if not words:
        return "en"
    
    cz_score = 0
    en_score = 0
    
    for w in words[:100]:
        if any(c in _CZ_CHARS for c in w):
            cz_score += 2
        if w in _CZ_WORDS:
            cz_score += 1
        if w in {"the", "is", "are", "was", "have", "has", "been", "will",
                 "with", "from", "that", "this", "for", "not", "but", "can"}:
            en_score += 1
    
    total = cz_score + en_score
    if total == 0:
        return "en"
    
    cz_ratio = cz_score / total
    if cz_ratio > 0.6:
        return "cs"
    elif cz_ratio < 0.3:
        return "en"
    return "mixed"


# ── Noise Classification ──────────────────────────────────────

_NOISE_PATTERNS = [
    r'^(OK|ok|Ok|NO_REPLY|HEARTBEAT_OK)\s*[.!]?\s*$',
    r'^\[\[reply_to_current\]\]\s*(OK|ok|rozumím|díky|jasně|super|paráda)\s*[.!]?\s*$',
    r'^(Pullnuto|Hotovo|Done|DONE|Ano|Ne|Yes|No)[.!]?\s*$',
    r'^(díky|děkuji|thanks|thx|ok|jasně|rozumím|fajn)\s*[.!]?\s*$',
    r'^```',
]
_NOISE_RE = [re.compile(p, re.MULTILINE) for p in _NOISE_PATTERNS]

_MARGINAL_INDICATORS = [
    "moment", "čekej", "zkusím", "pracuji na", "podívám se",
    "hned to", "ještě chvíli", "zpracovávám",
]

def classify_noise(text: str) -> str:
    """Classify: 'useful', 'marginal', or 'noise'."""
    stripped = text.strip()
    
    if len(stripped) < 15:
        return "noise"
    
    for pat in _NOISE_RE:
        if pat.match(stripped):
            return "noise"
    
    lower = stripped.lower()
    for indicator in _MARGINAL_INDICATORS:
        if lower.startswith(indicator):
            return "marginal"
    
    return "useful"


# ── Importance Scoring ──────────────────────────────────────

_DECISION_KEYWORDS = {
    "rozhodnutí", "rozhodl", "schváleno", "zamítnuto", "pravidlo",
    "decision", "decided", "approved", "rejected", "rule",
    "nové pravidlo", "new rule", "dohodnuto", "agreed",
}

_FACT_KEYWORDS = {
    "běží na", "port", "ip", "server", "konfigurace", "config",
    "verze", "version", "nainstalován", "installed", "endpoint",
    "databáze", "database", "služba", "service", "cesta", "path",
}

def compute_importance(text: str, noise_class: str, dedup_status: str = "unique") -> float:
    """Compute importance score 1-10."""
    if noise_class == "noise":
        return 1.0
    if noise_class == "marginal":
        return 3.0
    
    score = 5.0
    lower = text.lower()
    
    for kw in _DECISION_KEYWORDS:
        if kw in lower:
            score += 1.5
            break
    
    fact_count = sum(1 for kw in _FACT_KEYWORDS if kw in lower)
    score += min(fact_count * 0.3, 1.5)
    
    if len(text) > 500:
        score += 0.5
    if len(text) > 1000:
        score += 0.5
    
    entities = len(re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|\b\d{4,}\b|/\w+/\w+', text))
    score += min(entities * 0.2, 1.0)
    
    if dedup_status == "duplicate":
        score -= 2.0
    elif dedup_status == "similar":
        score -= 1.0
    
    return max(1.0, min(10.0, round(score, 1)))


# ── Quality Pipeline ──────────────────────────────────────

class QualityPipeline:
    """
    Enriches knowledge records with quality metadata.
    
    Community edition stages:
        - Language detection (cs/en/mixed)
        - Noise classification (useful/marginal/noise)
        - Importance scoring (1-10)
    
    Pro/Enterprise stages (require license):
        - Semantic deduplication
        - Contradiction detection
        - Trust scoring
    
    Usage:
        pipeline = QualityPipeline(db_path)
        result = pipeline.process(knowledge_id)
    """
    
    QUALITY_VERSION = 1
    
    def __init__(self, db_path: str, embedding_fn=None, neo4j_driver=None):
        self.db_path = db_path
        self.embedding_fn = embedding_fn
        self._neo4j_driver = neo4j_driver
    
    def process(self, knowledge_id: int) -> dict:
        """Run quality pipeline on a single record."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        row = conn.execute(
            "SELECT * FROM knowledge WHERE id = ?", (knowledge_id,)
        ).fetchone()
        
        if not row:
            conn.close()
            return {"error": "not found"}
        
        text = row["content"] or ""
        results = {}
        
        # Stage 1: Language Detection
        lang = detect_language(text)
        results["lang"] = lang
        self._update_and_audit(conn, knowledge_id, "lang", row["lang"], lang, "lang_detect")
        
        # Stage 2: Noise Classification
        noise_class = classify_noise(text)
        results["noise_class"] = noise_class
        self._update_and_audit(conn, knowledge_id, "noise_class", row["noise_class"], noise_class, "noise_classify")
        
        # Stage 3: Importance Scoring
        importance = compute_importance(text, noise_class)
        results["importance_score"] = importance
        self._update_and_audit(conn, knowledge_id, "importance_score",
                              str(row["importance_score"]), str(importance), "importance_score")
        
        # Pro/Enterprise stages (semantic dedup, contradiction, trust) not included
        # in community edition. See https://uaml-memory.com for details.
        
        conn.execute(
            "UPDATE knowledge SET quality_version = ? WHERE id = ?",
            (self.QUALITY_VERSION, knowledge_id)
        )
        results["quality_version"] = self.QUALITY_VERSION
        
        conn.commit()
        conn.close()
        return results
    
    def process_batch(self, limit: int = 1000, min_age_hours: int = 0) -> dict:
        """Process unprocessed records in batch."""
        conn = sqlite3.connect(self.db_path)
        
        rows = conn.execute(
            """SELECT id FROM knowledge 
               WHERE (quality_version IS NULL OR quality_version < ?)
               AND created_at < datetime('now', ?)
               ORDER BY created_at DESC LIMIT ?""",
            (self.QUALITY_VERSION, f'-{min_age_hours} hours', limit)
        ).fetchall()
        conn.close()
        
        stats = {"processed": 0, "noise": 0, "useful": 0, "marginal": 0, "errors": 0}
        for (kid,) in rows:
            try:
                result = self.process(kid)
                stats["processed"] += 1
                nc = result.get("noise_class", "useful")
                stats[nc] = stats.get(nc, 0) + 1
            except Exception:
                stats["errors"] += 1
        
        return stats
    
    def _update_and_audit(self, conn, kid: int, column: str, old_val, new_val, action: str):
        """Update column and log to quality_audit."""
        if str(old_val) == str(new_val):
            return
        
        conn.execute(
            f"UPDATE knowledge SET {column} = ? WHERE id = ?",
            (new_val, kid)
        )
        conn.execute(
            """INSERT INTO quality_audit (knowledge_id, action, old_value, new_value, details)
               VALUES (?, ?, ?, ?, ?)""",
            (kid, action, str(old_val) if old_val else None, str(new_val),
             json.dumps({"column": column, "version": self.QUALITY_VERSION}))
        )
