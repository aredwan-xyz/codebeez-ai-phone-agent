"""
ElevenLabs streaming TTS service.

Converts text sentences → μ-law 8 kHz audio chunks for Twilio.
Uses the `eleven_turbo_v2_5` model for lowest latency.
"""

import asyncio
from typing import AsyncGenerator

import structlog
from elevenlabs import AsyncElevenLabs, VoiceSettings

from app.config import get_settings
from app.core.audio import pcm_for_twilio

log = structlog.get_logger()
settings = get_settings()

# ElevenLabs returns PCM at this sample rate when output_format=pcm_22050
ELEVENLABS_SAMPLE_RATE = 22050
PCM_CHUNK_SIZE = 4096  # bytes per read from the stream


class TTSService:
    def __init__(self):
        self._client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        self._voice_settings = VoiceSettings(
            stability=0.4,
            similarity_boost=0.8,
            style=0.0,
            use_speaker_boost=True,
        )

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """
        Yield μ-law 8 kHz audio chunks suitable for sending to Twilio.
        Starts yielding as soon as the first bytes arrive from ElevenLabs.
        """
        text = text.strip()
        if not text:
            return

        log.debug("tts.request", chars=len(text))

        try:
            audio_stream = await self._client.text_to_speech.convert_as_stream(
                voice_id=settings.elevenlabs_voice_id,
                text=text,
                model_id=settings.elevenlabs_model_id,
                voice_settings=self._voice_settings,
                output_format="pcm_22050",  # raw signed-16 PCM, no container
            )

            pcm_buffer = b""
            async for chunk in audio_stream:
                if not chunk:
                    continue
                pcm_buffer += chunk
                # Convert and yield in Twilio-sized chunks (160 bytes mulaw)
                while len(pcm_buffer) >= PCM_CHUNK_SIZE:
                    block = pcm_buffer[:PCM_CHUNK_SIZE]
                    pcm_buffer = pcm_buffer[PCM_CHUNK_SIZE:]
                    mulaw = pcm_for_twilio(block, ELEVENLABS_SAMPLE_RATE)
                    yield mulaw

            # Flush remaining
            if pcm_buffer:
                mulaw = pcm_for_twilio(pcm_buffer, ELEVENLABS_SAMPLE_RATE)
                yield mulaw

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("tts.error", text_preview=text[:50])
