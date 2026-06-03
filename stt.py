import contextlib
import os
import shutil
import time

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
    model = WhisperModel("base.en", device="cpu", compute_type="int8")

print("✅ Model loaded")


def transcribe(audio):

    start = time.time()

    try:

        print("🧠 Transcribing...")

        # Save EXACTLY what audio.py captured
        wav.write("temp.wav", 16000, audio)

        shutil.copy("temp.wav", "/tmp/whisper_input.wav")
        print("💾 Saved Whisper input to /tmp/whisper_input.wav")

        # Same settings that worked in benchmark_whisper.py
        with suppress_stderr():
            segments, info = model.transcribe("temp.wav", beam_size=5)

        text = "".join(segment.text for segment in segments).strip()

        elapsed = time.time() - start

        print(f"⏱️ STT took {elapsed:.2f} sec")

        if not text:
            print("⚠️ No speech recognized")
            return ""

        print(f"You said: {text}")

        return text

    except Exception as e:

        print("❌ STT ERROR:", e)
        return ""
