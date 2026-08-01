"""Build audio loudness envelopes for Ezra's LED mouth animation."""

import wave

import numpy as np

from config import (
    TTS_MOUTH_LEVEL_GAMMA,
    TTS_MOUTH_NOISE_GATE_RMS,
    TTS_MOUTH_REFERENCE_PERCENTILE,
    TTS_MOUTH_SYNC_WINDOW_SECONDS,
)


def build_mouth_envelope(path):
    """Return normalized RMS levels and seconds per level for a PCM WAV."""
    with wave.open(path, "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    dtype_by_width = {
        1: np.dtype("u1"),
        2: np.dtype("<i2"),
        4: np.dtype("<i4"),
    }
    if sample_width not in dtype_by_width:
        raise ValueError(f"Unsupported TTS WAV sample width: {sample_width}")

    audio = np.frombuffer(frames, dtype=dtype_by_width[sample_width]).astype(np.float32)
    if sample_width == 1:
        audio = (audio - 128.0) / 128.0
    else:
        audio /= float(1 << ((sample_width * 8) - 1))

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    window_samples = max(1, round(sample_rate * TTS_MOUTH_SYNC_WINDOW_SECONDS))
    rms_levels = []
    for start in range(0, audio.size, window_samples):
        window = audio[start : start + window_samples]
        rms_levels.append(float(np.sqrt(np.mean(window**2))) if window.size else 0.0)

    rms = np.asarray(rms_levels, dtype=np.float32)
    if rms.size == 0:
        return np.zeros(1, dtype=np.float32), TTS_MOUTH_SYNC_WINDOW_SECONDS

    voiced = rms[rms >= TTS_MOUTH_NOISE_GATE_RMS]
    reference = (
        float(np.percentile(voiced, TTS_MOUTH_REFERENCE_PERCENTILE))
        if voiced.size
        else TTS_MOUTH_NOISE_GATE_RMS
    )
    span = max(1e-6, reference - TTS_MOUTH_NOISE_GATE_RMS)
    normalized = np.clip((rms - TTS_MOUTH_NOISE_GATE_RMS) / span, 0.0, 1.0)
    normalized = np.power(normalized, TTS_MOUTH_LEVEL_GAMMA).astype(np.float32)
    return normalized, window_samples / sample_rate
