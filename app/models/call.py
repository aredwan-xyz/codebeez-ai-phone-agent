from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(str, Enum):
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"


class CallSession(BaseModel):
    call_sid: str
    stream_sid: str = ""
    from_number: str
    to_number: str
    direction: CallDirection
    status: CallStatus = CallStatus.RINGING
    started_at: datetime = datetime.utcnow()
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None

    # Interruption state
    agent_speaking: bool = False
    interrupted: bool = False

    # Caller identity (resolved from CRM)
    caller_name: Optional[str] = None
    caller_id: Optional[str] = None  # CRM contact ID


class OutboundCallRequest(BaseModel):
    to_number: str
    context: Optional[str] = None    # optional instructions for this specific call
    caller_name: Optional[str] = None
