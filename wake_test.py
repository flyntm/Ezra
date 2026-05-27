import numpy as np
import sounddevice as sd
import time
from openwakeword.model import Model
from collections import deque

# =========================
# CONFIG
# =========================
SAMPLE_RATE = 16000
BLOCK_SIZE = 1024

THRESHOLD = 0.6

# Re-arm after silence
SILENCE_THRESHOLD = 0.02
SILENCE_TIME_REQUIRED = 0.3

# =========================
# STATE
# =========================
silence_start = None
armed = True

# Smooth predictions
history = deque(maxlen=3)

# =========================
# LOAD MODEL
# =========================
print("🔊 Loading wake word model...")

model = Model()

print("Loaded models:", model.models.keys())

print("Available wake words:", model.models.keys())
print("Loaded models:", model.models.keys())

# =========================
# AUDIO BUFFER
# =========================
buffer_size = int(SAMPLE_RATE * 1.0)
audio_buffer = np.zeros(buffer_size, dtype=np.float32)


# =========================
# AUDIO CALLBACK
# =========================
def audio_callback(indata, frames, time_info, status):
    global audio_buffer

    if status:
        print("⚠️", status)

    # Mono audio
    audio = indata[:, 0]

    # Keep rolling 1-second buffer
    audio_buffer = np.concatenate((audio_buffer, audio))
    audio_buffer = audio_buffer[-buffer_size:]


# =========================
# MAIN LOOP
# =========================
print("\n✅ Ready")
print("\n👂 Listening for wake word...\n")

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    ):

        while True:
            # =========================
            # AUDIO LEVEL
            # =========================
            rms = np.sqrt(np.mean(audio_buffer**2))

            # =========================
            # MODEL INPUT
            # =========================
            audio_int16 = (audio_buffer * 32767).astype(np.int16)

            predictions = model.predict(audio_int16)

            score = predictions.get("ezra", 0.0)

            # Smooth scores
            history.append(score)

            avg_score = sum(history) / len(history)
            peak_score = max(history)

            # Debug display
            print(f"🎤 RMS: {rms:.3f} | 🎧 jarvis: {avg_score:.3f}")

            current_time = time.time()

            # =========================
            # RE-ARM AFTER SILENCE
            # =========================
            if rms < SILENCE_THRESHOLD:
                if silence_start is None:
                    silence_start = current_time

                elif (current_time - silence_start) > SILENCE_TIME_REQUIRED:
                    armed = True

            else:
                silence_start = None

            # =========================
            # WAKE WORD DETECTION
            # =========================
            if peak_score > THRESHOLD and armed:
                print("🚀 WAKE WORD DETECTED!")

                # Prevent immediate retrigger
                armed = False

                # Clear rolling history
                history.clear()

                # ==================================================
                # TODO:
                # Launch Ezra assistant here
                # ==================================================
                # handle_wake_word()

            time.sleep(0.05)

except KeyboardInterrupt:
    print("\n🛑 Stopped")
