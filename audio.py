import sounddevice as sd
import numpy as np
import time
from collections import deque
from scipy.signal import resample_poly

SAMPLE_RATE = 48000

THRESHOLD = 0.015
SILENCE_TIME = 0.8
MAX_TIME = 10
COMMAND_TIMEOUT = 3


def listen(wake_audio=None):

    print("🎤 Listening for command...")

    chunks = []

    # ---------------------------------
    # Add wake audio if supplied
    # ---------------------------------

    if wake_audio is not None:

        print(f"Received {len(wake_audio)/16000:.2f} seconds " "of pre-wake audio")

        # Convert Wake audio from 16k -> 48k
        wake_audio_48k = resample_poly(
            wake_audio,
            up=3,
            down=1,
        )

        wake_rms = np.sqrt(np.mean(wake_audio_48k**2))

        print(f"Wake RMS: {wake_rms:.4f}")

        chunks.append(wake_audio_48k.reshape(-1, 1))

    # ---------------------------------
    # Prebuffer
    # ---------------------------------

    prebuffer = deque(maxlen=400)

    # ---------------------------------
    # Recording
    # ---------------------------------

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    ) as stream:

        print("Ready")

        heard_speech = wake_audio is not None
        last_speech_time = time.time()
        start_time = time.time()

        if heard_speech:
            print("🎤 Continuing from wake audio")

        while True:

            audio, overflowed = stream.read(1024)
            prebuffer.append(audio.copy())
            rms = np.sqrt(np.mean(audio**2))

            print(f"RMS: {rms:.4f}")

            if rms > THRESHOLD:
                if not heard_speech:
                    print("🎤 SPEECH STARTED")
                    chunks.extend(prebuffer)
                    heard_speech = True

                last_speech_time = time.time()

            if heard_speech:
                chunks.append(audio)

            # -------------------------
            # End after silence
            # -------------------------

            if heard_speech and time.time() - last_speech_time > SILENCE_TIME:
                print("Silence detected")
                break

            # -------------------------
            # No command
            # -------------------------

            if not heard_speech and time.time() - start_time > COMMAND_TIMEOUT:
                print("No command detected")
                return None

            # -------------------------
            # Safety timeout
            # -------------------------

            if time.time() - start_time > MAX_TIME:
                print("Maximum time reached")
                break

    if not chunks:
        print("No audio captured")
        return None

    audio = np.concatenate(chunks, axis=0)

    print(f"Recording length: " f"{len(audio)/SAMPLE_RATE:.2f} sec")

    return audio.astype(np.float32)
