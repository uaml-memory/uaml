# Copyright (c) 2026 GLG, a.s. All rights reserved.
# Licensed under dual license: Non-commercial use free, commercial use requires paid license.
# See LICENSE file for details.
"""UAML Inter-Agent Messaging — structured communication between agents.

Enables agents to send typed messages (queries, responses, tasks,
notifications) through a shared message bus.

Usage:
    from uaml.federation.messaging import MessageBus, MessageType

    bus = MessageBus()
    bus.send("cyril", "metod", MessageType.QUERY, {"question": "What's the status?"})
    messages = bus.receive("metod")
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Optional, Callable


class MessageType(enum.Enum):
    """Types of inter-agent messages."""
    QUERY = "query"
    RESPONSE = "response"
    TASK = "task"
    TASK_RESULT = "task_result"
    NOTIFICATION = "notification"
    SYNC_REQUEST = "sync_request"
    SYNC_ACK = "sync_ack"
    HEARTBEAT = "heartbeat"


@dataclass
class AgentMessage:
    """A message between agents."""
    id: int
    sender: str
    recipient: str
    msg_type: MessageType
    payload: dict
    timestamp: float
    read: bool = False
    reply_to: Optional[int] = None


class MessageBus:
    """Central message bus for inter-agent communication."""

    def __init__(self):
        self._messages: list[AgentMessage] = []
        self._next_id: int = 1
        self._handlers: dict[str, dict[MessageType, list[Callable]]] = {}

    def send(
        self,
        sender: str,
        recipient: str,
        msg_type: MessageType,
        payload: dict,
        *,
        reply_to: Optional[int] = None,
    ) -> int:
        """Send a message. Returns message ID."""
        msg = AgentMessage(
            id=self._next_id,
            sender=sender,
            recipient=recipient,
            msg_type=msg_type,
            payload=payload,
            timestamp=time.time(),
            reply_to=reply_to,
        )
        self._messages.append(msg)
        self._next_id += 1

        # Trigger handlers
        agent_handlers = self._handlers.get(recipient, {})
        for handler in agent_handlers.get(msg_type, []):
            try:
                handler(msg)
            except Exception:
                pass

        return msg.id

    def receive(
        self,
        recipient: str,
        *,
        msg_type: Optional[MessageType] = None,
        unread_only: bool = True,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """Receive messages for an agent.

        Args:
            recipient: Agent ID
            msg_type: Filter by type
            unread_only: Only return unread messages
            limit: Max messages
        """
        results = []
        for msg in self._messages:
            if msg.recipient != recipient:
                continue
            if unread_only and msg.read:
                continue
            if msg_type and msg.msg_type != msg_type:
                continue
            results.append(msg)
            if len(results) >= limit:
                break
        return results

    def mark_read(self, message_ids: list[int]) -> int:
        """Mark messages as read. Returns count marked."""
        count = 0
        id_set = set(message_ids)
        for msg in self._messages:
            if msg.id in id_set and not msg.read:
                msg.read = True
                count += 1
        return count

    def reply(
        self,
        original_id: int,
        sender: str,
        payload: dict,
    ) -> Optional[int]:
        """Reply to a message."""
        original = next((m for m in self._messages if m.id == original_id), None)
        if not original:
            return None

        return self.send(
            sender=sender,
            recipient=original.sender,
            msg_type=MessageType.RESPONSE,
            payload=payload,
            reply_to=original_id,
        )

    def on_message(self, agent_id: str, msg_type: MessageType, handler: Callable) -> None:
        """Register a message handler for an agent."""
        self._handlers.setdefault(agent_id, {})
        self._handlers[agent_id].setdefault(msg_type, [])
        self._handlers[agent_id][msg_type].append(handler)

    def get_thread(self, message_id: int) -> list[AgentMessage]:
        """Get all messages in a thread (replies chain)."""
        thread = []
        # Find root
        root = next((m for m in self._messages if m.id == message_id), None)
        if not root:
            return []

        thread.append(root)
        # Find all replies
        for msg in self._messages:
            if msg.reply_to == message_id:
                thread.append(msg)

        thread.sort(key=lambda m: m.timestamp)
        return thread

    def stats(self) -> dict:
        """Message bus statistics."""
        from collections import Counter
        types = Counter(m.msg_type.value for m in self._messages)
        agents = set()
        for m in self._messages:
            agents.add(m.sender)
            agents.add(m.recipient)

        unread = sum(1 for m in self._messages if not m.read)
        return {
            "total_messages": len(self._messages),
            "unread": unread,
            "agents": sorted(agents),
            "by_type": dict(types),
        }
