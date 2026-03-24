"""Tests for UAML Local Knowledge Graph."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.graph.local import LocalGraph


@pytest.fixture
def graph(tmp_path):
    store = MemoryStore(tmp_path / "graph.db", agent_id="test")
    g = LocalGraph(store)
    yield g
    store.close()


class TestLocalGraph:
    def test_add_get_entity(self, graph):
        graph.add_entity("Python", "language", properties={"version": "3.12"})
        e = graph.get_entity("Python")
        assert e is not None
        assert e.entity_type == "language"
        assert e.properties["version"] == "3.12"

    def test_entity_not_found(self, graph):
        assert graph.get_entity("nonexistent") is None

    def test_add_relation(self, graph):
        graph.add_entity("UAML", "project")
        graph.add_entity("Python", "language")
        graph.add_relation("UAML", "uses", "Python")

        neighbors = graph.neighbors("UAML", direction="outgoing")
        assert len(neighbors) == 1
        assert neighbors[0].target == "Python"
        assert neighbors[0].relation == "uses"

    def test_incoming_neighbors(self, graph):
        graph.add_entity("A", "node")
        graph.add_entity("B", "node")
        graph.add_relation("A", "links_to", "B")

        incoming = graph.neighbors("B", direction="incoming")
        assert len(incoming) == 1
        assert incoming[0].source == "A"

    def test_both_directions(self, graph):
        graph.add_entity("A", "node")
        graph.add_entity("B", "node")
        graph.add_entity("C", "node")
        graph.add_relation("A", "to", "B")
        graph.add_relation("C", "to", "B")

        both = graph.neighbors("B", direction="both")
        assert len(both) >= 1

    def test_shortest_path(self, graph):
        for name in ("A", "B", "C", "D"):
            graph.add_entity(name, "node")
        graph.add_relation("A", "to", "B")
        graph.add_relation("B", "to", "C")
        graph.add_relation("C", "to", "D")

        path = graph.shortest_path("A", "D")
        assert path == ["A", "B", "C", "D"]

    def test_shortest_path_no_route(self, graph):
        graph.add_entity("X", "node")
        graph.add_entity("Y", "node")
        assert graph.shortest_path("X", "Y") is None

    def test_shortest_path_same(self, graph):
        graph.add_entity("A", "node")
        assert graph.shortest_path("A", "A") == ["A"]

    def test_stats(self, graph):
        graph.add_entity("A", "type1")
        graph.add_entity("B", "type2")
        graph.add_relation("A", "rel", "B")

        stats = graph.stats()
        assert stats["entities"] == 2
        assert stats["relations"] == 1
        assert "type1" in stats["entity_types"]

    def test_remove_entity(self, graph):
        graph.add_entity("X", "temp")
        graph.add_entity("Y", "temp")
        graph.add_relation("X", "to", "Y")

        assert graph.remove_entity("X") is True
        assert graph.get_entity("X") is None
        assert graph.neighbors("Y", direction="incoming") == []

    def test_entity_links(self, graph):
        graph.add_entity("UAML", "project", entry_ids=[1, 2, 3])
        e = graph.get_entity("UAML")
        assert e.entry_ids == [1, 2, 3]

    def test_relation_filter(self, graph):
        graph.add_entity("A", "node")
        graph.add_entity("B", "node")
        graph.add_entity("C", "node")
        graph.add_relation("A", "uses", "B")
        graph.add_relation("A", "owns", "C")

        uses = graph.neighbors("A", relation="uses", direction="outgoing")
        assert len(uses) == 1
        assert uses[0].target == "B"
