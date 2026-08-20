import sounddevice as sd
import soundfile as sf
import numpy as np
import time
from collections import deque

SAMPLE_RATE = 48000
CHANNELS = 1

THRESHOLD = 0.005  # speech threshold
SILENCE_TIME = 0.8  # stop after 0.8 sec silence
MAX_TIME = 10  # safety limit

print("Opening microphone...")


print("🎤 Start speaking...")
print(sd.query_devices(0))
print("Recording will stop after you pause.")

chunks = []

with sd.InputStream(
    samplerate=SAMPLE_RATE,
    channels=CHANNELS,
    dtype="float32",
) as stream:

    print("Ready")

    heard_speech = False
    last_speech_time = time.time()
    start_time = time.time()
    prebuffer = deque(maxlen=200)

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

audio = np.concatenate(chunks, axis=0)

sf.write(
    "silence_test.wav",
    audio,
    SAMPLE_RATE,
)

print()
print(f"Recorded chunks: {len(chunks)}")
print("Saved silence_test.wav")
print(f"Duration: {len(audio)/SAMPLE_RATE:.2f} sec")
print("Done.")
