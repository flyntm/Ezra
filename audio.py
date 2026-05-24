import subprocess
import numpy as np
from collections import deque
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

    num_samples = int(CHUNK_DURATION * SAMPLE_RATE)
    expected_bytes = num_samples * BYTES_PER_SAMPLE

    current_proc = subprocess.Popen(
        [
            "arecord",
            "-D",
            MIC_DEVICE,
            "-f",
            AUDIO_FORMAT,
            "-r",
            str(SAMPLE_RATE),
            "-c",
            str(CHANNELS),
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
        current_proc.wait()
        current_proc = None

    if not raw_audio:
        return None

    audio = np.frombuffer(raw_audio, dtype=np.int16)
    audio = audio.astype(np.float32) / 32768.0

    # Remove DC offset
    audio = audio - np.mean(audio)

    # Apply gain
    audio = audio * GAIN

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

            rms_raw = np.sqrt(np.mean(audio**2))
            rms = 0.7 * rms_raw + 0.3 * getattr(listen, "last_rms", rms_raw)
            listen.last_rms = rms
            rms = min(rms, RMS_CLAMP)
            print(f"Level: {rms:.3f}")

            if rms < 0.10:  # ignore spikes
                noise_samples.append(rms)

        noise_floor = np.percentile(noise_samples, 30)
        noise_floor_cached = noise_floor

        print(f"Noise floor: {noise_floor:.3f}")
    else:
        noise_floor = noise_floor_cached

    # Thresholds
    start_threshold = noise_floor + START_THRESHOLD_OFFSET
    silence_threshold = noise_floor + SILENCE_THRESHOLD_OFFSET

    # =========================
    # RING BUFFER (KEY CHANGE)
    # =========================
    ring_seconds = 1.5
    ring_size = int(ring_seconds / CHUNK_DURATION)
    ring_buffer = deque(maxlen=ring_size)

    # === INIT ===
    recording = []

    speaking = False
    silence_counter = 0
    speech_chunks = 0
    start_counter = 0

    print("🎤 Listening...")

    # === MAIN LOOP ===
    while True:
        audio = record_chunk()
        if audio is None:
            continue

        # Always store audio
        ring_buffer.append(audio)

        rms = np.sqrt(np.mean(audio**2))
        rms = min(rms, RMS_CLAMP)

        print(f"Level: {rms:.3f}")

        # === START DETECTION ===
        if not speaking:
            if rms > start_threshold:
                start_counter += 1
            else:
                start_counter = 0

            if start_counter >= START_CHUNKS_REQUIRED:
                speaking = True
                print("🟢 Speech detected")

                # 🔥 prepend buffered audio
                if len(ring_buffer) > 0:
                    buffered = np.concatenate(list(ring_buffer))
                    recording.extend(buffered)

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
                silence_counter = max(0, silence_counter - SILENCE_DECAY)

            if silence_counter >= SILENCE_LIMIT and speech_chunks > 4:
                print("🔴 End of speech")
                break

    # === FINAL CHECK ===
    if len(recording) < SAMPLE_RATE * MIN_AUDIO_LENGTH:
        print("⚠️ Too short, ignoring")
        return None

    return np.array(recording)
