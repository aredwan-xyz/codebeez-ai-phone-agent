"""
Twilio webhook endpoints.

/calls/inbound  — Twilio calls this when a call arrives; returns TwiML to open a Media Stream.
/calls/outbound — TwiML for outbound calls.
/calls/make     — REST endpoint to trigger an outbound call.
/calls/status   — Twilio status callback.
/calls/transfer-twiml — TwiML to bridge to a human agent.
"""

from fastapi import APIRouter, Form, Request, Response
from twilio.twiml.voice_response import Connect, Dial, VoiceResponse, Stream

from app.config import get_settings
from app.models.call import OutboundCallRequest
from app.services.telephony import make_outbound_call

router = APIRouter()
settings = get_settings()


def _media_stream_twiml(call_sid: str, direction: str = "inbound") -> str:
    resp = VoiceResponse()
    connect = Connect()
    stream = Stream(
        url=f"wss://{settings.base_url.removeprefix('https://').removeprefix('http://')}/ws/call/{call_sid}",
        track="inbound_track",
    )
    stream.parameter(name="direction", value=direction)
    connect.append(stream)
    resp.append(connect)
    return str(resp)


@router.post("/inbound")
async def inbound_call(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
):
    twiml = _media_stream_twiml(CallSid, direction="inbound")
    return Response(content=twiml, media_type="application/xml")


@router.post("/outbound")
async def outbound_call_twiml(
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
):
    twiml = _media_stream_twiml(CallSid, direction="outbound")
    return Response(content=twiml, media_type="application/xml")


@router.post("/make")
async def initiate_outbound_call(req: OutboundCallRequest):
    twiml_url = f"{settings.base_url}/calls/outbound"
    call_sid = make_outbound_call(req.to_number, twiml_url)
    return {"call_sid": call_sid, "to": req.to_number}


@router.post("/status")
async def call_status_callback(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
):
    from app.memory.session import SessionStore
    store = SessionStore()
    session = await store.get_session(CallSid)
    if session:
        from app.models.call import CallStatus as CS
        try:
            session.status = CS(CallStatus.lower().replace("-", "_"))
        except ValueError:
            pass
        await store.update_session(session)
    return Response(content="", status_code=204)


@router.get("/transfer-twiml")
async def transfer_twiml(target: str):
    resp = VoiceResponse()
    dial = Dial()
    dial.number(target)
    resp.append(dial)
    return Response(content=str(resp), media_type="application/xml")
