import contextlib
import math
import os
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import (
    COMMAND_DOA_MAX_CIRCULAR_DEVIATION_DEGREES,
    COMMAND_DOA_MIN_ACTIVE_SPEECH_SECONDS,
    COMMAND_DOA_ACTIVE_CLUSTER_TOLERANCE_DEGREES,
    COMMAND_DOA_MIN_ACTIVE_CLUSTER_FRACTION,
    COMMAND_DOA_SETTLED_AGREEMENT_DEGREES,
    COMMAND_DOA_STABILITY_WINDOW_SECONDS,
    CONTINUOUS_CAPTURE_AFTER_WAKE,
    EMOTION_LISTENING,
    ENABLE_HEAD_TRACKING,
    ENABLE_HEAD_DIRECTION_DIAGNOSTIC,
    ENABLE_DOA_DIAGNOSTIC,
    ENABLE_INTERACTION_DIAGNOSTIC,
    ENABLE_FACE_MOTION_DIAGNOSTIC,
    ENABLE_SOUND_GAZE,
    EZRA_PREFERENCE_FLOOR,
    FORCE_HEY_EZRA_SCORE,
    HEAD_TRACKING_DIRECTION,
    HEAD_TRACKING_MIC_FORWARD_AZIMUTH,
    HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS,
    HEAD_TRACKING_WAKE_SETTLE_SECONDS,
    HEAD_TRACKING_WAKE_HISTORY_SECONDS,
    HEY_EZRA_DOMINANCE_MARGIN,
    HEY_EZRA_MIN_SCORE,
    POST_WAKE_AUDIO_SECONDS_EZRA,
    POST_WAKE_AUDIO_SECONDS_HEY_EZRA,
    PREBUFFER_SECONDS,
    RESPEAKER_ERROR_LOG_INTERVAL_SECONDS,
    RESPEAKER_RECONNECT_INTERVAL_SECONDS,
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
    WAKE_ONLY_DOA_MIN_ACTIVE_SPEECH_SECONDS,
    MIC_DEVICE as ALSA_MIC_DEVICE,
    WAKE_MIC_DEVICE as MIC_DEVICE,
    WAKE_MIC_OPEN_RETRIES as MIC_OPEN_RETRIES,
    WAKE_MIC_RELEASE_DELAY as MIC_RELEASE_DELAY,
    WAKE_MIC_RETRY_DELAY as MIC_RETRY_DELAY,
    WAKE_REARM_THRESHOLD as REARM_THRESHOLD,
    WAKE_SAMPLE_RATE as SAMPLE_RATE,
    WAKE_TAIL_TRIM_SECONDS_EZRA,
    WAKE_TAIL_TRIM_SECONDS_HEY_EZRA,
    WAKE_THRESHOLD as THRESHOLD,
    VERBOSE_RUNTIME_LOGS,
    SOUND_GAZE_MAX_BEARING_DEGREES,
    SOUND_GAZE_MAX_EYE_OFFSET,
    SOUND_GAZE_RESPONSE_EXPONENT,
    SOUND_GAZE_AMBIENT_COOLDOWN_SECONDS,
    SOUND_GAZE_AMBIENT_HOLD_SECONDS,
    SOUND_GAZE_AMBIENT_MIN_RMS,
    SOUND_GAZE_AMBIENT_MIN_SPEECH_SECONDS,
    SOUND_GAZE_AMBIENT_RESET_SILENCE_SECONDS,
    SOUND_GAZE_TEST_MODE,
    SOUND_GAZE_VERTICAL_POSITION,
)
from respeaker_io import create_respeaker_or_raise

from robot import eyelids
from robot import eyes
from robot import robot_emotions

if (
    ENABLE_HEAD_TRACKING
    and not ENABLE_INTERACTION_DIAGNOSTIC
):
    from robot.head_tracking import head_tracker
else:
    head_tracker = None

# =========================
# RESPEAKER
# =========================

mic = create_respeaker_or_raise()

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
audio_ready = threading.Event()
_last_stream_status_log_at = 0.0


# =========================
# STATE
# =========================

sleeping = False
last_activity_time = time.time()
_last_command_doa = None
_last_command_doa_diagnostic = None
_last_wake_detected_at = None


