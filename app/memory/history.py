"""
Persistent caller history — cross-call memory stored in PostgreSQL.
"""

from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select, update

from app.db.base import AsyncSessionLocal
from app.db.models import CallerProfile, CallRecord, TurnRecord
from app.models.call import CallSession
from app.models.conversation import ConversationTurn, Message

log = structlog.get_logger()


class CallerHistoryService:
    async def get_caller_profile(self, phone_number: str) -> Optional[CallerProfile]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CallerProfile).where(CallerProfile.phone_number == phone_number)
            )
            return result.scalar_one_or_none()

    async def get_or_create_profile(self, phone_number: str) -> CallerProfile:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(CallerProfile).where(CallerProfile.phone_number == phone_number)
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = CallerProfile(phone_number=phone_number)
                db.add(profile)
                await db.commit()
                await db.refresh(profile)
            return profile

    async def save_call(self, session: CallSession, messages: list[Message]):
        """Persist final call record and update caller profile."""
        async with AsyncSessionLocal() as db:
            # Upsert CallRecord
            result = await db.execute(
                select(CallRecord).where(CallRecord.call_sid == session.call_sid)
            )
            record = result.scalar_one_or_none()
            if record is None:
                record = CallRecord(
                    call_sid=session.call_sid,
                    from_number=session.from_number,
                    to_number=session.to_number,
                    direction=session.direction.value,
                    status=session.status.value,
                    caller_name=session.caller_name,
                    caller_id=session.caller_id,
                    started_at=session.started_at,
                )
                db.add(record)

            record.ended_at = session.ended_at or datetime.utcnow()
            if session.started_at and record.ended_at:
                record.duration_seconds = int(
                    (record.ended_at - session.started_at).total_seconds()
                )
            record.status = session.status.value

            # Update caller profile
            profile_result = await db.execute(
                select(CallerProfile).where(CallerProfile.phone_number == session.from_number)
            )
            profile = profile_result.scalar_one_or_none()
            if profile is None:
                profile = CallerProfile(phone_number=session.from_number)
                db.add(profile)

            profile.call_count = (profile.call_count or 0) + 1
            profile.last_called_at = datetime.utcnow()
            if session.caller_name and not profile.name:
                profile.name = session.caller_name
            if session.caller_id and not profile.crm_contact_id:
                profile.crm_contact_id = session.caller_id

            await db.commit()

    async def save_turn(self, turn: ConversationTurn):
        async with AsyncSessionLocal() as db:
            record = TurnRecord(
                call_sid=turn.call_sid,
                turn_index=turn.turn_index,
                caller_transcript=turn.caller_transcript,
                agent_response=turn.agent_response,
                tools_used=turn.tools_used,
                latency_ms=turn.latency_ms,
                timestamp=turn.timestamp,
            )
            db.add(record)
            await db.commit()

    async def get_recent_turns(self, call_sid: str, limit: int = 20) -> list[TurnRecord]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(TurnRecord)
                .where(TurnRecord.call_sid == call_sid)
                .order_by(TurnRecord.turn_index.desc())
                .limit(limit)
            )
            return list(reversed(result.scalars().all()))
