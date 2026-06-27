import contextlib
import os
import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import (
    CONTINUOUS_CAPTURE_AFTER_WAKE,
    EZRA_PREFERENCE_FLOOR,
    FORCE_HEY_EZRA_SCORE,
    HEY_EZRA_DOMINANCE_MARGIN,
    HEY_EZRA_MIN_SCORE,
    POST_WAKE_AUDIO_SECONDS_EZRA,
    POST_WAKE_AUDIO_SECONDS_HEY_EZRA,
    PREBUFFER_SECONDS,
    RECENT_AUDIO_SECONDS,
    SEED_ACTIVITY_WINDOW_SECONDS,
    SLEEP_TIMEOUT,
    STOP_GUARD_HITS,
    STOP_GUARD_THRESHOLD,
    WAKE_BLOCK_SIZE as BLOCK_SIZE,
    WAKE_CHANNELS as CHANNELS,
    WAKE_COMMAND_TIMEOUT as COMMAND_TIMEOUT,
    WAKE_CONFIRM_DELAY,
    WAKE_END_POST_ROLL_SECONDS as END_POST_ROLL_SECONDS,
    WAKE_END_SILENCE as END_SILENCE,
    WAKE_ACTIVE_RMS_THRESHOLD as ACTIVE_RMS_THRESHOLD,
    WAKE_MAX_COMMAND_TIME as MAX_COMMAND_TIME,
    WAKE_MIC_DEVICE as MIC_DEVICE,
    WAKE_MIC_OPEN_RETRIES as MIC_OPEN_RETRIES,
    WAKE_MIC_RELEASE_DELAY as MIC_RELEASE_DELAY,
    WAKE_MIC_RETRY_DELAY as MIC_RETRY_DELAY,
    WAKE_REARM_THRESHOLD as REARM_THRESHOLD,
    WAKE_SAMPLE_RATE as SAMPLE_RATE,
    WAKE_TAIL_TRIM_SECONDS_EZRA,
    WAKE_TAIL_TRIM_SECONDS_HEY_EZRA,
    WAKE_THRESHOLD as THRESHOLD,
    QUIET_STARTUP,
)
from respeaker_io import create_respeaker_or_raise

from robot import eyelids
from robot import eyes
from robot import robot_emotions

# =========================
# RESPEAKER
# =========================

mic = create_respeaker_or_raise()

if not QUIET_STARTUP:
    print("✅ ReSpeaker Connected")


# =========================
# MODEL
# =========================


@contextlib.contextmanager
def suppress_stderr():
    """Temporarily silence native library warnings written to stderr."""

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)

    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        os.close(devnull)


with suppress_stderr():
    from openwakeword.model import Model

    model = Model(
        wakeword_models=[
            "/home/flyntm/projects/ezra/ezra.onnx",
            "/home/flyntm/projects/ezra/hey_ezra.onnx",
            "/home/flyntm/projects/ezra/ezra_stop.onnx",
            "/home/flyntm/projects/ezra/ezzera.onnx",
        ],
        inference_framework="onnx",
    )

if not QUIET_STARTUP:
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


