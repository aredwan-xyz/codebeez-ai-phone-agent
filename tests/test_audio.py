import numpy as np

from app.core.audio import (
    b64_decode_mulaw,
    b64_encode_mulaw,
    chunk_audio,
    compute_energy,
    mulaw_to_pcm16,
    pcm16_to_mulaw,
    pcm_for_twilio,
    resample_pcm16,
)


def _sine_wave_pcm(freq=440, sample_rate=8000, duration=0.1) -> bytes:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    samples = (np.sin(2 * np.pi * freq * t) * 16000).astype(np.int16)
    return samples.tobytes()


def test_mulaw_roundtrip():
    pcm = _sine_wave_pcm()
    mulaw = pcm16_to_mulaw(pcm)
    restored = mulaw_to_pcm16(mulaw)
    assert len(restored) == len(pcm)


def test_resample():
    pcm_22k = _sine_wave_pcm(sample_rate=22050, duration=0.1)
    pcm_8k = resample_pcm16(pcm_22k, src_rate=22050, dst_rate=8000)
    # 22050 * 0.1 samples → 8000 * 0.1 samples
    assert abs(len(pcm_8k) // 2 - 800) < 5


def test_pcm_for_twilio():
    pcm = _sine_wave_pcm(sample_rate=22050)
    mulaw = pcm_for_twilio(pcm, src_rate=22050)
    assert isinstance(mulaw, bytes)
    assert len(mulaw) > 0


def test_energy():
    silence = b"\x00" * 320
    sine = _sine_wave_pcm()
    assert compute_energy(silence) < 0.001
    assert compute_energy(sine) > 0.001


def test_chunk_audio():
    audio = bytes(1000)
    chunks = list(chunk_audio(audio, chunk_size=160))
    assert len(chunks) == 7
    assert sum(len(c) for c in chunks) == 1000


def test_base64_roundtrip():
    mulaw = bytes(range(256))
    encoded = b64_encode_mulaw(mulaw)
    assert b64_decode_mulaw(encoded) == mulaw
