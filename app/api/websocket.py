"""
Twilio Media Streams WebSocket handler.

Protocol: https://www.twilio.com/docs/voice/twiml/stream

Event flow:
  connected → start → media* → (mark* | stop)

The handler creates a CallOrchestrator per call and feeds it audio frames.
"""

import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.audio import b64_decode_mulaw, b64_encode_mulaw
from app.core.orchestrator import CallOrchestrator
from app.memory.history import CallerHistoryService
from app.memory.session import SessionStore
from app.models.call import CallDirection, CallSession, CallStatus
from app.security import authenticate_twilio_websocket

log = structlog.get_logger()
router = APIRouter()


async def _send_media(ws: WebSocket, stream_sid: str, mulaw_bytes: bytes):
    await ws.send_text(
        json.dumps(
            {
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": b64_encode_mulaw(mulaw_bytes)},
            }
        )
    )


async def _clear_media(ws: WebSocket, stream_sid: str):
    await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))


@router.websocket("/call/{call_sid}")
async def call_websocket(websocket: WebSocket, call_sid: str):
    if not await authenticate_twilio_websocket(websocket):
        return
    await websocket.accept()
    log.info("ws.connected", call_sid=call_sid)

    session_store = SessionStore()
    history_service = CallerHistoryService()
    orchestrator: CallOrchestrator | None = None
    stream_sid = ""
    session_created = False

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "connected":
                log.info("ws.twilio_connected")

            elif event == "start":
                start = msg["start"]
                if start.get("callSid") != call_sid or session_created:
                    await websocket.close(code=1008)
                    break
                stream_sid = start["streamSid"]
                params = start.get("customParameters", {})
                direction = params.get("direction", "inbound")

                session = CallSession(
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                    from_number=start.get("from", "unknown"),
                    to_number=start.get("to", "unknown"),
                    direction=CallDirection(direction),
                    status=CallStatus.IN_PROGRESS,
                )
                await session_store.save_session(session)
                session_created = True

                async def send_audio(mulaw_bytes: bytes):
                    await _send_media(websocket, stream_sid, mulaw_bytes)

                async def clear_audio():
                    await _clear_media(websocket, stream_sid)

                orchestrator = CallOrchestrator(
                    session=session,
                    send_audio=send_audio,
                    clear_audio=clear_audio,
                    session_store=session_store,
                    history_service=history_service,
                )

                # Start STT first, wire transcript callback
                await orchestrator._stt.start(on_transcript=orchestrator.on_deepgram_transcript)
                await orchestrator.start()
                log.info("ws.call_started", call_sid=call_sid)

            elif event == "media":
                if orchestrator:
                    mulaw_frame = b64_decode_mulaw(msg["media"]["payload"])
                    await orchestrator.on_audio_frame(mulaw_frame)

            elif event == "mark":
                pass  # TTS playback position markers — ignored for now

            elif event == "stop":
                log.info("ws.twilio_stop", call_sid=call_sid)
                break

    except WebSocketDisconnect:
        log.info("ws.disconnected", call_sid=call_sid)
    except Exception:
        log.exception("ws.error", call_sid=call_sid)
    finally:
        if orchestrator:
            await orchestrator._stt.stop()
            await orchestrator.stop()
        if session_created:
            await session_store.delete_session(call_sid)
        log.info("ws.cleaned_up", call_sid=call_sid)