def get_last_command_doa():
    """Return the continuous capture path's most recent signed command DoA."""
    return _last_command_doa


def get_last_command_doa_diagnostic():
    """Return DoA qualification details for item test 1."""
    return _last_command_doa_diagnostic


def get_last_wake_detected_at():
    """Return the monotonic time of the most recent wake-model detection."""
    return _last_wake_detected_at


def _mean_signed_doa(raw_angles):
    if not raw_angles:
        return None
    sin_sum = sum(math.sin(math.radians(angle)) for angle in raw_angles)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in raw_angles)
    raw_mean = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    relative = (
        raw_mean - HEAD_TRACKING_MIC_FORWARD_AZIMUTH + 180.0
    ) % 360.0 - 180.0
    return HEAD_TRACKING_DIRECTION * relative


def _angular_difference(angle, reference):
    return (float(angle) - float(reference) + 180.0) % 360.0 - 180.0


def _circular_mean_degrees(angles):
    sin_sum = sum(math.sin(math.radians(angle)) for angle in angles)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in angles)
    return math.degrees(math.atan2(sin_sum, cos_sum))


def _qualify_command_doa(samples, stability_samples=None):
    """Use VAD samples for speech duration and settled samples for direction."""
    stability_samples = stability_samples or samples
    active_seconds = sum(duration for _, duration in samples)
    sample_count = len(samples)
    result = {
        "angle": None,
        "qualified": False,
        "active_seconds": active_seconds,
        "sample_count": sample_count,
        "active_angle": None,
        "cluster_fraction": 0.0,
        "settled_angle": None,
        "settled_agreement": None,
        "max_deviation": None,
        "reason": "no valid VAD-backed DoA samples",
    }

    if not samples or not stability_samples:
        return result

    active_bearings = [
        _mean_signed_doa([raw_angle]) for raw_angle, _ in samples
    ]
    dominant_cluster = max(
        (
            [
                bearing
                for bearing in active_bearings
                if abs(_angular_difference(bearing, center))
                <= COMMAND_DOA_ACTIVE_CLUSTER_TOLERANCE_DEGREES
            ]
            for center in active_bearings
        ),
        key=len,
    )
    cluster_fraction = len(dominant_cluster) / len(active_bearings)
    active_angle = _circular_mean_degrees(dominant_cluster)
    result["angle"] = active_angle
    result["active_angle"] = active_angle
    result["cluster_fraction"] = cluster_fraction

    if active_seconds < COMMAND_DOA_MIN_ACTIVE_SPEECH_SECONDS:
        result["reason"] = (
            f"needs {COMMAND_DOA_MIN_ACTIVE_SPEECH_SECONDS:.2f}s active speech"
        )
        return result

    if cluster_fraction < COMMAND_DOA_MIN_ACTIVE_CLUSTER_FRACTION:
        result["reason"] = (
            f"active DoA cluster is {cluster_fraction:.0%} "
            f"(needs {COMMAND_DOA_MIN_ACTIVE_CLUSTER_FRACTION:.0%})"
        )
        return result

    # Prefer the most recent stable window that still agrees with the dominant
    # speech-backed cluster. Stable post-speech noise can no longer win merely
    # because it varies less than the actual voice bearing.
    accepted_window = None
    for end in range(len(stability_samples) - 1, -1, -1):
        window = []
        window_seconds = 0.0
        for index in range(end, -1, -1):
            window.append(stability_samples[index])
            window_seconds += stability_samples[index][1]
            if window_seconds >= COMMAND_DOA_STABILITY_WINDOW_SECONDS:
                break
        if window_seconds < COMMAND_DOA_STABILITY_WINDOW_SECONDS:
            continue

        window_angles = [raw_angle for raw_angle, _ in window]
        window_mean = _mean_signed_doa(window_angles)
        window_deviation = max(
            abs(_angular_difference(_mean_signed_doa([sample_angle]), window_mean))
            for sample_angle in window_angles
        )
        agreement = abs(_angular_difference(window_mean, active_angle))
        if (
            window_deviation <= COMMAND_DOA_MAX_CIRCULAR_DEVIATION_DEGREES
            and agreement <= COMMAND_DOA_SETTLED_AGREEMENT_DEGREES
        ):
            accepted_window = (window_deviation, window_mean, agreement)
            break

    if accepted_window is None:
        result["reason"] = "no stable settled DoA agrees with active speech"
        return result

    max_deviation, recent_mean, agreement = accepted_window
    result["angle"] = recent_mean
    result["settled_angle"] = recent_mean
    result["settled_agreement"] = agreement
    result["max_deviation"] = max_deviation

    result["qualified"] = True
    result["reason"] = "stable"
    return result


