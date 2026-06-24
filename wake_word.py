import sys
import time
from collections import deque

import numpy as np
import sounddevice as sd
import usb.core
from openwakeword.model import Model

from robot import eyelids
from robot import eyes
from robot import robot_emotions

# =========================
# CONFIG
# =========================

MIC_DEVICE = 1

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1024

# Wake-word sensitivity
THRESHOLD = 0.15
REARM_THRESHOLD = 0.05

# Small delay after the score first crosses the threshold.
WAKE_CONFIRM_DELAY = 0.10

# Audio returned with the detected wake word.
# Increase slightly to preserve more pre-wake audio across the handoff.
RECENT_AUDIO_SECONDS = 2.5
# Keep a small prebuffer of command audio around the wake word.
PREBUFFER_SECONDS = 0.80
# Continue capturing briefly after detecting the wake word.
POST_WAKE_AUDIO_SECONDS = 0.80

# Testing value. Change to 180 later.
SLEEP_TIMEOUT = 20

# Direct ALSA device 1 may remain busy briefly while switching
# between Listen and Wake.
MIC_OPEN_RETRIES = 8
MIC_RETRY_DELAY = 0.25
MIC_RELEASE_DELAY = 0.25


# =========================
# RESPEAKER
# =========================

sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")

from xvf_host import ReSpeaker

dev = usb.core.find(idVendor=0x2886)

if not dev:
    raise RuntimeError("❌ ReSpeaker not found")

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
# AUDIO HELPERS
# =========================


def get_buffer_in_order(buffer, start_idx, count):
    """Extract the most recent valid samples in chronological order."""
    if count <= 0:
        return np.empty((0,), dtype=buffer.dtype)

    buffer_len = len(buffer)
    if buffer_len == 0:
        return np.empty((0,), dtype=buffer.dtype)

    count = min(count, buffer_len)
    end_idx = start_idx % buffer_len
    start_idx = (end_idx - count) % buffer_len

    if count == buffer_len:
        if end_idx == 0:
            return buffer.copy()
        return np.concatenate([buffer[end_idx:], buffer[:end_idx]])

    if start_idx < end_idx:
        return buffer[start_idx:end_idx].copy()

    return np.concatenate([buffer[start_idx:], buffer[:end_idx]])


BUFFER_SECONDS = 1.0

buffer_size = int(SAMPLE_RATE * BUFFER_SECONDS)
recent_buffer_size = int(SAMPLE_RATE * RECENT_AUDIO_SECONDS)

# Preallocated circular buffers and indices for fast callback
audio_buffer = np.zeros(buffer_size, dtype=np.float32)
recent_audio_buffer = np.zeros(recent_buffer_size, dtype=np.float32)
audio_buffer_idx = 0
recent_buffer_idx = 0
audio_buffer_len = 0
recent_buffer_len = 0


# =========================
# STATE
# =========================

sleeping = False
last_activity_time = time.time()


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


# =========================
# AUDIO CALLBACK
# =========================


def audio_callback(indata, frames, time_info, status):
    global audio_buffer, recent_audio_buffer
    global audio_buffer_idx, recent_buffer_idx
    global audio_buffer_len, recent_buffer_len

    if status:
        print("⚠️", status)

    audio = indata[:, 0].copy()
    n_samples = len(audio)

    # Circular buffer fill for audio_buffer
    remaining = buffer_size - audio_buffer_idx

    if n_samples <= remaining:
        audio_buffer[audio_buffer_idx : audio_buffer_idx + n_samples] = audio
        audio_buffer_idx += n_samples
        if audio_buffer_idx >= buffer_size:
            audio_buffer_idx = 0
    else:
        audio_buffer[audio_buffer_idx:] = audio[:remaining]
        audio_buffer[: n_samples - remaining] = audio[remaining:]
        audio_buffer_idx = n_samples - remaining

    audio_buffer_len = min(buffer_size, audio_buffer_len + n_samples)

    # Circular buffer fill for recent_audio_buffer
    remaining = recent_buffer_size - recent_buffer_idx

    if n_samples <= remaining:
        recent_audio_buffer[recent_buffer_idx : recent_buffer_idx + n_samples] = audio
        recent_buffer_idx += n_samples
        if recent_buffer_idx >= recent_buffer_size:
            recent_buffer_idx = 0
    else:
        recent_audio_buffer[recent_buffer_idx:] = audio[:remaining]
        recent_audio_buffer[: n_samples - remaining] = audio[remaining:]
        recent_buffer_idx = n_samples - remaining

    recent_buffer_len = min(recent_buffer_size, recent_buffer_len + n_samples)


# =========================
# MICROPHONE
# =========================


def open_microphone():
    """
    Open the direct ReSpeaker ALSA input.

    Listen and Wake use the same hardware device, so ALSA may need
    a brief moment to release it between streams.
    """

    last_error = None

    for attempt in range(1, MIC_OPEN_RETRIES + 1):
        try:
            stream = sd.InputStream(
                device=MIC_DEVICE,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=audio_callback,
            )

            stream.start()
            return stream

        except sd.PortAudioError as e:
            last_error = e

            if attempt < MIC_OPEN_RETRIES:
                print(
                    f"⚠️ Microphone busy — retrying "
                    f"({attempt}/{MIC_OPEN_RETRIES})..."
                )
                time.sleep(MIC_RETRY_DELAY)

    raise last_error


