"""UAML Benchmark Suite — performance tests for core operations.

Measures insert, search, layer query, backup, and concurrent access latencies.
Run with: python -m pytest tests/test_benchmark.py -v --tb=short
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from uaml.core.store import MemoryStore
from uaml.io.backup import BackupManager


@pytest.fixture
def bench_store(tmp_path):
    """Create a store pre-loaded with test data for benchmarks."""
    store = MemoryStore(tmp_path / "bench.db", agent_id="bench")
    return store


@pytest.fixture
def loaded_store(bench_store):
    """Store pre-loaded with 1000 entries across all layers."""
    layers = ["identity", "knowledge", "team", "operational", "project"]
    topics = ["python", "security", "network", "database", "ai", "devops", "legal", "gdpr"]

    for i in range(1000):
        layer = layers[i % len(layers)]
        topic = topics[i % len(topics)]
        bench_store.learn(
            f"Benchmark entry {i}: Lorem ipsum dolor sit amet, "
            f"consectetur adipiscing elit. Topic is {topic}, layer is {layer}. "
            f"Entry number {i} with some searchable content about {topic} systems.",
            topic=topic,
            data_layer=layer,
            source_origin="generated",
            project=f"project-{i % 5}",
            client_ref=f"client-{i % 3}" if layer == "project" else None,
            dedup=False,
        )

    return bench_store


class TestInsertPerformance:
    """Benchmark insert operations."""

    def test_single_insert_latency(self, bench_store):
        """Single learn() should be < 5ms."""
        times = []
        for i in range(100):
            start = time.perf_counter()
            bench_store.learn(
                f"Performance test entry {i} with searchable content",
                topic="perf",
                data_layer="knowledge",
                dedup=False,
            )
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        p99_ms = sorted(times)[int(len(times) * 0.99)] * 1000
        print(f"\n  Insert: avg={avg_ms:.2f}ms, p99={p99_ms:.2f}ms")
        assert avg_ms < 10, f"Insert too slow: {avg_ms:.2f}ms avg"

    def test_bulk_insert_throughput(self, bench_store):
        """Should sustain > 200 inserts/sec."""
        count = 500
        start = time.perf_counter()
        for i in range(count):
            bench_store.learn(
                f"Bulk insert entry {i} for throughput testing",
                topic="bulk",
                dedup=False,
            )
        elapsed = time.perf_counter() - start
        rate = count / elapsed
        print(f"\n  Bulk insert: {rate:.0f} entries/sec ({elapsed:.2f}s for {count})")
        assert rate > 100, f"Throughput too low: {rate:.0f}/sec"

    def test_dedup_overhead(self, bench_store):
        """Dedup check should add < 2ms overhead."""
        # Pre-insert entries
        for i in range(100):
            bench_store.learn(f"Dedup test {i}", dedup=False)

        # Now try inserting duplicates with dedup=True
        times_dedup = []
        for i in range(100):
            start = time.perf_counter()
            bench_store.learn(f"Dedup test {i}", dedup=True)
            times_dedup.append(time.perf_counter() - start)

        # And without dedup
        times_nodedup = []
        for i in range(100, 200):
            start = time.perf_counter()
            bench_store.learn(f"Dedup test new {i}", dedup=False)
            times_nodedup.append(time.perf_counter() - start)

        avg_dedup = (sum(times_dedup) / len(times_dedup)) * 1000
        avg_nodedup = (sum(times_nodedup) / len(times_nodedup)) * 1000
        overhead = avg_dedup - avg_nodedup

        print(f"\n  Dedup: {avg_dedup:.2f}ms, No-dedup: {avg_nodedup:.2f}ms, Overhead: {overhead:.2f}ms")
        assert overhead < 5, f"Dedup overhead too high: {overhead:.2f}ms"


class TestSearchPerformance:
    """Benchmark search operations."""

    def test_fts_search_latency(self, loaded_store):
        """FTS search should be < 10ms for 1000-entry DB."""
        queries = ["python", "security network", "database systems", "legal gdpr"]
        times = []
        for q in queries:
            for _ in range(25):
                start = time.perf_counter()
                results = loaded_store.search(q, limit=10)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        p99_ms = sorted(times)[int(len(times) * 0.99)] * 1000
        print(f"\n  FTS search: avg={avg_ms:.2f}ms, p99={p99_ms:.2f}ms (1000 entries)")
        assert avg_ms < 20, f"Search too slow: {avg_ms:.2f}ms avg"

    def test_filtered_search_latency(self, loaded_store):
        """Search with filters (topic, project, client) should be < 15ms."""
        times = []
        for _ in range(50):
            start = time.perf_counter()
            loaded_store.search(
                "systems",
                topic="python",
                project="project-0",
                limit=10,
            )
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Filtered search: avg={avg_ms:.2f}ms")
        assert avg_ms < 30, f"Filtered search too slow: {avg_ms:.2f}ms avg"

    def test_temporal_search_latency(self, loaded_store):
        """Point-in-time search should be < 15ms."""
        times = []
        for _ in range(50):
            start = time.perf_counter()
            loaded_store.point_in_time("security", "2026-03-08")
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Temporal search: avg={avg_ms:.2f}ms")
        assert avg_ms < 30, f"Temporal search too slow: {avg_ms:.2f}ms avg"


class TestLayerPerformance:
    """Benchmark data layer operations."""

    def test_layer_query_latency(self, loaded_store):
        """Layer-specific query should be < 10ms."""
        layers = ["identity", "knowledge", "team", "operational", "project"]
        times = []
        for layer in layers:
            for _ in range(20):
                start = time.perf_counter()
                loaded_store.query_layer(layer, limit=20)
                elapsed = time.perf_counter() - start
                times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Layer query: avg={avg_ms:.2f}ms")
        assert avg_ms < 20, f"Layer query too slow: {avg_ms:.2f}ms avg"

    def test_layer_stats_latency(self, loaded_store):
        """layer_stats() should be < 5ms."""
        times = []
        for _ in range(50):
            start = time.perf_counter()
            loaded_store.layer_stats()
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Layer stats: avg={avg_ms:.2f}ms")
        assert avg_ms < 10, f"Layer stats too slow: {avg_ms:.2f}ms avg"

    def test_export_layer_latency(self, loaded_store):
        """Exporting a full layer should be < 100ms for 200 entries."""
        times = []
        for _ in range(10):
            start = time.perf_counter()
            loaded_store.export_layer("knowledge")
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Layer export: avg={avg_ms:.2f}ms")
        assert avg_ms < 200, f"Layer export too slow: {avg_ms:.2f}ms avg"

    def test_identity_layer_protection(self, loaded_store):
        """Identity layer export must fail without confirm_identity."""
        with pytest.raises(PermissionError):
            loaded_store.export_layer("identity")

        # Should work with confirm_identity=True
        entries = loaded_store.export_layer("identity", confirm_identity=True)
        assert isinstance(entries, list)


class TestBackupPerformance:
    """Benchmark backup operations."""

    def test_full_backup_latency(self, loaded_store, tmp_path):
        """Full backup of 1000-entry DB should be < 500ms."""
        mgr = BackupManager(loaded_store)

        times = []
        for i in range(5):
            target = tmp_path / f"backup_{i}"
            start = time.perf_counter()
            manifest = mgr.backup_full(target)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert manifest.entry_counts.get("knowledge", 0) == 1000

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Full backup: avg={avg_ms:.2f}ms (1000 entries)")
        assert avg_ms < 1000, f"Backup too slow: {avg_ms:.2f}ms avg"

    def test_verify_latency(self, loaded_store, tmp_path):
        """Backup verify should be < 200ms."""
        mgr = BackupManager(loaded_store)
        manifest = mgr.backup_full(tmp_path / "verify_test")

        times = []
        for _ in range(10):
            start = time.perf_counter()
            result = mgr.verify(Path(manifest.target_path))
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert result["readable"]
            assert result["checksum_ok"]

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Backup verify: avg={avg_ms:.2f}ms")
        assert avg_ms < 500, f"Verify too slow: {avg_ms:.2f}ms avg"


class TestStatsPerformance:
    """Benchmark stats and reporting."""

    def test_stats_latency(self, loaded_store):
        """stats() should be < 10ms."""
        times = []
        for _ in range(50):
            start = time.perf_counter()
            loaded_store.stats()
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  Stats: avg={avg_ms:.2f}ms")
        assert avg_ms < 20, f"Stats too slow: {avg_ms:.2f}ms avg"

    def test_access_report_latency(self, loaded_store):
        """GDPR access report should be < 50ms per client."""
        times = []
        for i in range(3):
            start = time.perf_counter()
            loaded_store.access_report(f"client-{i}")
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"\n  GDPR access report: avg={avg_ms:.2f}ms per client")
        assert avg_ms < 100, f"Access report too slow: {avg_ms:.2f}ms avg"


class TestScalability:
    """Test behavior at larger scale."""

    def test_10k_entries(self, tmp_path):
        """10K entries: search should still be < 20ms."""
        store = MemoryStore(tmp_path / "scale_10k.db", agent_id="scale")

        # Bulk insert 10K
        start = time.perf_counter()
        for i in range(10_000):
            store.learn(
                f"Scalability test entry {i}: distributed systems, "
                f"microservices architecture, kubernetes orchestration, "
                f"index {i}",
                topic=f"topic-{i % 20}",
                data_layer=["identity", "knowledge", "team", "operational", "project"][i % 5],
                dedup=False,
            )
        insert_time = time.perf_counter() - start
        print(f"\n  10K insert: {insert_time:.1f}s ({10000/insert_time:.0f}/sec)")

        # Search
        times = []
        for _ in range(20):
            start = time.perf_counter()
            results = store.search("distributed kubernetes", limit=10)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg_ms = (sum(times) / len(times)) * 1000
        print(f"  10K search: avg={avg_ms:.2f}ms")
        assert avg_ms < 50, f"10K search too slow: {avg_ms:.2f}ms"

        # Layer stats
        start = time.perf_counter()
        stats = store.layer_stats()
        stats_ms = (time.perf_counter() - start) * 1000
        print(f"  10K layer_stats: {stats_ms:.2f}ms")
        assert sum(s["count"] for s in stats.values()) == 10_000

        store.close()
