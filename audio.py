import subprocess
import numpy as np
from config import *

# =========================
# GLOBAL STATE
# =========================
noise_floor_cached = None
current_proc = None


# =========================
# RECORD AUDIO
# =========================
def record_chunk():
    global current_proc

    bytes_per_sample = 2
    sample_rate = 16000
    num_samples = int(CHUNK_DURATION * sample_rate)
    expected_bytes = num_samples * bytes_per_sample

    current_proc = subprocess.Popen(
        [
            "arecord",
            "-D",
            MIC_DEVICE,
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
            "-t",
            "raw",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    try:
        raw_audio = current_proc.stdout.read(expected_bytes)
    finally:
        current_proc.terminate()
        current_proc = None

    if not raw_audio:
        return None

    audio = np.frombuffer(raw_audio, dtype=np.int16)
    audio = audio.astype(np.float32) / 32768.0

    # Remove DC offset
    audio = audio - np.mean(audio)

    # Apply gain
    audio = audio * GAIN
    audio = np.clip(audio, -1.0, 1.0)

    return audio


# =========================
# LISTEN FOR SPEECH
# =========================
def listen():
    global noise_floor_cached

    # === CALIBRATION ===
    if noise_floor_cached is None:
        print("🔇 Calibrating noise floor...")

        noise_samples = []

        for _ in range(10):
            audio = record_chunk()
            if audio is None:
                continue

            rms = np.sqrt(np.mean(audio**2))
            rms = min(rms, 0.3)
            print(f"Level: {rms:.3f}")
            noise_samples.append(rms)

        noise_floor = np.mean(noise_samples)
        noise_floor_cached = noise_floor

        # 👇 DEFINE FIRST
        start_threshold = noise_floor + 0.025
        silence_threshold = noise_floor + 0.012

        # 👇 THEN PRINT
        print(f"Noise floor: {noise_floor:.3f}")
        print(f"Start threshold: {start_threshold:.3f}")
        print(f"Silence threshold: {silence_threshold:.3f}")
    else:
        noise_floor = noise_floor_cached

    start_threshold = noise_floor + 0.025
    silence_threshold = noise_floor + 0.012

    # === INIT ===
    recording = []
    pre_buffer = []
    PRE_BUFFER_SIZE = 3

    speaking = False
    silence_counter = 0
    speech_chunks = 0
    start_counter = 0

    print("🎤 Listening...")

    # === MAIN LOOP ===
    while True:
        audio = record_chunk()

        # Save pre-buffer
        if audio is not None and len(audio) > 0:
            pre_buffer.append(audio)
        if len(pre_buffer) > PRE_BUFFER_SIZE:
            pre_buffer.pop(0)

        if audio is None:
            continue

        rms = np.sqrt(np.mean(audio**2))
        rms = min(rms, 0.3)

        print(f"Level: {rms:.3f}")

        # === START DETECTION ===
        if not speaking:
            if rms > start_threshold:
                start_counter += 1
            else:
                start_counter = 0

            if start_counter >= 2:
                speaking = True
                print("🟢 Speech detected")

                # Add buffered audio (capture first syllable)
                valid = [a for a in pre_buffer if a is not None and len(a) > 0]
                if valid:
                    recording.extend(np.concatenate(valid))

                recording.extend(audio)

                silence_counter = 0
                speech_chunks = 0
                start_counter = 0

        # === SPEAKING MODE ===
        else:
            recording.extend(audio)
            speech_chunks += 1

            if rms < silence_threshold:
                silence_counter += 1
            else:
                silence_counter = max(0, silence_counter - 1)

            if silence_counter >= SILENCE_LIMIT and speech_chunks > 4:
                print("🔴 End of speech")
                break

    # === FINAL CHECK ===
    if len(recording) < 16000 * MIN_AUDIO_LENGTH:
        print("⚠️ Too short, ignoring")
        return None

    return np.array(recording)