def get_new_buffer_samples(buffer, start_idx, end_idx):
    """Return samples between two circular-buffer indices."""

    if start_idx == end_idx:
        return np.empty((0,), dtype=buffer.dtype)

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
    stop_history = deque(maxlen=STOP_GUARD_HITS)

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

    def capture_command_same_stream(seed_audio):
        """
        Capture command audio from the already-open wake stream.

        Always seeds with the full wake handoff clip so no speech
        is lost regardless of pause length. Polls the live circular
        buffer until silence, then returns all audio for STT.
        Wake-word tokens in the transcript are stripped in main.
        """

        frames = []
        seed_tail_rms = 0.0
        seed_arr = None

        if seed_audio is not None and len(seed_audio) > 0:
            seed_arr = np.asarray(seed_audio, dtype=np.float32)
            frames.append(seed_arr)

            tail_samples = int(SEED_ACTIVITY_WINDOW_SECONDS * SAMPLE_RATE)
            seed_tail = seed_arr[-tail_samples:] if tail_samples > 0 else seed_arr

            if seed_tail.size > 0:
                seed_tail_rms = float(np.sqrt(np.mean(seed_tail**2)))

        last_idx = recent_buffer_idx
        last_active_time = None
        start_time = time.time()

        if seed_tail_rms >= ACTIVE_RMS_THRESHOLD:
            last_active_time = start_time
            print(f"🎤 Seed tail active (rms={seed_tail_rms:.4f})")

        while True:
            time.sleep(0.02)

            current_idx = recent_buffer_idx
            new_chunk = get_new_buffer_samples(
                recent_audio_buffer,
                last_idx,
                current_idx,
            )
            last_idx = current_idx

            chunk_rms = 0.0
            if new_chunk.size > 0:
                frames.append(new_chunk.astype(np.float32, copy=False))
                chunk_rms = float(np.sqrt(np.mean(new_chunk**2)))

            now = time.time()

            if chunk_rms >= ACTIVE_RMS_THRESHOLD:
                if last_active_time is None:
                    print("🎤 Command speech detected")
                last_active_time = now
            elif last_active_time is None:
                # No speech seen yet — wait up to COMMAND_TIMEOUT.
                if now - start_time >= COMMAND_TIMEOUT:
                    if seed_arr is not None and seed_arr.size > 0:
                        print(
                            "⚠️ No post-wake speech detected within timeout — "
                            "using wake handoff audio"
                        )
                        return seed_arr.astype(np.float32, copy=False)

                    print("⚠️ No command speech detected within timeout")
                    return None
            elif now - last_active_time >= END_SILENCE:
                post_roll_until = now + END_POST_ROLL_SECONDS

                while time.time() < post_roll_until:
                    time.sleep(0.02)
                    current_idx = recent_buffer_idx
                    post_chunk = get_new_buffer_samples(
                        recent_audio_buffer,
                        last_idx,
                        current_idx,
                    )
                    last_idx = current_idx

                    if post_chunk.size > 0:
                        frames.append(post_chunk.astype(np.float32, copy=False))

                print("🛑 Command ended after silence")
                break

            if now - start_time >= MAX_COMMAND_TIME:
                print("⚠️ Maximum command time reached")
                break

        if not frames:
            return None

        return np.concatenate(frames, axis=0).astype(np.float32, copy=False)

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

            stop_history.append(stop_score >= STOP_GUARD_THRESHOLD)
            stop_guard_active = len(stop_history) == STOP_GUARD_HITS and all(
                stop_history
            )

            # The Ezra and Ezzera models both count as "Ezra."
            ezra_combined = max(
                ezra_score,
                ezzera_score,
            )

            # Disambiguate wake phrase labels so plain "ezra" is not
            # frequently tagged as "hey ezra" by model-score noise.
            detected_phrase = "EZRA"

            hey_is_strong = hey_ezra_score >= HEY_EZRA_MIN_SCORE
            hey_is_dominant = (
                hey_ezra_score - ezra_combined
            ) >= HEY_EZRA_DOMINANCE_MARGIN
            ezra_is_meaningful = ezra_combined >= EZRA_PREFERENCE_FLOOR
            force_hey = hey_ezra_score >= FORCE_HEY_EZRA_SCORE

            if force_hey or (
                hey_is_strong and hey_is_dominant and not ezra_is_meaningful
            ):
                detected_phrase = "HEY EZRA"

            wake_score = max(ezra_combined, hey_ezra_score)

            history.append(wake_score)
            peak_score = max(history)

            if peak_score > 0.05 or stop_score > 0.05:
                print(
                    f"🎤 RMS: {rms:.3f} | "
                    f"VAD: {'YES' if speech else 'NO '} | "
                    f"🎧 ezra: {ezra_score:.3f} | "
                    f"hey_ezra: {hey_ezra_score:.3f} | "
                    f"ezzera: {ezzera_score:.3f} | "
                    f"stop: {stop_score:.3f} "
                    f"(guard={'ON' if stop_guard_active else 'off'})"
                )

            # Start a pending wake detection.
            if peak_score >= THRESHOLD and armed and not pending_wake:
                pending_wake = True
                pending_wake_time = current_time
                pending_phrase = detected_phrase

            # Confirm the pending detection.
            if pending_wake:
                # Keep the pending phrase updated with the freshest frame.
                pending_phrase = detected_phrase

                if current_time - pending_wake_time >= WAKE_CONFIRM_DELAY:
                    pending_wake = False
                    armed = False
                    history.clear()

                    if sleeping:
                        wake_up()
                        sleeping = False

                    last_activity_time = current_time

                    phrase = handle_wake_word(pending_phrase)

                    # Use different capture and trim values for the short and long wake phrases.
                    if phrase == "hey ezra":
                        post_wake_audio_seconds = POST_WAKE_AUDIO_SECONDS_HEY_EZRA
                        wake_tail_trim_seconds = WAKE_TAIL_TRIM_SECONDS_HEY_EZRA
                    else:
                        post_wake_audio_seconds = POST_WAKE_AUDIO_SECONDS_EZRA
                        wake_tail_trim_seconds = WAKE_TAIL_TRIM_SECONDS_EZRA

                    time.sleep(post_wake_audio_seconds)

                    # Include a small pre-detection span plus post-wake span so
                    # continuous speech like "ezra what time..." keeps the first word.
                    handoff_seconds = PREBUFFER_SECONDS + post_wake_audio_seconds

                    wake_audio = get_buffer_in_order(
                        recent_audio_buffer,
                        recent_buffer_idx,
                        min(
                            recent_buffer_len,
                            int(handoff_seconds * SAMPLE_RATE),
                        ),
                    )

                    trim_samples = int(wake_tail_trim_seconds * SAMPLE_RATE)
                    if len(wake_audio) > trim_samples:
                        wake_audio = wake_audio[trim_samples:]
                        print(
                            f"✂️ Trimmed {wake_tail_trim_seconds:.2f} sec from wake handoff"
                        )

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
                        if CONTINUOUS_CAPTURE_AFTER_WAKE:
                            command_audio = capture_command_same_stream(wake_audio)
                            return phrase, command_audio

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
