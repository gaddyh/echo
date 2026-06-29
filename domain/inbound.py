from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class InboundMessage:
    """Neutral inbound DTO produced by the infra layer and consumed by the agent."""
    user_id: str
    sender_name: str
    text: str  # carries "stt:" or "text:" prefix — parsed agent-side


@dataclass
class UserContext:
    """Snapshot of the user data the agent needs to build its prompt and resolve contacts."""
    user_id: str
    name: str
    timezone: str
    recent_chats: Dict[str, str] = field(default_factory=dict)
    name2chat_id: Dict[str, List[str]] = field(default_factory=dict)
