from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(StrEnum):
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
    ended_at: datetime | None = None
    duration_seconds: int | None = None

    # Interruption state
    agent_speaking: bool = False
    interrupted: bool = False

    # Caller identity (resolved from CRM)
    caller_name: str | None = None
    caller_id: str | None = None  # CRM contact ID


class OutboundCallRequest(BaseModel):
    to_number: str
    context: str | None = None  # optional instructions for this specific call
    caller_name: str | None = None
