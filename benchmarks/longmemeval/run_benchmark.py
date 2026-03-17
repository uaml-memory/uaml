#!/usr/bin/env python3
"""UAML LongMemEval Benchmark — evaluate UAML memory against standard benchmarks.

Tests 5 core long-term memory abilities:
1. Information Extraction (single-session-user, single-session-assistant, single-session-preference)
2. Multi-Session Reasoning (multi-session)
3. Knowledge Updates (knowledge-update)
4. Temporal Reasoning (temporal-reasoning)
5. Abstention (questions ending with _abs)

Usage:
    python run_benchmark.py --dataset oracle --limit 50    # Quick test with oracle retrieval
    python run_benchmark.py --dataset small --limit 500    # Full benchmark
    python run_benchmark.py --dataset oracle --type temporal-reasoning  # Specific type
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

# Add parent to path for UAML imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from uaml.core.store import MemoryStore


def load_dataset(dataset: str = "oracle") -> list[dict]:
    """Load LongMemEval dataset."""
    data_dir = Path(__file__).parent / "data"
    if dataset == "oracle":
        path = data_dir / "longmemeval_oracle.json"
    elif dataset == "small":
        path = data_dir / "longmemeval_s_cleaned.json"
    else:
        raise ValueError(f"Unknown dataset: {dataset}")

    with open(path) as f:
        return json.load(f)


def ingest_sessions(store: MemoryStore, instance: dict) -> int:
    """Ingest chat history sessions into UAML store. Returns entry count."""
    sessions = instance.get("haystack_sessions", instance.get("history_sessions", []))
    count = 0

    dates = instance.get("haystack_dates", [])
    session_ids = instance.get("haystack_session_ids", [])

    for idx, session in enumerate(sessions):
        session_id = session_ids[idx] if idx < len(session_ids) else f"s{idx}"
        date = dates[idx] if idx < len(dates) else ""

        # Sessions can be list of messages or dict with messages
        if isinstance(session, list):
            messages = session
        elif isinstance(session, dict):
            messages = session.get("messages", session.get("conversation", []))
        else:
            continue

        # Combine all messages in session into one knowledge entry
        content_parts = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                text = msg.get("content", msg.get("text", ""))
            else:
                role = "unknown"
                text = str(msg)
            if text:
                content_parts.append(f"[{role}]: {text}")

        if content_parts:
            content = "\n".join(content_parts)
            store.learn(
                content,
                topic=f"session_{session_id}",
                source_type="chat",
                source_ref=f"session:{session_id}",
                tags=f"longmemeval,session_{session_id}",
                valid_from=date if date else None,
                data_layer="knowledge",
                source_origin="external",
                dedup=False,
            )
            count += 1

    return count


STOP_WORDS = {
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "they",
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "can", "may", "might", "shall", "must", "need",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "and", "but", "or", "not", "no", "if", "when", "what", "which", "who",
    "how", "where", "why", "that", "this", "these", "those", "any", "all",
    "each", "some", "most", "other", "than", "then", "so", "just", "also",
    "very", "much", "more", "many", "first", "new", "its", "had",
}


def clean_query(question: str, max_terms: int = 8) -> str:
    """Extract key terms from a natural language question for FTS5."""
    words = question.lower().replace("?", "").replace("'", "").split()
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    # Take most distinctive terms (longer words tend to be more specific)
    keywords.sort(key=len, reverse=True)
    return " ".join(keywords[:max_terms])


def retrieve_answer(store: MemoryStore, question: str, top_k: int = 5) -> str:
    """Use UAML search to retrieve relevant context for answering."""
    # First try with cleaned query
    cleaned = clean_query(question)
    results = store.search(cleaned, limit=top_k) if cleaned else []

    # Fallback: try original question words
    if not results:
        results = store.search(question, limit=top_k)

    if not results:
        return "[NO_RETRIEVAL]"

    # Combine top results as context
    context_parts = []
    for r in results:
        snippet = r.entry.content[:500]
        context_parts.append(snippet)

    return "\n---\n".join(context_parts)


def retrieve_answer_associative(store: MemoryStore, question: str, top_k: int = 5) -> str:
    """Enhanced retrieval using FTS5 + associative memory + contextual recall.

    Combines three retrieval strategies:
    1. FTS5 keyword search (same as baseline)
    2. Contextual recall (multi-signal associative matching)
    3. If FTS returns results, find related entries for broader coverage
    """
    from uaml.core.associative import AssociativeEngine

    engine = AssociativeEngine(store)
    seen_ids = set()
    context_parts = []

    # Strategy 1: FTS5 keyword search
    cleaned = clean_query(question)
    fts_results = store.search(cleaned, limit=top_k) if cleaned else []

    for r in fts_results:
        if r.entry.id not in seen_ids:
            seen_ids.add(r.entry.id)
            context_parts.append(r.entry.content[:500])

    # Strategy 2: Contextual recall (keyword-based multi-signal)
    assoc_results = engine.contextual_recall(question, limit=top_k, min_score=0.01)
    for a in assoc_results:
        if a.entry_id not in seen_ids:
            seen_ids.add(a.entry_id)
            context_parts.append(a.content[:500])

    # Strategy 3: Related entries from top FTS result (graph expansion)
    if fts_results and len(context_parts) < top_k:
        top_id = fts_results[0].entry.id
        related = engine.find_related(top_id, limit=3, min_score=0.01)
        for a in related:
            if a.entry_id not in seen_ids:
                seen_ids.add(a.entry_id)
                context_parts.append(a.content[:500])

    if not context_parts:
        return "[NO_RETRIEVAL]"

    return "\n---\n".join(context_parts[:top_k])


def retrieve_answer_hybrid(store: MemoryStore, question: str, top_k: int = 5) -> str:
    """Hybrid retrieval using embedding engine (TF-IDF + FTS5 + associative)."""
    from uaml.core.embeddings import EmbeddingEngine

    engine = EmbeddingEngine(store)
    engine.index_all()

    results = engine.hybrid_search(question, limit=top_k)
    if not results:
        return "[NO_RETRIEVAL]"

    return "\n---\n".join(r.content[:500] for r in results)


def check_answer(predicted_context: str, expected_answer: str) -> dict:
    """Check if the expected answer can be found in the retrieved context.

    This is a retrieval-only evaluation (no LLM generation).
    Measures whether UAML's search retrieves the right information.
    """
    answer_lower = str(expected_answer).lower().strip()
    context_lower = predicted_context.lower()

    # Exact substring match
    exact_match = answer_lower in context_lower

    # Token overlap (Jaccard-like)
    answer_tokens = set(answer_lower.split())
    context_tokens = set(context_lower.split())
    if answer_tokens:
        overlap = len(answer_tokens & context_tokens) / len(answer_tokens)
    else:
        overlap = 0.0

    # Key phrases (split answer into 2-3 word phrases)
    answer_words = answer_lower.split()
    phrase_hits = 0
    phrase_total = 0
    for i in range(len(answer_words) - 1):
        phrase = f"{answer_words[i]} {answer_words[i+1]}"
        phrase_total += 1
        if phrase in context_lower:
            phrase_hits += 1

    phrase_score = phrase_hits / phrase_total if phrase_total > 0 else 0.0

    return {
        "exact_match": exact_match,
        "token_overlap": round(overlap, 3),
        "phrase_score": round(phrase_score, 3),
        "retrieval_hit": exact_match or overlap > 0.6 or phrase_score > 0.5,
    }


def run_benchmark(
    dataset: str = "oracle",
    limit: int = 50,
    question_type: Optional[str] = None,
    top_k: int = 5,
    verbose: bool = False,
    mode: str = "fts",  # "fts" or "associative"
) -> dict:
    """Run the LongMemEval benchmark against UAML.

    Returns aggregate metrics.
    """
    data = load_dataset(dataset)

    # Filter by type if specified
    if question_type:
        data = [d for d in data if d["question_type"] == question_type]

    data = data[:limit]

    if mode == "hybrid":
        retrieve_fn = retrieve_answer_hybrid
    elif mode == "associative":
        retrieve_fn = retrieve_answer_associative
    else:
        retrieve_fn = retrieve_answer

    print(f"📊 UAML LongMemEval Benchmark")
    print(f"   Dataset: {dataset}")
    print(f"   Mode: {mode}")
    print(f"   Instances: {len(data)}")
    print(f"   Top-K: {top_k}")
    if question_type:
        print(f"   Type filter: {question_type}")
    print()

    results_by_type: dict[str, list] = {}
    total_ingest_time = 0.0
    total_search_time = 0.0
    total_entries = 0

    for i, instance in enumerate(data):
        qid = instance["question_id"]
        qtype = instance["question_type"]
        question = instance["question"]
        expected = instance["answer"]
        is_abstention = qid.endswith("_abs")

        # Create fresh store for each instance
        store = MemoryStore(":memory:", agent_id="benchmark")

        # Ingest sessions
        t0 = time.perf_counter()
        entry_count = ingest_sessions(store, instance)
        ingest_time = time.perf_counter() - t0
        total_ingest_time += ingest_time
        total_entries += entry_count

        # Retrieve
        t0 = time.perf_counter()
        context = retrieve_fn(store, question, top_k=top_k)
        search_time = time.perf_counter() - t0
        total_search_time += search_time

        # Evaluate
        if is_abstention:
            # For abstention questions, no retrieval = correct
            result = {
                "exact_match": context == "[NO_RETRIEVAL]",
                "token_overlap": 0.0,
                "phrase_score": 0.0,
                "retrieval_hit": context == "[NO_RETRIEVAL]",
            }
        else:
            result = check_answer(context, expected)

        result["question_id"] = qid
        result["question_type"] = qtype
        result["ingest_time_ms"] = round(ingest_time * 1000, 1)
        result["search_time_ms"] = round(search_time * 1000, 1)
        result["entry_count"] = entry_count

        results_by_type.setdefault(qtype, []).append(result)

        if verbose:
            hit = "✅" if result["retrieval_hit"] else "❌"
            print(f"  {hit} [{qtype}] {qid}: overlap={result['token_overlap']}, "
                  f"phrase={result['phrase_score']}, ingest={result['ingest_time_ms']:.0f}ms, "
                  f"search={result['search_time_ms']:.1f}ms")

        store.close()

        # Progress
        if (i + 1) % 25 == 0:
            print(f"  ... {i+1}/{len(data)} processed")

    # Aggregate
    print(f"\n{'='*60}")
    print(f"📊 RESULTS — UAML LongMemEval ({dataset}, mode={mode})")
    print(f"{'='*60}\n")

    all_results = []
    for qtype in sorted(results_by_type.keys()):
        type_results = results_by_type[qtype]
        all_results.extend(type_results)

        hits = sum(1 for r in type_results if r["retrieval_hit"])
        exact = sum(1 for r in type_results if r["exact_match"])
        avg_overlap = sum(r["token_overlap"] for r in type_results) / len(type_results)
        avg_phrase = sum(r["phrase_score"] for r in type_results) / len(type_results)

        print(f"  {qtype}:")
        print(f"    Retrieval Hit Rate: {hits}/{len(type_results)} ({hits/len(type_results)*100:.1f}%)")
        print(f"    Exact Match:        {exact}/{len(type_results)} ({exact/len(type_results)*100:.1f}%)")
        print(f"    Avg Token Overlap:  {avg_overlap:.3f}")
        print(f"    Avg Phrase Score:   {avg_phrase:.3f}")
        print()

    # Overall
    total = len(all_results)
    total_hits = sum(1 for r in all_results if r["retrieval_hit"])
    total_exact = sum(1 for r in all_results if r["exact_match"])
    avg_ingest = total_ingest_time / total * 1000
    avg_search = total_search_time / total * 1000

    print(f"  OVERALL:")
    print(f"    Retrieval Hit Rate: {total_hits}/{total} ({total_hits/total*100:.1f}%)")
    print(f"    Exact Match:        {total_exact}/{total} ({total_exact/total*100:.1f}%)")
    print(f"    Avg Ingest Time:    {avg_ingest:.1f}ms per instance")
    print(f"    Avg Search Time:    {avg_search:.1f}ms per query")
    print(f"    Total Entries:      {total_entries}")
    print()

    summary = {
        "dataset": dataset,
        "mode": mode,
        "instances": total,
        "top_k": top_k,
        "overall": {
            "retrieval_hit_rate": round(total_hits / total, 4),
            "exact_match_rate": round(total_exact / total, 4),
            "avg_ingest_ms": round(avg_ingest, 1),
            "avg_search_ms": round(avg_search, 1),
        },
        "by_type": {},
    }

    for qtype, type_results in results_by_type.items():
        hits = sum(1 for r in type_results if r["retrieval_hit"])
        exact = sum(1 for r in type_results if r["exact_match"])
        summary["by_type"][qtype] = {
            "count": len(type_results),
            "retrieval_hit_rate": round(hits / len(type_results), 4),
            "exact_match_rate": round(exact / len(type_results), 4),
        }

    # Save results
    output_path = Path(__file__).parent / f"results_{dataset}_{mode}_{limit}.json"
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  Results saved to: {output_path}")

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UAML LongMemEval Benchmark")
    parser.add_argument("--dataset", choices=["oracle", "small"], default="oracle")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--type", dest="question_type", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--mode", choices=["fts", "associative", "hybrid"], default="fts",
                       help="Retrieval mode: fts (baseline), associative, or hybrid (vector+fts+assoc)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    run_benchmark(
        dataset=args.dataset,
        limit=args.limit,
        question_type=args.question_type,
        top_k=args.top_k,
        verbose=args.verbose,
        mode=args.mode,
    )
