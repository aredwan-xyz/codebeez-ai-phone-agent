import asyncio

import numpy as np
import pytest

from app.core.audio import pcm16_to_mulaw
from app.core.vad import BargeInDetector, EndOfTurnDetector


def _mulaw_frame(amplitude=0) -> bytes:
    pcm = (np.ones(160, dtype=np.int16) * amplitude).tobytes()
    return pcm16_to_mulaw(pcm)


def test_barge_in_detects_speech():
    fired = []
    detector = BargeInDetector(on_barge_in=lambda: fired.append(True))
    # Feed loud audio
    loud_frame = _mulaw_frame(amplitude=8000)
    for _ in range(5):
        detector.feed(loud_frame)
    assert len(fired) > 0


def test_barge_in_silent_no_trigger():
    fired = []
    detector = BargeInDetector(on_barge_in=lambda: fired.append(True))
    silent_frame = _mulaw_frame(amplitude=0)
    for _ in range(10):
        detector.feed(silent_frame)
    assert len(fired) == 0


@pytest.mark.asyncio
async def test_end_of_turn_speech_final():
    results = []
    detector = EndOfTurnDetector(on_end_of_turn=lambda t: results.append(t))
    detector.on_final("Hello there", speech_final=True)
    assert results == ["Hello there"]


@pytest.mark.asyncio
async def test_end_of_turn_silence_timer():
    results = []
    # Very short threshold for testing
    import app.core.vad as vad_module

    original = vad_module.settings.vad_silence_threshold_ms
    vad_module.settings.vad_silence_threshold_ms = 100

    detector = EndOfTurnDetector(on_end_of_turn=lambda t: results.append(t))
    detector.on_interim("Hello")
    await asyncio.sleep(0.2)
    assert results == ["Hello"]

    vad_module.settings.vad_silence_threshold_ms = original
