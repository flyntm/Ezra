import contextlib
import os
import numpy as np
from faster_whisper import WhisperModel
from config import *


# =========================
# SUPPRESS STDERR
# =========================
@contextlib.contextmanager
def suppress_stderr():
    devnull = os.open(os.devnull, os.O_WRONLY)
    old = os.dup(2)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(old, 2)
        os.close(devnull)
        os.close(old)


# =========================
# LOAD MODEL
# =========================
print("🧠 Loading Whisper model...")
with suppress_stderr():
    model = WhisperModel(
        WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE
    )
print("✅ Model loaded")


# =========================
# TRANSCRIBE
# =========================
def transcribe(audio):
    print("🧠 Transcribing...")

    # Normalize audio
    audio = audio / (np.max(np.abs(audio)) + 1e-6)
    audio = np.clip(audio, -1.0, 1.0)

    # Reject very low energy audio
    rms = np.sqrt(np.mean(audio**2))
    if rms < 0.02:
        print("🔇 Ignoring low-energy audio")
        return ""

    # 🔥 ADD THIS (padding at the beginning)
    pad = np.zeros(int(0.2 * SAMPLE_RATE))
    audio = np.concatenate([pad, audio])

    with suppress_stderr():
        segments, _ = model.transcribe(
            audio,
            language=WHISPER_LANGUAGE,
            beam_size=WHISPER_BEAM_SIZE,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt="Ezra",
        )

    text = " ".join([seg.text for seg in segments]).strip()

    # 🔥 FILTER OUT GARBAGE / HALLUCINATIONS
    if not text:
        return ""

    # Reject obvious hallucination pattern
    if len(text.split()) > 8:
        print("⚠️ Ignoring long/invalid transcription")
        return ""

    # Reject repeated nonsense
    if text.lower().count("ezra") > 3:
        print("⚠️ Ignoring hallucinated repetition")
        return ""

    print(f"You said: {text}")

    return text