def _look_toward_wake_sound(active_angles, settled_angles):
    """Hold an eye-only gaze toward a qualified front-facing speaker."""
    if not ENABLE_SOUND_GAZE:
        return False

    active_samples = [
        (angle, HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS) for angle in active_angles
    ]
    settled_samples = [
        (angle, HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS) for angle in settled_angles
    ]
    result = _qualify_command_doa(active_samples, settled_samples)
    bearing = result.get("angle")

    if not result["qualified"] or bearing is None:
        if VERBOSE_RUNTIME_LOGS:
            print(f"👀 Sound gaze skipped: {result['reason']}")
        return False
    if abs(bearing) > SOUND_GAZE_MAX_BEARING_DEGREES:
        if VERBOSE_RUNTIME_LOGS:
            print(f"👀 Sound gaze ignored rear bearing {bearing:+.1f}°")
        return False

    fraction = bearing / SOUND_GAZE_MAX_BEARING_DEGREES
    curved_fraction = math.copysign(
        abs(fraction) ** SOUND_GAZE_RESPONSE_EXPONENT,
        fraction,
    )
    horizontal = 90.0 + curved_fraction * SOUND_GAZE_MAX_EYE_OFFSET
    robot_emotions.set_external_gaze(horizontal, SOUND_GAZE_VERTICAL_POSITION)
    print(
        f"👀 Looking toward speaker {bearing:+.1f}° "
        f"(eye gaze {horizontal:.1f})"
    )
    return True


# =========================
# SLEEP HELPERS
# =========================


def reset_idle_timer():
    global last_activity_time

    last_activity_time = time.time()
    if VERBOSE_RUNTIME_LOGS:
        print("⏰ IDLE TIMER RESET")


