#!/usr/bin/env python3
"""Run LongMemEval with neural embeddings (sentence-transformers)."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from run_benchmark import load_dataset, ingest_sessions, check_answer, clean_query, STOP_WORDS
from uaml.core.store import MemoryStore
from uaml.core.embeddings import EmbeddingEngine


def make_neural_embedder():
    """Create sentence-transformers embedder."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    def embed(texts):
        return model.encode(texts, show_progress_bar=False).tolist()
    return embed


def retrieve_neural_hybrid(engine: EmbeddingEngine, question: str, top_k: int = 5) -> str:
    """Hybrid retrieval with neural embeddings — vector-heavy weights."""
    results = engine.hybrid_search(
        question, limit=top_k,
        vector_weight=0.7, fts_weight=0.2, associative_weight=0.1,
    )
    if not results:
        return "[NO_RETRIEVAL]"
    return "\n---\n".join(r.content[:500] for r in results)


def main():
    dataset = load_dataset("oracle")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    dataset = dataset[:limit]

    embedder = make_neural_embedder()
    
    results = []
    hits = 0
    total = 0
    type_stats = {}
    start = time.time()

    for i, instance in enumerate(dataset):
        store = MemoryStore(":memory:")
        ingest_sessions(store, instance)
        
        engine = EmbeddingEngine(store, embed_fn=embedder)
        engine.index_all()

        question = instance.get("question", instance.get("query", ""))
        expected = instance.get("answer", instance.get("expected_answer", ""))
        q_type = instance.get("question_type", instance.get("type", "unknown"))
        
        context = retrieve_neural_hybrid(engine, question)
        check = check_answer(context, expected)
        
        total += 1
        is_hit = check["retrieval_hit"]
        if is_hit:
            hits += 1
        
        type_stats.setdefault(q_type, {"hits": 0, "total": 0})
        type_stats[q_type]["total"] += 1
        if is_hit:
            type_stats[q_type]["hits"] += 1
        
        results.append({
            "id": i,
            "type": q_type,
            "hit": is_hit,
            "exact": check["exact_match"],
        })
        
        store.close()
        
        if (i + 1) % 50 == 0:
            elapsed = time.time() - start
            rate = hits / total * 100
            print(f"  [{i+1}/{len(dataset)}] Hit rate: {rate:.1f}% ({elapsed:.0f}s)")

    elapsed = time.time() - start
    hit_rate = hits / total * 100

    print(f"\n{'='*60}")
    print(f"Neural Hybrid — {total} instances in {elapsed:.1f}s")
    print(f"Overall hit rate: {hit_rate:.1f}% ({hits}/{total})")
    print(f"\nPer type:")
    for t, s in sorted(type_stats.items()):
        r = s["hits"] / s["total"] * 100
        print(f"  {t}: {r:.1f}% ({s['hits']}/{s['total']})")

    out_path = Path(__file__).parent / "results_oracle_neural_500.json"
    with open(out_path, "w") as f:
        json.dump({
            "mode": "neural_hybrid",
            "model": "paraphrase-multilingual-MiniLM-L12-v2",
            "total": total,
            "hits": hits,
            "hit_rate": hit_rate,
            "elapsed_s": round(elapsed, 1),
            "type_stats": type_stats,
            "results": results,
        }, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
