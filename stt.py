import contextlib
import os
from faster_whisper import WhisperModel
import scipy.io.wavfile as wav
import numpy as np


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


print("🧠 Loading Whisper model...")
with suppress_stderr():
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
print("✅ Model loaded")


def transcribe(audio):
    print("🧠 STT CALLED")
    print("🧠 Transcribing...")

    # =========================
    # NORMALIZE
    # =========================
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val

    # =========================
    # GAIN BOOST (important)
    # =========================
    audio = np.clip(audio * 3.0, -1.0, 1.0)

    # =========================
    # 🔥 TRIM AUDIO (CRITICAL FIX)
    # =========================
    max_samples = 16000 * 3  # 3 seconds max
    audio = audio[-max_samples:]

    # =========================
    # WRITE TEMP FILE
    # =========================
    wav.write("temp.wav", 16000, audio)

    # =========================
    # TRANSCRIBE (FAST + SAFE)
    # =========================
    with suppress_stderr():
        segments, _ = model.transcribe(
            "temp.wav", language="en", beam_size=1, best_of=1
        )

    # =========================
    # BUILD TEXT
    # =========================
    text = " ".join([seg.text for seg in segments]).strip()

    if not text:
        print("⚠️ No speech recognized")
        return ""

    print(f"You said: {text}")
    return text