def enter_sleep():
    print("\n😴 Ezra sleeping")

    if head_tracker is not None:
        try:
            head_tracker.center()
        except Exception as e:
            # A neck-servo problem should not prevent the eyes, eyelids, and
            # facial animation from completing the sleep transition.
            print(f"Sleep head-centering error: {e}")

    try:
        robot_emotions.clear_external_gaze()
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
    global _last_stream_status_log_at

    if status:
        now = time.monotonic()
        if now - _last_stream_status_log_at >= RESPEAKER_ERROR_LOG_INTERVAL_SECONDS:
            print("⚠️", status)
            _last_stream_status_log_at = now

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
    audio_ready.set()


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

    mic_candidates = [MIC_DEVICE, ALSA_MIC_DEVICE, "default", None]

    # Keep order but drop duplicates.
    deduped_candidates = []
    for candidate in mic_candidates:
        if candidate not in deduped_candidates:
            deduped_candidates.append(candidate)

    for mic_device in deduped_candidates:
        for attempt in range(1, MIC_OPEN_RETRIES + 1):
            try:
                stream = sd.InputStream(
                    device=mic_device,
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
                err_text = str(e).lower()

                if "no input device matching" in err_text:
                    print(
                        f"⚠️ Mic '{mic_device}' was not found; "
                        "trying next microphone source..."
                    )
                    break

                if "invalid sample rate" in err_text:
                    print(
                        f"⚠️ Mic '{mic_device}' does not support {SAMPLE_RATE} Hz; "
                        "trying next microphone source..."
                    )
                    break

                if attempt < MIC_OPEN_RETRIES:
                    print(
                        f"⚠️ Microphone busy on '{mic_device}' — retrying "
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
    global mic
    global _last_wake_detected_at

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

    wake_direction_history = deque(
        maxlen=max(
            1,
            round(
                HEAD_TRACKING_WAKE_HISTORY_SECONDS
                / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
            ),
        )
    )
    ambient_gaze_angles = deque(
        maxlen=max(
            1,
            round(
                1.5 / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
            ),
        )
    )
    ambient_last_speech_at = None
    ambient_gaze_until = 0.0
    ambient_cooldown_until = 0.0
    last_respeaker_error_at = 0.0
    next_respeaker_reconnect_at = 0.0

    def capture_command_same_stream(
        seed_audio,
        seed_active_doa_angles=None,
        seed_settled_doa_angles=None,
    ):
        """
        Capture command audio from the already-open wake stream.

        Always seeds with the full wake handoff clip so no speech
        is lost regardless of pause length. Polls the live circular
        buffer until silence, then returns all audio for STT.
        Wake-word tokens in the transcript are stripped in main.
        """

        global _last_command_doa, _last_command_doa_diagnostic
        _last_command_doa = None
        _last_command_doa_diagnostic = None

        frames = []
        # Wake and command are one continuous interaction from the same speaker.
        # Seed with the settled wake bearing so short commands already contained
        # in the handoff audio still have a usable direction.
        command_doa_samples = [
            (angle, HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS)
            for angle in (seed_active_doa_angles or ())
        ]
        stability_doa_samples = [
            (angle, HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS)
            for angle in (seed_settled_doa_angles or ())
        ]
        live_command_doa_samples = []

        def finish_command_direction():
            global _last_command_doa, _last_command_doa_diagnostic
            _last_command_doa_diagnostic = _qualify_command_doa(
                command_doa_samples,
                stability_doa_samples,
            )
            _last_command_doa = _last_command_doa_diagnostic["angle"]

            if head_tracker is None:
                return

            # Move only after capture is complete so servo noise cannot enter
            # the follow-on recording. Prefer qualified live command direction.
            if live_command_doa_samples:
                command_result = _qualify_command_doa(
                    live_command_doa_samples,
                    live_command_doa_samples,
                )
                if command_result["qualified"]:
                    head_tracker.turn_toward_bearing(
                        command_result["angle"],
                        source="command",
                    )
                    return

            wake_result = _last_command_doa_diagnostic
            if (
                wake_result["qualified"]
                and wake_result["active_seconds"]
                >= WAKE_ONLY_DOA_MIN_ACTIVE_SPEECH_SECONDS
                and wake_result["angle"] is not None
            ):
                head_tracker.turn_toward_bearing(
                    wake_result["angle"],
                    source="wake word",
                )
            else:
                print(
                    "👂 Wake-only direction uncertain; "
                    "waiting for follow-up speech"
                )
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
            if VERBOSE_RUNTIME_LOGS:
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

            if chunk_rms >= ACTIVE_RMS_THRESHOLD:
                try:
                    doa = mic.read("DOA_VALUE")
                    if (
                        len(doa) == 2
                        and bool(doa[1])
                        and not robot_emotions.is_doa_suppressed()
                    ):
                        sample = (float(doa[0]), 0.02)
                        command_doa_samples.append(sample)
                        stability_doa_samples.append(sample)
                        live_command_doa_samples.append(sample)
                except Exception as e:
                    print(f"⚠️ Command direction read error: {e}")

            now = time.time()

            if chunk_rms >= ACTIVE_RMS_THRESHOLD:
                if last_active_time is None:
                    if VERBOSE_RUNTIME_LOGS:
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
                        finish_command_direction()
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

                if VERBOSE_RUNTIME_LOGS:
                    print("🛑 Command ended after silence")
                break

            if now - start_time >= MAX_COMMAND_TIME:
                print(
                    "⚠️ Maximum command time reached — "
                    "discarding timed-out audio"
                )
                finish_command_direction()
                return None

        if not frames:
            return None

        finish_command_direction()
        return np.concatenate(frames, axis=0).astype(np.float32, copy=False)

    if ENABLE_SOUND_GAZE and not ENABLE_FACE_MOTION_DIAGNOSTIC:
        if SOUND_GAZE_TEST_MODE:
            robot_emotions.set_external_gaze(
                90.0,
                SOUND_GAZE_VERTICAL_POSITION,
            )
            print("👀 Sound-gaze test ready: eyes held at center")
        else:
            robot_emotions.clear_external_gaze()

    print("\n👂 Listening for wake words...\n")

    stream = open_microphone()

    try:
        while True:
            # Run wake-word inference once per fresh microphone block. Without
            # this gate the loop repeatedly infers on identical audio and can
            # starve PortAudio's Python callback, causing input overflows.
            if not audio_ready.wait(timeout=0.25):
                continue
            audio_ready.clear()

            current_time = time.time()

            # =========================
            # SLEEP CHECK
            # =========================

            if (
                not ENABLE_FACE_MOTION_DIAGNOSTIC
                and not sleeping
                and current_time - last_activity_time > SLEEP_TIMEOUT
            ):
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
                if current_time - last_respeaker_error_at >= (
                    RESPEAKER_ERROR_LOG_INTERVAL_SECONDS
                ):
                    print(f"⚠️ ReSpeaker VAD unavailable: {e}")
                    last_respeaker_error_at = current_time

                if current_time >= next_respeaker_reconnect_at:
                    next_respeaker_reconnect_at = (
                        current_time + RESPEAKER_RECONNECT_INTERVAL_SECONDS
                    )
                    try:
                        mic = create_respeaker_or_raise()
                        print("✅ ReSpeaker control interface reconnected")
                        last_respeaker_error_at = 0.0
                    except Exception:
                        pass

            # Always run OpenWakeWord, even if the ReSpeaker VAD
            # does not recognize quiet speech.
            audio_int16 = np.clip(
                audio_buffer * 32767,
                -32768,
                32767,
            ).astype(np.int16)

            rms = float(np.sqrt(np.mean(audio_buffer**2)))

            if (
                ENABLE_SOUND_GAZE
                and not ENABLE_FACE_MOTION_DIAGNOSTIC
                and not sleeping
            ):
                if robot_emotions.is_sound_gaze_suppressed():
                    ambient_gaze_angles.clear()
                    ambient_last_speech_at = None
                elif (
                    angle is not None
                    and speech
                    and rms >= SOUND_GAZE_AMBIENT_MIN_RMS
                ):
                    ambient_gaze_angles.append(float(angle))
                    ambient_last_speech_at = current_time

                    active_seconds = (
                        len(ambient_gaze_angles)
                        * HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
                    )
                    if (
                        active_seconds >= SOUND_GAZE_AMBIENT_MIN_SPEECH_SECONDS
                        and current_time >= ambient_cooldown_until
                        and not pending_wake
                    ):
                        if _look_toward_wake_sound(
                            list(ambient_gaze_angles),
                            list(ambient_gaze_angles),
                        ):
                            ambient_gaze_until = (
                                current_time + SOUND_GAZE_AMBIENT_HOLD_SECONDS
                            )
                            ambient_cooldown_until = (
                                current_time + SOUND_GAZE_AMBIENT_COOLDOWN_SECONDS
                            )
                            ambient_gaze_angles.clear()

                elif (
                    ambient_last_speech_at is not None
                    and current_time - ambient_last_speech_at
                    >= SOUND_GAZE_AMBIENT_RESET_SILENCE_SECONDS
                ):
                    ambient_gaze_angles.clear()
                    ambient_last_speech_at = None

                if ambient_gaze_until and current_time >= ambient_gaze_until:
                    if SOUND_GAZE_TEST_MODE:
                        robot_emotions.set_external_gaze(
                            90.0,
                            SOUND_GAZE_VERTICAL_POSITION,
                        )
                    else:
                        robot_emotions.clear_external_gaze()
                    ambient_gaze_until = 0.0

            if (
                (
                    head_tracker is not None
                    or ENABLE_DOA_DIAGNOSTIC
                    or ENABLE_SOUND_GAZE
                )
                and angle is not None
                and speech
                and rms >= ACTIVE_RMS_THRESHOLD
                and not robot_emotions.is_doa_suppressed()
            ):
                wake_direction_history.append(float(angle))

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

            if VERBOSE_RUNTIME_LOGS and (peak_score > 0.05 or stop_score > 0.05):
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
                _last_wake_detected_at = time.monotonic()

            # Confirm the pending detection.
            if pending_wake:
                # Keep the pending phrase updated with the freshest frame.
                pending_phrase = detected_phrase

                if current_time - pending_wake_time >= WAKE_CONFIRM_DELAY:
                    pending_wake = False
                    armed = False
                    history.clear()
                    if ENABLE_SOUND_GAZE:
                        # Ambient eye glances end when an interaction begins;
                        # qualified wake/command direction belongs to the head.
                        robot_emotions.clear_external_gaze()
                    if sleeping:
                        wake_up()
                        sleeping = False

                    if not ENABLE_FACE_MOTION_DIAGNOSTIC:
                        robot_emotions.set_emotion(EMOTION_LISTENING)

                    last_activity_time = current_time

                    phrase = handle_wake_word(pending_phrase)

                    # Use different capture and trim values for the short and long wake phrases.
                    if phrase == "hey ezra":
                        post_wake_audio_seconds = POST_WAKE_AUDIO_SECONDS_HEY_EZRA
                        wake_tail_trim_seconds = WAKE_TAIL_TRIM_SECONDS_HEY_EZRA
                    else:
                        post_wake_audio_seconds = POST_WAKE_AUDIO_SECONDS_EZRA
                        wake_tail_trim_seconds = WAKE_TAIL_TRIM_SECONDS_EZRA

                    # The XVF3800 bearing/LED settles just after the wake phrase
                    # ends. Preserve those final readings instead of freezing
                    # the earlier angle from the model-detection instant.
                    post_wake_started_at = time.monotonic()
                    active_wake_angles = list(wake_direction_history)
                    settled_wake_angles = []
                    settle_until = post_wake_started_at + min(
                        HEAD_TRACKING_WAKE_SETTLE_SECONDS,
                        post_wake_audio_seconds,
                    )
                    while time.monotonic() < settle_until:
                        try:
                            doa = mic.read("DOA_VALUE")
                            if len(doa) != 2:
                                raise RuntimeError(
                                    "Expected (angle, speech) DOA_VALUE response, "
                                    f"received: {doa!r}"
                                )
                            # The XVF3800 LED/bearing commonly settles just
                            # after VAD turns off. Preserve that final bearing
                            # while also extending active speech evidence.
                            if not robot_emotions.is_doa_suppressed():
                                settled_wake_angles.append(float(doa[0]))
                            if (
                                bool(doa[1])
                                and not robot_emotions.is_doa_suppressed()
                            ):
                                active_wake_angles.append(float(doa[0]))
                        except Exception as e:
                            print(f"⚠️ Wake direction settle error: {e}")
                        time.sleep(HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS)

                    if (
                        head_tracker is not None
                        and not ENABLE_DOA_DIAGNOSTIC
                        and not (return_audio and CONTINUOUS_CAPTURE_AFTER_WAKE)
                    ):
                        try:
                            head_tracker.turn_toward_wake(
                                active_wake_angles + settled_wake_angles
                            )
                        except Exception as e:
                            print(f"⚠️ Head tracking movement error: {e}")

                    post_wake_until = (
                        post_wake_started_at + post_wake_audio_seconds
                    )
                    while time.monotonic() < post_wake_until:
                        try:
                            doa = mic.read("DOA_VALUE")
                            if len(doa) != 2:
                                raise RuntimeError(
                                    "Expected (angle, speech) DOA_VALUE response, "
                                    f"received: {doa!r}"
                                )
                            if (
                                bool(doa[1])
                                and not robot_emotions.is_doa_suppressed()
                            ):
                                settled_wake_angles.append(float(doa[0]))
                                active_wake_angles.append(float(doa[0]))
                        except Exception as e:
                            print(f"⚠️ Post-wake direction read error: {e}")
                        time.sleep(HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS)

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
                        if VERBOSE_RUNTIME_LOGS:
                            print(
                                f"✂️ Trimmed {wake_tail_trim_seconds:.2f} sec "
                                "from wake handoff"
                            )

                    if VERBOSE_RUNTIME_LOGS:
                        print(
                            f"📼 Captured {len(wake_audio)/SAMPLE_RATE:.2f} sec "
                            "of post-wake audio"
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
                            command_audio = capture_command_same_stream(
                                wake_audio,
                                active_wake_angles,
                                settled_wake_angles,
                            )
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
            # Abort instead of draining the live input stream. A graceful
            # PortAudio stop can block after a command-capture timeout.
            stream.abort()
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
