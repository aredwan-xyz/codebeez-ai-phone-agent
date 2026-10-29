"""Admin REST API — call history, KB management, live session inspection."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models import CallerProfile, CallRecord, TurnRecord
from app.memory.session import get_redis
from app.security import require_admin
from app.tools.knowledge_base import ingest_document

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/calls")
async def list_calls(limit: int = 50, offset: int = 0):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CallRecord).order_by(CallRecord.started_at.desc()).limit(limit).offset(offset)
        )
        calls = result.scalars().all()
    return [
        {
            "call_sid": c.call_sid,
            "from": c.from_number,
            "to": c.to_number,
            "direction": c.direction,
            "status": c.status,
            "duration_s": c.duration_seconds,
            "started_at": c.started_at,
        }
        for c in calls
    ]


@router.get("/calls/{call_sid}/turns")
async def get_turns(call_sid: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TurnRecord)
            .where(TurnRecord.call_sid == call_sid)
            .order_by(TurnRecord.turn_index)
        )
        turns = result.scalars().all()
    if not turns:
        raise HTTPException(status_code=404, detail="No turns found")
    return [
        {
            "turn": t.turn_index,
            "caller": t.caller_transcript,
            "agent": t.agent_response,
            "tools": t.tools_used,
            "latency_ms": t.latency_ms,
        }
        for t in turns
    ]


@router.get("/callers")
async def list_callers():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CallerProfile).order_by(CallerProfile.last_called_at.desc())
        )
        profiles = result.scalars().all()
    return [
        {
            "phone": p.phone_number,
            "name": p.name,
            "call_count": p.call_count,
            "last_called": p.last_called_at,
        }
        for p in profiles
    ]


@router.get("/active-sessions")
async def active_sessions():
    r = get_redis()
    keys = await r.keys("call_session:*")
    sessions = []
    for key in keys:
        raw = await r.get(key)
        if raw:
            import json

            sessions.append(json.loads(raw))
    return sessions


@router.post("/knowledge-base/ingest")
async def ingest_kb(file: UploadFile):
    content = await file.read()
    await ingest_document(source=file.filename or "upload", content=content.decode("utf-8"))
    return {"status": "ingested", "source": file.filename}


@router.post("/knowledge-base/ingest-text")
async def ingest_kb_text(source: str, content: str):
    await ingest_document(source=source, content=content)
    return {"status": "ingested", "source": source}
