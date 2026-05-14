import os
import sys
import signal
import contextlib
import subprocess
import time

import numpy as np

from dotenv import load_dotenv
from pathlib import Path
from faster_whisper import WhisperModel

from ezra_brain import ask_ezra
from ezra_emotion import set_emotion


# =========================
# LOAD ENV
# =========================
load_dotenv(Path(__file__).parent / ".env")


# =========================
# CONFIG
# =========================
MIC_DEVICE = "plughw:3,0"
SPEAKER_DEVICE = "plughw:2,0"

CHUNK_DURATION = 0.3

START_THRESHOLD = 0.025
SILENCE_THRESHOLD = 0.01

SILENCE_LIMIT = 2
MIN_AUDIO_LENGTH = 1.0

GAIN = 6.0


# =========================
# STDERR SUPPRESSION
# =========================
@contextlib.contextmanager
def suppress_stderr_fully():
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr_fd = os.dup(2)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        os.dup2(old_stderr_fd, 2)
        os.close(devnull)
        os.close(old_stderr_fd)


print("🚀 Starting Ezra...")

print("🧠 Loading Whisper model...")
with suppress_stderr_fully():
    model = WhisperModel(
        "base",
        device="cpu",
        compute_type="int8"
    )
print("✅ Model loaded")


# =========================
# CLEAN SHUTDOWN
# =========================
current_proc = None

def signal_handler(sig, frame):
    global current_proc
    print("\n🛑 Shutting down Ezra...")
    if current_proc:
        try:
            current_proc.terminate()
        except:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)


# =========================
# RECORD AUDIO (RAW - FIXED)
# =========================
def record_chunk():

    bytes_per_sample = 2  # S16_LE
    sample_rate = 16000
    num_samples = int(CHUNK_DURATION * sample_rate)
    expected_bytes = num_samples * bytes_per_sample

    proc = subprocess.Popen(
        [
            "arecord",
            "-D", MIC_DEVICE,
            "-f", "S16_LE",
            "-r", "16000",
            "-c", "1",
            "-t", "raw"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    # 🔥 Read exactly the amount we need
    raw_audio = proc.stdout.read(expected_bytes)

    proc.terminate()

    if not raw_audio:
        return None

    audio = np.frombuffer(raw_audio, dtype=np.int16)

    # Normalize
    audio = audio.astype(np.float32) / 32768.0

    # Remove DC offset
    audio = audio - np.mean(audio)

    # Apply gain
    audio = audio * GAIN
    audio = np.clip(audio, -1.0, 1.0)

    return audio

    proc = subprocess.Popen(
        [
            "arecord",
            "-D", MIC_DEVICE,
            "-f", "S16_LE",
            "-r", "16000",
            "-c", "1",
            "-d", str(CHUNK_DURATION),
            "-t", "raw"   # 🔥 KEY FIX: no WAV header
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )

    raw_audio, _ = proc.communicate()

    # Convert bytes → numpy
    audio = np.frombuffer(raw_audio, dtype=np.int16)

    if len(audio) == 0:
        return None

    # Normalize
    audio = audio.astype(np.float32) / 32768.0

    # Remove DC offset
    audio = audio - np.mean(audio)

    # Apply gain
    audio = audio * GAIN
    audio = np.clip(audio, -1.0, 1.0)

    return audio


# =========================
# LISTEN LOOP
# =========================
def listen():

    print("🔇 Calibrating noise floor...")

    noise_samples = []

    for _ in range(10):
        audio = record_chunk()
        if audio is None:
            continue
        rms = np.sqrt(np.mean(audio**2))
        rms = min(rms, 0.3)  # clamp crazy spikes
        print(f"Level: {rms:.3f}")
        noise_samples.append(rms)

    noise_floor = np.mean(noise_samples)

    START_THRESHOLD = noise_floor + 0.025
    SILENCE_THRESHOLD = noise_floor + 0.005

    print(f"Noise floor: {noise_floor:.3f}")
    print(f"Start threshold: {START_THRESHOLD:.3f}")
    print(f"Silence threshold: {SILENCE_THRESHOLD:.3f}")

    print("🎤 Listening...")

    recording = []
    speaking = False

    silence_counter = 0
    speech_chunks = 0

    while True:

        audio = record_chunk()

        if audio is None:
            continue
        print(f"Samples: {len(audio)}")
        
        rms = np.sqrt(np.mean(audio**2))
        print(f"Level: {rms:.3f}")

        # Start speaking
        if not speaking:
            if rms > START_THRESHOLD:
                speech_chunks += 1
            else:
                speech_chunks = 0

            if speech_chunks >= 2:
                speaking = True
                print("🟢 Speech detected")
                recording.extend(audio)

            speaking = True
            print("🟢 Speech detected")
            recording.extend(audio)

        if speaking:
            speech_chunks = 0
            recording.extend(audio)
            speech_chunks += 1

            if rms < (noise_floor + 0.008):
                silence_counter += 1
            else:
                silence_counter = 0

            if speech_chunks > 2:
                if silence_counter >= SILENCE_LIMIT or rms < (noise_floor + 0.005):
                    print("🔴 End of speech")
                    break

    # Ignore short clips
    if len(recording) < 16000 * MIN_AUDIO_LENGTH:
        print("⚠️ Too short, ignoring")
        return None

    return np.array(recording)


# =========================
# TRANSCRIBE
# =========================
def transcribe(audio):

    print("🧠 Transcribing...")

    # 🔥 Normalize audio (boost quiet speech)
    audio = audio / max(0.01, np.max(np.abs(audio)))

    import scipy.io.wavfile as wav
    wav.write("temp.wav", 16000, audio)

    with suppress_stderr_fully():
        segments, _ = model.transcribe(
            "temp.wav",
            language="en",
            beam_size=5,
            vad_filter=True
        )

    text = " ".join([seg.text for seg in segments]).strip()

    print(f"You said: {text}")

    return text


# =========================
# SPEAK
# =========================
def speak(text):

    print(f"Ezra: {text}")

    cmd = (
        f'echo "{text}" | '
        f'~/projects/piper_tts/piper '
        f'--model ~/projects/piper_tts/en_US-lessac-medium.onnx '
        f'--output_file temp.wav '
        f'> /dev/null 2>&1'
    )

    os.system(cmd)

    # Talking animation ON
    set_emotion("normal_talking")
    time.sleep(0.05)

    # Play audio
    os.system(
        f"aplay -D {SPEAKER_DEVICE} temp.wav > /dev/null 2>&1"
    )

    # Back to listening
    set_emotion("listening")


# =========================
# MAIN LOOP
# =========================
def main():

    print("🤖 Ezra ready! (Ctrl+C to exit)\n")

    while True:

        set_emotion("listening")

        audio = listen()

        if audio is None:
            continue

        text = transcribe(audio)

        if not text:
            continue

        if "quit" in text.lower():
            speak("Goodbye!")
            break

        result = ask_ezra(text)
        response = result["response"]

        speak(response)


# =========================
# START
# =========================
if __name__ == "__main__":
    main()