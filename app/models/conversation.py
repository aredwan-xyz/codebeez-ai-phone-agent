from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: Role
    content: str
    timestamp: datetime = datetime.utcnow()
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_result: Any | None = None


class ConversationTurn(BaseModel):
    """A single caller-utterance → agent-response pair."""

    call_sid: str
    turn_index: int
    caller_transcript: str
    agent_response: str
    tools_used: list[str] = []
    latency_ms: int = 0
    timestamp: datetime = datetime.utcnow()