# =========================
# MAIN LOOP
# =========================


def run(return_audio=False):
    global audio_buffer
    global recent_audio_buffer
    global sleeping
    global last_activity_time
    global audio_buffer_idx, recent_buffer_idx
    global audio_buffer_len, recent_buffer_len

    # Reset all detection state each time Wake is entered.
    #
    # This is important because Main calls this function again after
    # every command. A previous wake must not leave the next run
    # disarmed.
    armed = True

    pending_wake = False
    pending_wake_time = 0.0
    pending_phrase = None

    history = deque(maxlen=4)

    audio_buffer = np.zeros(
        buffer_size,
        dtype=np.float32,
    )

    recent_audio_buffer = np.zeros(
        recent_buffer_size,
        dtype=np.float32,
    )

    audio_buffer_idx = 0
    recent_buffer_idx = 0
    audio_buffer_len = 0
    recent_buffer_len = 0

    # Flush stale OpenWakeWord features from the previous detection.
    flush_audio = np.zeros(
        SAMPLE_RATE,
        dtype=np.int16,
    )

    model.predict(flush_audio)

    print("\n✅ Ready")
    print("\n👂 Listening for wake words...\n")

    stream = open_microphone()

    try:
        while True:
            current_time = time.time()

            # =========================
            # SLEEP CHECK
            # =========================

            if not sleeping and current_time - last_activity_time > SLEEP_TIMEOUT:
                enter_sleep()
                sleeping = True

            # ReSpeaker VAD is retained for diagnostics and DoA,
            # but it does not block OpenWakeWord processing.
            speech = False
            angle = None

            try:
                doa = mic.read("DOA_VALUE")

                if len(doa) >= 2:
                    angle = doa[0]
                    speech = bool(doa[1])

            except Exception as e:
                print(f"VAD error: {e}")

            # Always run OpenWakeWord, even if the ReSpeaker VAD
            # does not recognize quiet speech.
            audio_int16 = np.clip(
                audio_buffer * 32767,
                -32768,
                32767,
            ).astype(np.int16)

            rms = float(np.sqrt(np.mean(audio_buffer**2)))

            predictions = model.predict(audio_int16)

            ezra_score = float(predictions.get("ezra", 0.0))
            hey_ezra_score = float(predictions.get("hey_ezra", 0.0))
            stop_score = float(predictions.get("ezra_stop", 0.0))
            ezzera_score = float(predictions.get("ezzera", 0.0))

            # The Ezra and Ezzera models both count as "Ezra."
            ezra_combined = max(
                ezra_score,
                ezzera_score,
            )

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
                    f"VAD: {'YES' if speech else 'NO '} | "
                    f"🎧 ezra: {ezra_score:.3f} | "
                    f"hey_ezra: {hey_ezra_score:.3f} | "
                    f"ezzera: {ezzera_score:.3f} | "
                    f"stop: {stop_score:.3f}"
                )

            # Start a pending wake detection.
            if peak_score >= THRESHOLD and armed and not pending_wake:
                pending_wake = True
                pending_wake_time = current_time
                pending_phrase = detected_phrase

            # Confirm the pending detection.
            if pending_wake:
                if current_time - pending_wake_time >= WAKE_CONFIRM_DELAY:
                    pending_wake = False
                    armed = False
                    history.clear()

                    if sleeping:
                        wake_up()
                        sleeping = False

                    last_activity_time = current_time

                    phrase = handle_wake_word(pending_phrase)

                    # Keep the Wake stream open briefly to capture the beginning
                    # of a command spoken immediately after the wake phrase.
                    time.sleep(POST_WAKE_AUDIO_SECONDS)

                    wake_audio = get_buffer_in_order(
                        recent_audio_buffer,
                        recent_buffer_idx,
                        min(
                            recent_buffer_len,
                            int(POST_WAKE_AUDIO_SECONDS * SAMPLE_RATE),
                        ),
                    )
                    if len(wake_audio) > 0:
                        trim_samples = int(0.20 * SAMPLE_RATE)
                        if len(wake_audio) > trim_samples:
                            wake_audio = wake_audio[trim_samples:]
                    print(
                        f"📼 Captured {len(wake_audio)/SAMPLE_RATE:.2f} sec of post-wake audio"
                    )

                    # Flush the detected wake word from OpenWakeWord's
                    # internal feature buffer before the next run.
                    model.predict(
                        np.zeros(
                            SAMPLE_RATE,
                            dtype=np.int16,
                        )
                    )

                    if return_audio:
                        return phrase, wake_audio

                    return phrase

            # This is mainly useful if run() is used in a mode where
            # it does not immediately return after detection.
            if not armed and peak_score < REARM_THRESHOLD:
                armed = True

            time.sleep(0.05)

    finally:
        try:
            stream.stop()
        except Exception:
            pass

        try:
            stream.close()
        except Exception:
            pass

        # Give ALSA time to release device 1 before Listen opens it.
        time.sleep(MIC_RELEASE_DELAY)


# =========================
# PUBLIC FUNCTIONS
# =========================


def wait_for_wake_word():
    return run(return_audio=False)


def wait_for_wake_word_with_audio():
    return run(return_audio=True)


# =========================
# STANDALONE TEST
# =========================


if __name__ == "__main__":
    try:
        run()

    except KeyboardInterrupt:
        print("\n🛑 Stopped")
