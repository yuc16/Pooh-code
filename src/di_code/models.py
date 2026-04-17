from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ChatMessage:
    role: str
    content: Any


@dataclass
class InboundMessage:
    text: str
    sender_id: str
    channel: str
    account_id: str
    peer_id: str
    chat_id: str | None = None
    is_group: bool = False
    reply_target_id: str | None = None
    reply_target_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentReply:
    text: str
    session_key: str
    session_id: str
    model: str
    compacted: bool = False


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: str


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
