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


def handle_stop():
    """
    Called when Ezra Stop is detected.
    """

    print("\n🛑 EZRA STOP DETECTED!")

    return "ezra stop"


THRESHOLD = 0.30
STOP_THRESHOLD = 0.45

COOLDOWN = 1.5
STOP_COOLDOWN = 1.0

WAKE_CONFIRM_DELAY = 0.25
STOP_SUPPRESSION_TIME = 1.0

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

stop_suppression_until = 0

history = deque(maxlen=4)


# =========================
# ACTIONS
# =========================
def handle_wake_word(phrase):
    """
    Called when Ezra or Hey Ezra is confirmed.
    """

    print(f"\n🚀 {phrase} DETECTED!")

    return phrase.lower()


def handle_stop():
    """
    Called when Ezra Stop is detected.
    """

    print("\n🛑 EZRA STOP DETECTED!")

    return "ezra stop"


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

    audio = indata[:, 0]

    audio_buffer = np.concatenate((audio_buffer, audio))
    audio_buffer = audio_buffer[-buffer_size:]


# =========================
# MAIN LOOP
# =========================
def run():

    global armed
    global last_trigger_time
    global last_stop_time

    global pending_wake
    global pending_wake_time
    global pending_phrase

    global stop_suppression_until

    print("\n✅ Ready")
    print("\n👂 Listening for wake words...\n")

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
            rms = np.sqrt(np.mean(audio_buffer**2))

            predictions = model.predict(audio_int16)

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

            peak_score = max(history)

            # =========================
            # DEBUG DISPLAY
            # =========================
            if peak_score > 0.05 or stop_score > 0.05:
                print(
                    f"🎤 RMS: {rms:.3f} | "
                    f"🎧 ezra: {ezra_score:.3f} | "
                    f"hey_ezra: {hey_ezra_score:.3f} | "
                    f"stop: {stop_score:.3f}"
                )

            # =========================
            # STOP DETECTION
            # =========================
            if (
                stop_score > STOP_THRESHOLD
                and current_time - last_stop_time > STOP_COOLDOWN
            ):

                last_stop_time = current_time

                pending_wake = False

                stop_suppression_until = current_time + STOP_SUPPRESSION_TIME

                return handle_stop()

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

                if stop_score > STOP_THRESHOLD:

                    pending_wake = False

                elif current_time - pending_wake_time > WAKE_CONFIRM_DELAY:

                    pending_wake = False

                    armed = False

                    last_trigger_time = current_time

                    history.clear()

                    return handle_wake_word(pending_phrase)

            # =========================
            # RE-ARM
            # =========================
            if not armed:

                if (
                    current_time - last_trigger_time > COOLDOWN
                    and peak_score < REARM_THRESHOLD
                ):
                    armed = True

            time.sleep(0.05)


def wait_for_wake_word():
    return run()


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":

    try:
        run()

    except KeyboardInterrupt:
        print("\n🛑 Stopped")
