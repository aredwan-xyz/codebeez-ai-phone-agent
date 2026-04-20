"""Voice Activity Detection.

Primary:  Deepgram's built-in endpointing fires `speech_final=True` —
          that signal drives end-of-turn detection without a local VAD.
Fallback: energy-based VAD for barge-in detection while the agent is speaking.
"""

import asyncio
import time
from collections import deque
from typing import Callable

from app.config import get_settings
from app.core.audio import compute_energy, mulaw_to_pcm16

settings = get_settings()

ENERGY_SPEECH_THRESHOLD = 0.008   # empirically tuned for telephone audio
LOOKBACK_FRAMES = 3                # frames to average


class BargeInDetector:
    """
    Detects caller speech while the agent is speaking so we can interrupt TTS.
    Works on raw μ-law frames from Twilio.
    """

    def __init__(self, on_barge_in: Callable[[], None], silence_ms: int | None = None):
        self._on_barge_in = on_barge_in
        self._silence_ms = silence_ms or settings.vad_silence_threshold_ms
        self._energy_window: deque[float] = deque(maxlen=LOOKBACK_FRAMES)
        self._speech_start: float | None = None
        self._active = False

    def feed(self, mulaw_frame: bytes) -> bool:
        """Feed a μ-law frame. Returns True if barge-in detected this frame."""
        pcm = mulaw_to_pcm16(mulaw_frame)
        energy = compute_energy(pcm)
        self._energy_window.append(energy)

        avg_energy = sum(self._energy_window) / len(self._energy_window)
        is_speech = avg_energy > ENERGY_SPEECH_THRESHOLD

        if is_speech and not self._active:
            self._active = True
            self._speech_start = time.monotonic()
            self._on_barge_in()
            return True

        if not is_speech:
            self._active = False
            self._speech_start = None

        return False

    def reset(self):
        self._energy_window.clear()
        self._speech_start = None
        self._active = False


class EndOfTurnDetector:
    """
    Tracks end-of-turn state driven by Deepgram `speech_final` events.
    Falls back to a silence timer when Deepgram endpointing is unavailable.
    """

    def __init__(self, on_end_of_turn: Callable[[str], None]):
        self._on_end_of_turn = on_end_of_turn
        self._transcript_buffer: list[str] = []
        self._timer_task: asyncio.Task | None = None

    def on_interim(self, transcript: str):
        """Call with Deepgram interim (is_final=False) transcripts."""
        self._transcript_buffer.append(transcript)
        self._restart_silence_timer()

    def on_final(self, transcript: str, speech_final: bool):
        """Call with Deepgram final (is_final=True) transcripts."""
        if transcript:
            self._transcript_buffer.append(transcript)
        if speech_final:
            self._fire()

    def _restart_silence_timer(self):
        if self._timer_task:
            self._timer_task.cancel()
        self._timer_task = asyncio.create_task(self._silence_timeout())

    async def _silence_timeout(self):
        await asyncio.sleep(settings.vad_silence_threshold_ms / 1000)
        self._fire()

    def _fire(self):
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        full_transcript = " ".join(self._transcript_buffer).strip()
        self._transcript_buffer.clear()
        if full_transcript:
            self._on_end_of_turn(full_transcript)

    def reset(self):
        if self._timer_task:
            self._timer_task.cancel()
        self._transcript_buffer.clear()
