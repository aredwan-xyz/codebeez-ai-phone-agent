"""
CallOrchestrator — the brain of each active call.

Lifecycle:
  1. Caller speaks → Deepgram fires transcripts.
  2. EndOfTurnDetector assembles the full utterance.
  3. Claude (streaming + tools) generates a response.
  4. ElevenLabs streams TTS audio back through Twilio.
  5. BargeInDetector can interrupt the TTS mid-stream.
"""

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable

import structlog

from app.config import get_settings
from app.core.vad import BargeInDetector, EndOfTurnDetector
from app.memory.history import CallerHistoryService
from app.memory.session import SessionStore
from app.models.call import CallSession
from app.models.conversation import ConversationTurn, Message, Role
from app.services.llm import LLMService
from app.services.stt import STTService
from app.services.tts import TTSService

log = structlog.get_logger()
settings = get_settings()


class CallOrchestrator:
    def __init__(
        self,
        session: CallSession,
        send_audio: "Callable[[bytes], Awaitable[None]]",
        clear_audio: "Callable[[], Awaitable[None]]",
        session_store: SessionStore,
        history_service: CallerHistoryService,
    ):
        self.session = session
        self._send_audio = send_audio
        self._clear_audio = clear_audio
        self._store = session_store
        self._history = history_service

        self._stt = STTService()
        self._tts = TTSService()
        self._llm = LLMService()

        self._messages: list[Message] = []
        self._turn_index = 0
        self._tts_task: asyncio.Task | None = None

        self._eot_detector = EndOfTurnDetector(on_end_of_turn=self._on_end_of_turn_sync)
        self._barge_in = BargeInDetector(on_barge_in=self._on_barge_in_sync)

        self._loop = asyncio.get_event_loop()
        self._turn_queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    async def start(self):
        await self._load_history()
        self._worker_task = asyncio.create_task(self._turn_worker())
        await self._greet_caller()
        log.info("orchestrator.started", call_sid=self.session.call_sid)

    async def stop(self):
        if self._tts_task:
            self._tts_task.cancel()
        if self._worker_task:
            self._worker_task.cancel()
        await self._history.save_call(self.session, self._messages)
        log.info("orchestrator.stopped", call_sid=self.session.call_sid, turns=self._turn_index)

    # ──────────────────────────────────────────────────────────────────────────
    # Audio / transcript ingestion (called by WebSocket handler)
    # ──────────────────────────────────────────────────────────────────────────

    async def on_audio_frame(self, mulaw_frame: bytes):
        """Feed a raw μ-law frame from Twilio into STT and barge-in detector."""
        await self._stt.feed(mulaw_frame)
        if self.session.agent_speaking:
            self._barge_in.feed(mulaw_frame)

    def on_deepgram_transcript(self, transcript: str, is_final: bool, speech_final: bool):
        """Called by STTService when a transcript arrives."""
        if is_final:
            self._eot_detector.on_final(transcript, speech_final)
        else:
            self._eot_detector.on_interim(transcript)

    # ──────────────────────────────────────────────────────────────────────────
    # VAD callbacks (sync wrappers — VAD runs in the event loop thread)
    # ──────────────────────────────────────────────────────────────────────────

    def _on_end_of_turn_sync(self, transcript: str):
        self._loop.call_soon_threadsafe(self._turn_queue.put_nowait, transcript)

    def _on_barge_in_sync(self):
        self._loop.call_soon_threadsafe(self._handle_barge_in)

    def _handle_barge_in(self):
        if self.session.agent_speaking and self._tts_task:
            log.info("barge_in", call_sid=self.session.call_sid)
            self.session.interrupted = True
            self._tts_task.cancel()
            asyncio.create_task(self._clear_audio())

    # ──────────────────────────────────────────────────────────────────────────
    # Turn worker
    # ──────────────────────────────────────────────────────────────────────────

    async def _turn_worker(self):
        """Drain the turn queue and process one turn at a time."""
        while True:
            transcript = await self._turn_queue.get()
            try:
                await self._process_turn(transcript)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("turn.error", call_sid=self.session.call_sid)

    async def _process_turn(self, caller_text: str):
        t0 = time.monotonic()
        log.info("turn.start", call_sid=self.session.call_sid, text=caller_text)

        self._messages.append(Message(role=Role.USER, content=caller_text))
        self._eot_detector.reset()
        self._barge_in.reset()

        # Stream LLM response + TTS concurrently
        response_text, tools_used = await self._stream_response()

        latency_ms = int((time.monotonic() - t0) * 1000)
        self._messages.append(Message(role=Role.ASSISTANT, content=response_text))

        turn = ConversationTurn(
            call_sid=self.session.call_sid,
            turn_index=self._turn_index,
            caller_transcript=caller_text,
            agent_response=response_text,
            tools_used=tools_used,
            latency_ms=latency_ms,
        )
        await self._history.save_turn(turn)
        await self._store.update_session(self.session)
        self._turn_index += 1

        log.info("turn.done", latency_ms=latency_ms, tools=tools_used)

    async def _stream_response(self) -> tuple[str, list[str]]:
        """Get streamed LLM response, pipe first tokens to TTS as fast as possible."""
        full_text = ""
        tools_used: list[str] = []
        sentence_buffer = ""

        self.session.agent_speaking = True
        self.session.interrupted = False

        async def _tts_stream(text_gen: AsyncGenerator[str, None]):
            nonlocal full_text, sentence_buffer
            async for chunk in text_gen:
                if self.session.interrupted:
                    break
                full_text += chunk
                sentence_buffer += chunk
                # Flush TTS on sentence boundaries for lowest latency
                if any(c in sentence_buffer for c in ".!?,;") and len(sentence_buffer) > 20:
                    await self._speak(sentence_buffer)
                    sentence_buffer = ""
            if sentence_buffer and not self.session.interrupted:
                await self._speak(sentence_buffer)

        text_gen, tools_used = await self._llm.stream(
            messages=self._messages,
            call_session=self.session,
        )
        self._tts_task = asyncio.create_task(_tts_stream(text_gen))
        try:
            await self._tts_task
        except asyncio.CancelledError:
            pass

        self.session.agent_speaking = False
        return full_text, tools_used

    async def _speak(self, text: str):
        """Convert text → μ-law audio and stream to caller."""
        if not text.strip():
            return
        try:
            async for audio_chunk in self._tts.stream(text):
                if self.session.interrupted:
                    return
                await self._send_audio(audio_chunk)
        except asyncio.CancelledError:
            pass

    async def _greet_caller(self):
        """Speak an opening greeting as soon as the call connects."""
        name = self.session.caller_name
        greeting = (
            f"Hello{', ' + name if name else ''}! "
            f"This is {settings.agent_name} from {settings.agent_company}. "
            "How can I help you today?"
        )
        self._messages.append(Message(role=Role.ASSISTANT, content=greeting))
        self.session.agent_speaking = True
        await self._speak(greeting)
        self.session.agent_speaking = False

    async def _load_history(self):
        """Inject recent call history + system prompt into message list."""
        profile = await self._history.get_caller_profile(self.session.from_number)
        history_text = ""
        if profile and profile.call_count > 0:
            history_text = f"\nThis caller has spoken to you {profile.call_count} time(s) before. "
            if profile.notes:
                history_text += f"Notes: {profile.notes}"

        system = _build_system_prompt(
            agent_name=settings.agent_name,
            company=settings.agent_company,
            caller_name=self.session.caller_name,
            history_context=history_text,
        )
        self._messages = [Message(role=Role.SYSTEM, content=system)]


def _build_system_prompt(
    agent_name: str,
    company: str,
    caller_name: str | None,
    history_context: str,
) -> str:
    caller_ref = caller_name or "the caller"
    return f"""You are {agent_name}, an expert AI phone agent for {company}.

PERSONA
- Warm, professional, concise. You are on a live phone call.
- Speak naturally — short sentences, no markdown, no lists.
- Never say "As an AI" or "I'm a language model."
- If you don't know something, say so honestly and offer to find out.

CALLER
- You are speaking with {caller_ref}.{history_context}

CAPABILITIES
You have access to tools: schedule_appointment, lookup_crm, search_knowledge_base,
transfer_to_human, end_call.

Use tools proactively when the caller's intent maps to one of them.
Always confirm details before booking or updating records.

RESPONSE FORMAT
- Keep responses under 3 sentences unless the caller explicitly asks for details.
- End each response with either a question or a clear next step.
- When transferring or ending the call, always say goodbye warmly first.

PHONE ETIQUETTE
- Acknowledge interruptions graciously ("Of course, go ahead.").
- If audio quality is poor, ask the caller to repeat: "I'm sorry, I didn't catch that."
- Maintain context across the entire conversation.
"""
