"""
Deepgram streaming STT service.

Sends μ-law 8 kHz audio frames directly to Deepgram's WebSocket API.
Fires transcripts back via a registered callback.
"""

import asyncio
from typing import Callable

import structlog
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveOptions,
    LiveTranscriptionEvents,
)

from app.config import get_settings

log = structlog.get_logger()
settings = get_settings()


class STTService:
    def __init__(self):
        self._client = DeepgramClient(
            settings.deepgram_api_key,
            DeepgramClientOptions(options={"keepalive": "true"}),
        )
        self._connection = None
        self._on_transcript: Callable[[str, bool, bool], None] | None = None
        self._ready = asyncio.Event()

    async def start(self, on_transcript: Callable[[str, bool, bool], None]):
        """Open a Deepgram WebSocket and begin streaming."""
        self._on_transcript = on_transcript

        self._connection = self._client.listen.asyncwebsocket.v("1")

        self._connection.on(LiveTranscriptionEvents.Open, self._on_open)
        self._connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript_event)
        self._connection.on(LiveTranscriptionEvents.Error, self._on_error)
        self._connection.on(LiveTranscriptionEvents.Close, self._on_close)

        options = LiveOptions(
            model=settings.deepgram_model,
            language=settings.deepgram_language,
            encoding="mulaw",
            sample_rate=8000,
            channels=1,
            punctuate=True,
            smart_format=True,
            interim_results=True,
            endpointing=300,         # ms of silence → speech_final=True
            utterance_end_ms=1000,
        )

        started = await self._connection.start(options)
        if not started:
            raise RuntimeError("Failed to open Deepgram WebSocket")

        await self._ready.wait()
        log.info("stt.started", model=settings.deepgram_model)

    async def feed(self, mulaw_frame: bytes):
        if self._connection and self._ready.is_set():
            await self._connection.send(mulaw_frame)

    async def stop(self):
        if self._connection:
            await self._connection.finish()
            log.info("stt.stopped")

    # ──────────────────────────────────────────────────────────────────────────
    # Deepgram event handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _on_open(self, *args, **kwargs):
        self._ready.set()

    async def _on_transcript_event(self, *args, result=None, **kwargs):
        if not result or not self._on_transcript:
            return
        alt = result.channel.alternatives[0]
        transcript = alt.transcript
        is_final = result.is_final
        speech_final = result.speech_final

        if transcript:
            log.debug("stt.transcript", text=transcript, final=is_final, speech_final=speech_final)
            self._on_transcript(transcript, is_final, speech_final)

    async def _on_error(self, *args, error=None, **kwargs):
        log.error("stt.error", error=str(error))

    async def _on_close(self, *args, **kwargs):
        self._ready.clear()
        log.info("stt.closed")
