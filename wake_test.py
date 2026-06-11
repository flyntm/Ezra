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

# Main wake threshold
THRESHOLD = 0.20

# Stop command threshold
STOP_THRESHOLD = 0.45

# Prevent repeated wake triggers
COOLDOWN = 1.5

# Prevent repeated stop triggers
STOP_COOLDOWN = 1.0

# Delay before confirming wake
WAKE_CONFIRM_DELAY = 0.25

# Suppress wake after STOP
STOP_SUPPRESSION_TIME = 1.0

# Re-arm threshold
REARM_THRESHOLD = 0.05

# =========================
# STATE
# =========================
armed = True

last_trigger_time = 0
last_stop_time = 0

pending_wake = False
pending_wake_time = 0
pending_phrase = None

# Prevent delayed wake after stop
stop_suppression_until = 0

# Smooth predictions
history = deque(maxlen=4)

# =========================
# LOAD MODELS
# =========================
print("🔊 Loading wake word models...")

model = Model(
    wakeword_models=[
        "/home/flyntm/projects/ezra/ezra.onnx",
        "/home/flyntm/projects/ezra/hey_ezra.onnx",
        "/home/flyntm/projects/ezra/ezra_stop.onnx",
    ],
    inference_framework="onnx",
)

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
print("\n👂 Listening for wake words...\n")

try:
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        channels=1,
        dtype="float32",
        callback=audio_callback,
    ):

        while True:

            current_time = time.time()

            # =========================
            # MODEL INPUT
            # =========================
            audio_int16 = (audio_buffer * 32767).astype(np.int16)

            predictions = model.predict(audio_int16)

            # =========================
            # GET SCORES
            # =========================
            ezra_score = predictions.get("ezra", 0.0)

            hey_ezra_score = predictions.get("hey_ezra", 0.0)

            stop_score = predictions.get("ezra_stop", 0.0)

            # =========================
            # PRIORITIZE HEY EZRA
            # =========================
            if hey_ezra_score > 0.5:
                wake_score = hey_ezra_score
                detected_phrase = "HEY EZRA"

            else:
                wake_score = ezra_score
                detected_phrase = "EZRA"

            # =========================
            # SMOOTH SCORES
            # =========================
            history.append(wake_score)

            avg_score = sum(history) / len(history)
            peak_score = max(history)

            # =========================
            # DEBUG DISPLAY
            # =========================
            if peak_score > 0.05 or stop_score > 0.05:
                print(
                    f"🎧 ezra: {ezra_score:.3f} | "
                    f"hey_ezra: {hey_ezra_score:.3f} | "
                    f"stop: {stop_score:.3f}"
                )

            # =========================
            # STOP DETECTION
            # =========================
            # if (
            #     stop_score > STOP_THRESHOLD
            #     and current_time - last_stop_time > STOP_COOLDOWN
            # ):

            #     print("🛑 EZRA STOP DETECTED!")

            #     last_stop_time = current_time

            #     # Cancel pending wake
            #     pending_wake = False

            #     # Suppress wake temporarily
            #     stop_suppression_until = current_time + STOP_SUPPRESSION_TIME

            # =====================================
            # TODO:
            # Interrupt Ezra here
            # Stop TTS
            # Stop servos
            # Cancel OpenAI stream
            # =====================================

            # =========================
            # START PENDING WAKE
            # =========================
            if (
                peak_score > THRESHOLD
                and armed
                and not pending_wake
                and current_time > stop_suppression_until
            ):

                pending_wake = True
                pending_wake_time = current_time
                pending_phrase = detected_phrase

            # =========================
            # CONFIRM PENDING WAKE
            # =========================
            if pending_wake:

                # STOP overrides wake
                if stop_score > STOP_THRESHOLD:

                    pending_wake = False

                elif current_time - pending_wake_time > WAKE_CONFIRM_DELAY:

                    print(f"🚀 {pending_phrase} DETECTED!")

                    pending_wake = False

                    # Prevent retrigger
                    armed = False

                    # Start cooldown timer
                    last_trigger_time = current_time

                    # Clear rolling history
                    history.clear()

                    # =====================================
                    # TODO:
                    # Launch Ezra assistant here
                    # =====================================
                    # handle_wake_word()

            # =========================
            # RE-ARM LOGIC
            # =========================
            if not armed:

                if (
                    current_time - last_trigger_time > COOLDOWN
                    and peak_score < REARM_THRESHOLD
                ):
                    armed = True

            time.sleep(0.05)

except KeyboardInterrupt:
    print("\n🛑 Stopped")
