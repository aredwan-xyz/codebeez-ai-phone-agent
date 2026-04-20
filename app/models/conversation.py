from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    role: Role
    content: str
    timestamp: datetime = datetime.utcnow()
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_result: Optional[Any] = None


class ConversationTurn(BaseModel):
    """A single caller-utterance → agent-response pair."""
    call_sid: str
    turn_index: int
    caller_transcript: str
    agent_response: str
    tools_used: list[str] = []
    latency_ms: int = 0
    timestamp: datetime = datetime.utcnow()
