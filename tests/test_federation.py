"""Tests for UAML Federation Hub."""

from __future__ import annotations

import pytest

from uaml.core.store import MemoryStore
from uaml.federation.hub import FederationHub, ShareRequest


@pytest.fixture
def hub(tmp_path):
    h = FederationHub()
    store_a = MemoryStore(tmp_path / "a.db", agent_id="cyril")
    store_b = MemoryStore(tmp_path / "b.db", agent_id="metod")

    # Add some data to agent A
    store_a.learn("Shared knowledge about Python", data_layer="team", topic="python")
    store_a.learn("Private identity data", data_layer="identity")
    store_a.learn("Project deliverable", data_layer="project", topic="uaml")

    h.register_agent(store_a, "cyril")
    h.register_agent(store_b, "metod")

    yield h, store_a, store_b

    store_a.close()
    store_b.close()


class TestFederationHub:
    def test_register_and_list(self, hub):
        h, _, _ = hub
        agents = h.list_agents()
        assert len(agents) == 2

    def test_share_team_entry(self, hub):
        h, store_a, store_b = hub
        req = ShareRequest(
            from_agent="cyril", to_agent="metod",
            entry_ids=[1], layer="team",
        )
        result = h.share(req)
        assert result.shared == 1
        assert result.success

    def test_identity_never_shared(self, hub):
        h, _, _ = hub
        req = ShareRequest(
            from_agent="cyril", to_agent="metod",
            entry_ids=[2], layer="team",  # entry 2 is identity
        )
        result = h.share(req)
        assert result.denied == 1
        assert result.shared == 0

    def test_permission_check(self, tmp_path):
        h = FederationHub()
        store_a = MemoryStore(tmp_path / "perm_a.db", agent_id="a")
        store_b = MemoryStore(tmp_path / "perm_b.db", agent_id="b")
        store_c = MemoryStore(tmp_path / "perm_c.db", agent_id="c")

        store_a.learn("Data", data_layer="team")

        h.register_agent(store_a, "a", peers=["b"])  # a can only share with b
        h.register_agent(store_b, "b")
        h.register_agent(store_c, "c")

        assert h.can_share("a", "b") is True
        assert h.can_share("a", "c") is False

        req = ShareRequest(from_agent="a", to_agent="c", entry_ids=[1])
        result = h.share(req)
        assert result.denied == 1

        store_a.close()
        store_b.close()
        store_c.close()

    def test_sync_layer(self, hub):
        h, store_a, store_b = hub
        result = h.sync_layer("cyril", "metod", layer="team")
        assert result.shared >= 1

    def test_share_log(self, hub):
        h, _, _ = hub
        req = ShareRequest(from_agent="cyril", to_agent="metod", entry_ids=[1])
        h.share(req)
        log = h.share_log()
        assert len(log) == 1
        assert log[0]["from"] == "cyril"

    def test_unregister(self, hub):
        h, _, _ = hub
        h.unregister_agent("metod")
        assert len(h.list_agents()) == 1

    def test_nonexistent_entry(self, hub):
        h, _, _ = hub
        req = ShareRequest(from_agent="cyril", to_agent="metod", entry_ids=[999])
        result = h.share(req)
        assert result.skipped == 1
