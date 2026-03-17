"""Tests for UAML Inter-Agent Messaging."""

from __future__ import annotations

import pytest

from uaml.federation.messaging import MessageBus, MessageType


@pytest.fixture
def bus():
    return MessageBus()


class TestMessageBus:
    def test_send_and_receive(self, bus):
        mid = bus.send("cyril", "metod", MessageType.QUERY, {"q": "status?"})
        assert mid == 1
        msgs = bus.receive("metod")
        assert len(msgs) == 1
        assert msgs[0].payload["q"] == "status?"

    def test_receive_filter_type(self, bus):
        bus.send("a", "b", MessageType.QUERY, {})
        bus.send("a", "b", MessageType.NOTIFICATION, {})
        queries = bus.receive("b", msg_type=MessageType.QUERY)
        assert len(queries) == 1

    def test_mark_read(self, bus):
        mid = bus.send("a", "b", MessageType.QUERY, {})
        bus.mark_read([mid])
        msgs = bus.receive("b", unread_only=True)
        assert len(msgs) == 0

    def test_reply(self, bus):
        mid = bus.send("cyril", "metod", MessageType.QUERY, {"q": "hello"})
        reply_id = bus.reply(mid, "metod", {"a": "world"})
        assert reply_id is not None
        # Cyril should receive the reply
        msgs = bus.receive("cyril")
        assert len(msgs) == 1
        assert msgs[0].msg_type == MessageType.RESPONSE

    def test_reply_nonexistent(self, bus):
        assert bus.reply(999, "a", {}) is None

    def test_handler(self, bus):
        received = []
        bus.on_message("metod", MessageType.TASK, lambda m: received.append(m))
        bus.send("cyril", "metod", MessageType.TASK, {"do": "something"})
        assert len(received) == 1

    def test_thread(self, bus):
        mid = bus.send("a", "b", MessageType.QUERY, {"q": "1"})
        bus.reply(mid, "b", {"a": "1"})
        thread = bus.get_thread(mid)
        assert len(thread) == 2

    def test_stats(self, bus):
        bus.send("cyril", "metod", MessageType.QUERY, {})
        bus.send("metod", "cyril", MessageType.RESPONSE, {})
        stats = bus.stats()
        assert stats["total_messages"] == 2
        assert "cyril" in stats["agents"]
        assert "metod" in stats["agents"]

    def test_unread_count(self, bus):
        bus.send("a", "b", MessageType.NOTIFICATION, {})
        bus.send("a", "b", MessageType.NOTIFICATION, {})
        stats = bus.stats()
        assert stats["unread"] == 2

    def test_receive_all(self, bus):
        bus.send("a", "b", MessageType.QUERY, {})
        mid = bus.receive("b")[0].id
        bus.mark_read([mid])
        all_msgs = bus.receive("b", unread_only=False)
        assert len(all_msgs) == 1
