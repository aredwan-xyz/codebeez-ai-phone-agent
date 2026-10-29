"""Audio codec utilities: μ-law ↔ PCM, resampling, chunking.

Twilio Media Streams: μ-law 8 kHz mono, 20 ms frames (160 bytes).
Deepgram input:       μ-law 8 kHz mono (passthrough, no conversion needed).
ElevenLabs output:    PCM 16-bit 22050/44100 Hz → resample → μ-law 8 kHz.
"""

import audioop
import base64
from collections.abc import Generator

import numpy as np

TWILIO_SAMPLE_RATE = 8000
TWILIO_FRAME_MS = 20
TWILIO_FRAME_BYTES = 160  # 8000 * 0.02


def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Convert μ-law encoded bytes to signed 16-bit PCM."""
    return audioop.ulaw2lin(mulaw_bytes, 2)


def pcm16_to_mulaw(pcm_bytes: bytes) -> bytes:
    """Convert signed 16-bit PCM bytes to μ-law."""
    return audioop.lin2ulaw(pcm_bytes, 2)


def resample_pcm16(pcm_bytes: bytes, src_rate: int, dst_rate: int = TWILIO_SAMPLE_RATE) -> bytes:
    """Resample signed 16-bit PCM from src_rate to dst_rate."""
    if src_rate == dst_rate:
        return pcm_bytes
    resampled, _ = audioop.ratecv(pcm_bytes, 2, 1, src_rate, dst_rate, None)
    return resampled


def pcm_to_numpy(pcm_bytes: bytes) -> np.ndarray:
    return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def numpy_to_pcm(audio: np.ndarray) -> bytes:
    return (audio * 32768.0).clip(-32768, 32767).astype(np.int16).tobytes()


def pcm_for_twilio(pcm_bytes: bytes, src_rate: int) -> bytes:
    """Full pipeline: arbitrary PCM → μ-law 8 kHz ready for Twilio."""
    resampled = resample_pcm16(pcm_bytes, src_rate)
    return pcm16_to_mulaw(resampled)


def chunk_audio(audio: bytes, chunk_size: int = TWILIO_FRAME_BYTES) -> Generator[bytes, None, None]:
    """Yield fixed-size chunks from a byte stream."""
    for i in range(0, len(audio), chunk_size):
        yield audio[i : i + chunk_size]


def b64_decode_mulaw(payload: str) -> bytes:
    return base64.b64decode(payload)


def b64_encode_mulaw(mulaw_bytes: bytes) -> str:
    return base64.b64encode(mulaw_bytes).decode()


def compute_energy(pcm_bytes: bytes) -> float:
    """RMS energy of a PCM16 buffer, range 0–1."""
    if not pcm_bytes:
        return 0.0
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(arr**2))) / 32768.0
