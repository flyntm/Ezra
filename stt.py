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
    model = WhisperModel("base", device="cpu", compute_type="int8")
print("✅ Model loaded")

def transcribe(audio):
    print("🧠 Transcribing...")

    audio = audio / max(0.01, np.max(np.abs(audio)))

    wav.write("temp.wav", 16000, audio)

    with suppress_stderr():
        segments, _ = model.transcribe("temp.wav", language="en")

    text = " ".join([seg.text for seg in segments]).strip()
    print(f"You said: {text}")

    return text