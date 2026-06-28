import contextlib
from collections import deque
import os
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd

from config import *
from ezra_emotion import set_emotion
import state


@contextlib.contextmanager
def suppress_stderr():
    """Temporarily suppress low-level native stderr warnings."""

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)

    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        os.close(devnull)


_stop_model = None

if ENABLE_MID_RESPONSE_STOP:
    try:
        with suppress_stderr():
            from openwakeword.model import Model

            _stop_model = Model(
                wakeword_models=[MID_RESPONSE_STOP_MODEL_PATH],
                inference_framework="onnx",
            )

            # Warm up internal buffers so first live stop phrase is not missed.
            _stop_model.predict(np.zeros(WAKE_SAMPLE_RATE, dtype=np.int16))

        state.mid_response_stop_ready = True
    except Exception as e:
        _stop_model = None
        state.mid_response_stop_ready = False
        if not QUIET_STARTUP:
            print(f"⚠️ Mid-response stop disabled: {e}")


def _monitor_stop_phrase(stop_event):
    """Listen for ezra_stop while TTS audio is playing."""

    if _stop_model is None:
        return

    audio_queue = deque()
    stop_hits = deque(maxlen=MID_RESPONSE_STOP_GUARD_HITS)
    rolling = np.zeros(WAKE_SAMPLE_RATE, dtype=np.float32)
    rolling_filled = 0

    def audio_callback(indata, frames, time_info, status):
        if status:
            return
        audio_queue.append(indata[:, 0].copy())

    try:
        with sd.InputStream(
            device=WAKE_MIC_DEVICE,
            samplerate=WAKE_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=WAKE_BLOCK_SIZE,
            callback=audio_callback,
        ):
            while not stop_event.is_set():
                if not audio_queue:
                    time.sleep(0.01)
                    continue

                chunk = audio_queue.popleft()

                if chunk.size >= rolling.size:
                    boosted = np.clip(
                        chunk[-rolling.size :] * MID_RESPONSE_STOP_MIC_GAIN,
                        -1.0,
                        1.0,
                    )
                    rolling = boosted.astype(np.float32, copy=False)
                    rolling_filled = rolling.size
                else:
                    shift = chunk.size
                    rolling[:-shift] = rolling[shift:]
                    rolling[-shift:] = np.clip(
                        chunk * MID_RESPONSE_STOP_MIC_GAIN,
                        -1.0,
                        1.0,
                    )
                    rolling_filled = min(rolling.size, rolling_filled + shift)

                min_samples = max(
                    1,
                    int(WAKE_SAMPLE_RATE * MID_RESPONSE_STOP_MIN_WINDOW_SECONDS),
                )
                if rolling_filled < min_samples:
                    continue

                # Keep model input length fixed to match wake-word runtime expectations.
                audio_int16 = np.clip(rolling * 32767, -32768, 32767).astype(np.int16)

                predictions = _stop_model.predict(audio_int16)
                stop_score = float(predictions.get("ezra_stop", 0.0))

                stop_hits.append(stop_score >= MID_RESPONSE_STOP_GUARD_THRESHOLD)

                if len(stop_hits) == MID_RESPONSE_STOP_GUARD_HITS and all(stop_hits):
                    stop_event.set()
                    print("🛑 Stop phrase detected — interrupting response")
                    return
    except Exception as e:
        # Keep TTS running even if monitor fails, but surface diagnostics.
        if not QUIET_STARTUP:
            print(f"⚠️ Mid-response stop monitor error: {e}")
        return


def speak(text, allow_mid_response_stop=True):
    if state.shutting_down:
        return

    print(f"Ezra: {text}")

    # Generate speech using Piper
    cmd = (
        f'echo "{text}" | '
        f"{PIPER_PATH} "
        f"--model {TTS_MODEL_PATH} "
        f"--output_file temp.wav"
    )

    subprocess.run(
        cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Talking animation
    set_emotion(EMOTION_TALKING)
    time.sleep(TTS_START_DELAY)

    # Play audio and optionally monitor for live stop phrase.
    proc = subprocess.Popen(
        ["aplay", "-D", SPEAKER_DEVICE, "temp.wav"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    state.tts_process = proc

    stop_event = threading.Event()
    monitor_thread = None

    interrupted_by_stop = False

    if (
        ENABLE_MID_RESPONSE_STOP
        and allow_mid_response_stop
        and state.mid_response_stop_ready
    ):
        monitor_thread = threading.Thread(
            target=_monitor_stop_phrase,
            args=(stop_event,),
            daemon=True,
        )
        monitor_thread.start()

    try:
        while proc.poll() is None:
            if stop_event.is_set():
                interrupted_by_stop = True
                proc.terminate()
                try:
                    proc.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.02)
    finally:
        stop_event.set()
        state.tts_process = None

    # Return to listening
    set_emotion(EMOTION_LISTENING)

    if interrupted_by_stop and not state.shutting_down:
        # Confirmation without recursive stop-monitoring.
        speak("Stopped.", allow_mid_response_stop=False)
