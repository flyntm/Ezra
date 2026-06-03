from wake_word import wait_for_wake_word
import sounddevice as sd
import soundfile as sf
import numpy as np
import time
from collections import deque

SAMPLE_RATE = 48000
CHANNELS = 1

THRESHOLD = 0.015
SILENCE_TIME = 0.8
MAX_TIME = 10


def listen_until_silence():
    print("🎤 Listening for command...")

    chunks = []
    prebuffer = deque(maxlen=400)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
    ) as stream:

        print("Ready")

        heard_speech = False
        last_speech_time = time.time()
        start_time = time.time()

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

            if heard_speech and time.time() - last_speech_time > SILENCE_TIME:
                print("Silence detected")
                break

            if time.time() - start_time > MAX_TIME:
                print("Maximum time reached")
                break

    if not chunks:
        print("No audio captured")
        return None

    audio = np.concatenate(chunks, axis=0)
    return audio


print("👂 Waiting for wake word...")

wake = wait_for_wake_word()
wake_time = time.time()
print(f"Wake detected: {wake}")

audio = listen_until_silence()

if audio is not None:
    sf.write("wake_test.wav", audio, SAMPLE_RATE)
    print("Saved wake_test.wav")
    print(f"Duration: {len(audio) / SAMPLE_RATE:.2f} sec")
    print("Play it with: aplay wake_test.wav")
