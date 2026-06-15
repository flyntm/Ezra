import numpy as np
import sounddevice as sd
import time
from openwakeword.model import Model
from collections import deque

from robot import robot_emotions
from robot import eyelids
from robot import eyes
import usb.core
import sys

sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")
from xvf_host import ReSpeaker

# =========================
# CONFIG
# =========================
SAMPLE_RATE = 16000
BLOCK_SIZE = 1024

THRESHOLD = 0.20
STOP_THRESHOLD = 0.45

COOLDOWN = 1.5
STOP_COOLDOWN = 1.0

WAKE_CONFIRM_DELAY = 0.1
STOP_SUPPRESSION_TIME = 1.0

REARM_THRESHOLD = 0.05

RECENT_AUDIO_SECONDS = 1.0

# Sleep timeout
SLEEP_TIMEOUT = 20  # testing (change to 180 later)

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

sleeping = False
last_activity_time = time.time()

# =========================
# RESPEAKER VAD
# =========================

dev = usb.core.find(idVendor=0x2886)

if not dev:
    print("❌ ReSpeaker not found")
    raise RuntimeError("ReSpeaker not found")

mic = ReSpeaker(dev)

print("✅ ReSpeaker Connected")

# =========================
# MODEL
# =========================
model = Model(
    wakeword_models=[
        "/home/flyntm/projects/ezra/ezra.onnx",
        "/home/flyntm/projects/ezra/hey_ezra.onnx",
        "/home/flyntm/projects/ezra/ezra_stop.onnx",
        "/home/flyntm/projects/ezra/ezzera.onnx",
    ],
    inference_framework="onnx",
)

print("Loaded models:", model.models.keys())

# =========================
# AUDIO BUFFERS
# =========================
buffer_size = int(SAMPLE_RATE * 1.0)
recent_buffer_size = int(SAMPLE_RATE * RECENT_AUDIO_SECONDS)

audio_buffer = np.zeros(buffer_size, dtype=np.float32)
recent_audio_buffer = np.zeros(recent_buffer_size, dtype=np.float32)


# =========================
# SLEEP HELPERS
# =========================


def reset_idle_timer():
    global last_activity_time

    last_activity_time = time.time()
    print("⏰ IDLE TIMER RESET")


def enter_sleep():
    print("\n😴 Ezra sleeping")

    try:
        eyes.center()
        eyelids.close_lids()

        robot_emotions.stop(
            clear_mouth=True,
            relax_servos=False,
        )

    except Exception as e:
        print(f"Sleep error: {e}")


def wake_up():
    print("\n😊 Ezra waking up")

    try:
        robot_emotions.start("listening")
        eyelids.open_lids()

    except Exception as e:
        print(f"Wake error: {e}")


# =========================
# ACTIONS
# =========================
def handle_wake_word(phrase):
    print(f"\n🚀 {phrase} DETECTED!")
    return phrase.lower()


def handle_stop():
    print("\n🛑 EZRA STOP DETECTED!")
    return "ezra stop"


# =========================
# AUDIO CALLBACK
# =========================
def audio_callback(indata, frames, time_info, status):
    global audio_buffer
    global recent_audio_buffer

    if status:
        print("⚠️", status)

    audio = indata[:, 0].copy()

    audio_buffer = np.concatenate((audio_buffer, audio))
    audio_buffer = audio_buffer[-buffer_size:]

    recent_audio_buffer = np.concatenate((recent_audio_buffer, audio))
    recent_audio_buffer = recent_audio_buffer[-recent_buffer_size:]


# =========================
# MAIN LOOP
# =========================
def run(return_audio=False):
    global armed
    global last_trigger_time
    global last_stop_time
    global pending_wake
    global pending_wake_time
    global pending_phrase
    global stop_suppression_until
    global audio_buffer
    global recent_audio_buffer
    global sleeping
    global last_activity_time

    audio_buffer = np.zeros(buffer_size, dtype=np.float32)
    recent_audio_buffer = np.zeros(recent_buffer_size, dtype=np.float32)

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
            # SLEEP CHECK
            # =========================
            if not sleeping and current_time - last_activity_time > SLEEP_TIMEOUT:
                enter_sleep()
                sleeping = True

            doa = mic.read("DOA_VALUE")

            speech = False

            if len(doa) >= 2:
                speech = bool(doa[1])
                angle = doa[0]

            if not speech:
                time.sleep(0.05)
                continue

            audio_int16 = (audio_buffer * 32767).astype(np.int16)
            rms = np.sqrt(np.mean(audio_buffer**2))

            predictions = model.predict(audio_int16)

            ezra_score = predictions.get("ezra", 0.0)
            hey_ezra_score = predictions.get("hey_ezra", 0.0)
            stop_score = predictions.get("ezra_stop", 0.0)
            ezzera_score = predictions.get("ezzera", 0.0)

            ezra_combined = max(ezra_score, ezzera_score)

            wake_score = ezra_combined
            detected_phrase = "EZRA"

            if hey_ezra_score > wake_score:
                wake_score = hey_ezra_score
                detected_phrase = "HEY EZRA"

            history.append(wake_score)
            peak_score = max(history)

            if peak_score > 0.05 or stop_score > 0.05:
                print(
                    f"🎤 RMS: {rms:.3f} | "
                    f"🎧 ezra: {ezra_score:.3f} | "
                    f"hey_ezra: {hey_ezra_score:.3f} | "
                    f"ezzera: {ezzera_score:.3f} | "
                    f"stop: {stop_score:.3f}"
                )

            if (
                peak_score > THRESHOLD
                and armed
                and not pending_wake
                and current_time > stop_suppression_until
            ):
                pending_wake = True
                pending_wake_time = current_time
                pending_phrase = detected_phrase

            if pending_wake:

                if False and stop_score > STOP_THRESHOLD:
                    pending_wake = False

                elif current_time - pending_wake_time > WAKE_CONFIRM_DELAY:

                    pending_wake = False
                    armed = False
                    last_trigger_time = current_time
                    history.clear()

                    if sleeping:
                        wake_up()
                        sleeping = False

                    # print(
                    #     f"DEBUG wake phrase={pending_phrase} "
                    #     f"ezra={ezra_score:.3f} "
                    #     f"hey={hey_ezra_score:.3f} "
                    #     f"ezzera={ezzera_score:.3f}"
                    # )

                    phrase = handle_wake_word(pending_phrase)

                    if return_audio:
                        return phrase, recent_audio_buffer.copy()

                    return phrase

            if not armed:
                if (
                    current_time - last_trigger_time > COOLDOWN
                    and peak_score < REARM_THRESHOLD
                ):
                    armed = True

            time.sleep(0.05)


def wait_for_wake_word():
    return run(return_audio=False)


def wait_for_wake_word_with_audio():
    return run(return_audio=True)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n🛑 Stopped")
