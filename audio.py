import math
import queue
import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import (
    COMMAND_DOA_ACTIVE_CLUSTER_TOLERANCE_DEGREES,
    COMMAND_DOA_MAX_CIRCULAR_DEVIATION_DEGREES,
    COMMAND_DOA_MIN_ACTIVE_SPEECH_SECONDS,
    COMMAND_DOA_MIN_ACTIVE_CLUSTER_FRACTION,
    COMMAND_DOA_SETTLED_AGREEMENT_DEGREES,
    COMMAND_DOA_STABILITY_WINDOW_SECONDS,
    LISTEN_ACTIVE_RMS_THRESHOLD as ACTIVE_RMS_THRESHOLD,
    LISTEN_BLOCKSIZE as BLOCKSIZE,
    LISTEN_CHANNELS as CHANNELS,
    LISTEN_COMMAND_TIMEOUT as COMMAND_TIMEOUT,
    LISTEN_END_POST_ROLL_SECONDS as END_POST_ROLL_SECONDS,
    LISTEN_END_SILENCE as END_SILENCE,
    LISTEN_MAX_COMMAND_TIME as MAX_COMMAND_TIME,
    LISTEN_MIC_DEVICE as MIC_DEVICE,
    HEAD_TRACKING_DIRECTION,
    HEAD_TRACKING_MIC_FORWARD_AZIMUTH,
    HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS,
    LISTEN_PRE_ROLL_SECONDS,
    LISTEN_SAMPLE_RATE as SAMPLE_RATE,
    LISTEN_START_RMS_THRESHOLD as START_RMS_THRESHOLD,
    QUIET_STARTUP,
    VERBOSE_RUNTIME_LOGS,
)
from respeaker_io import create_respeaker_or_raise


# Most recently completed command bearing. This small diagnostic state keeps
# listen()'s existing return type unchanged for all current callers.
_last_command_doa = None


def get_last_command_doa():
    """Return the last command's signed DoA, or None when it was unavailable."""
    return _last_command_doa


def _mean_doa(raw_angles):
    """Average circular microphone angles and convert them to a signed bearing."""
    if not raw_angles:
        return None
    sin_sum = sum(math.sin(math.radians(angle)) for angle in raw_angles)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in raw_angles)
    raw_mean = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    relative = (
        raw_mean - HEAD_TRACKING_MIC_FORWARD_AZIMUTH + 180.0
    ) % 360.0 - 180.0
    return HEAD_TRACKING_DIRECTION * relative


def _qualified_command_doa(raw_angles):
    """Return a stable, speech-backed command bearing or None."""

    active_seconds = len(raw_angles) * HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
    if active_seconds < COMMAND_DOA_MIN_ACTIVE_SPEECH_SECONDS:
        return None

    window_samples = max(
        1,
        round(
            COMMAND_DOA_STABILITY_WINDOW_SECONDS
            / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
        ),
    )
    if len(raw_angles) < window_samples:
        return None

    active_bearings = [_mean_doa([angle]) for angle in raw_angles]
    dominant_cluster = max(
        (
            [
                bearing
                for bearing in active_bearings
                if abs((bearing - center + 180.0) % 360.0 - 180.0)
                <= COMMAND_DOA_ACTIVE_CLUSTER_TOLERANCE_DEGREES
            ]
            for center in active_bearings
        ),
        key=len,
    )
    if (
        len(dominant_cluster) / len(active_bearings)
        < COMMAND_DOA_MIN_ACTIVE_CLUSTER_FRACTION
    ):
        return None

    sin_sum = sum(math.sin(math.radians(angle)) for angle in dominant_cluster)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in dominant_cluster)
    active_bearing = math.degrees(math.atan2(sin_sum, cos_sum))

    for start in range(
        len(raw_angles) - window_samples,
        -1,
        -1,
    ):
        window = raw_angles[start : start + window_samples]
        bearing = _mean_doa(window)
        deviation = max(
            abs((_mean_doa([angle]) - bearing + 180.0) % 360.0 - 180.0)
            for angle in window
        )
        agreement = abs((bearing - active_bearing + 180.0) % 360.0 - 180.0)
        if (
            deviation <= COMMAND_DOA_MAX_CIRCULAR_DEVIATION_DEGREES
            and agreement <= COMMAND_DOA_SETTLED_AGREEMENT_DEGREES
        ):
            return bearing

    return None


# --------------------------------------------------
# RESPEAKER SETUP
# --------------------------------------------------

mic = create_respeaker_or_raise()

if not QUIET_STARTUP:
    print("✅ ReSpeaker hardware VAD ready")


# --------------------------------------------------
# LISTEN
# --------------------------------------------------


def listen(wake_audio=None, wake_text="EZRA"):
    """
    Listen for a command after wake-word detection using ReSpeaker hardware VAD.

    If wake_audio is provided, it is prepended so that speech beginning
    immediately after the wake word is retained.

    wake_text is used to adjust the tail-ignore window for the command
    capture path.
    """

    global _last_command_doa
    _last_command_doa = None

    from robot import robot_emotions

    print("👂 Listening for command (ReSpeaker VAD)...")

    frames = []
    command_doa_samples = []
    wake_audio_rms = 0.0

    if wake_audio is not None and len(wake_audio) > 0:
        wake_audio = np.asarray(wake_audio, dtype=np.float32)
        if wake_audio.ndim == 1:
            wake_audio = wake_audio.reshape(-1, 1)
        frames.append(wake_audio)
        wake_audio_rms = (
            float(np.sqrt(np.mean(wake_audio**2))) if wake_audio.size else 0.0
        )
        print(
            f"📼 Preserved {wake_audio.shape[0]/SAMPLE_RATE:.2f} sec of wake detection audio"
        )

    if frames:
        print(
            f"📼 Starting command capture with {frames[0].shape[0]/SAMPLE_RATE:.2f} sec of prebuffer audio"
        )

    start_time = time.time()
    command_started = wake_audio_rms >= START_RMS_THRESHOLD
    command_start_time = start_time if command_started else None
    last_active_time = start_time if command_started else None
    last_block_rms = 0.0
    last_vad_speech = None

    if command_started:
        print(f"🎤 Command primed from wake audio (rms={wake_audio_rms:.4f})")

    pre_roll_chunks = deque()
    pre_roll_samples = 0
    pre_roll_max_samples = int(LISTEN_PRE_ROLL_SECONDS * SAMPLE_RATE)

    if wake_audio is not None and len(wake_audio) > 0:
        wake_tail_ignore_seconds = 0.0
    else:
        wake_text = wake_text.upper() if wake_text else ""
        wake_tail_ignore_seconds = 0.20
        if wake_text == "EZRA":
            wake_tail_ignore_seconds = 0.10
        elif wake_text == "HEY EZRA":
            wake_tail_ignore_seconds = 0.25

    wake_tail_ignore_until = start_time + wake_tail_ignore_seconds
    wake_tail_ignored = wake_tail_ignore_seconds <= 0.0
    print(f"⏳ Wake-tail ignore window: {wake_tail_ignore_seconds:.2f} sec")

    audio_queue = queue.Queue()

    def audio_callback(indata, frames_count, time_info, status):
        audio_queue.put(indata.copy())

    with sd.InputStream(
        device=MIC_DEVICE,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_callback,
        blocksize=BLOCKSIZE,
    ):
        while True:
            # Collect available audio frames.
            while not audio_queue.empty():
                chunk = audio_queue.get()

                if command_started:
                    frames.append(chunk)
                else:
                    pre_roll_chunks.append(chunk)
                    pre_roll_samples += len(chunk)

                    while pre_roll_samples > pre_roll_max_samples and pre_roll_chunks:
                        removed = pre_roll_chunks.popleft()
                        pre_roll_samples -= len(removed)

                if chunk.size > 0:
                    last_block_rms = float(np.sqrt(np.mean(chunk**2)))

            # Check ReSpeaker hardware VAD.
            doa = mic.read("DOA_VALUE")
            if len(doa) != 2:
                raise RuntimeError(
                    f"Expected (angle, speech) DOA_VALUE response, received: {doa!r}"
                )
            vad_speech = bool(doa[1])
            angle = doa[0]

            # Keep only bearings supported by both hardware VAD and audible
            # command energy. Circular averaging avoids the 359°/0° boundary.
            if (
                command_started
                and vad_speech
                and last_block_rms >= ACTIVE_RMS_THRESHOLD
                and not robot_emotions.is_doa_suppressed()
            ):
                command_doa_samples.append(angle)

            # Debug: print VAD state changes
            if VERBOSE_RUNTIME_LOGS and (
                last_vad_speech is None or vad_speech != last_vad_speech
            ):
                if vad_speech:
                    print(f"🎤 VAD=ON (angle={angle})")
                else:
                    print(
                        f"🎤 VAD=OFF (silence_start candidate, rms={last_block_rms:.4f})"
                    )
                last_vad_speech = vad_speech

            # Ignore a brief wake-tail window so the prebuffer does not
            # immediately begin the command on the last syllable of "hey ezra".
            if not wake_tail_ignored and time.time() >= wake_tail_ignore_until:
                wake_tail_ignored = True
                print("⏳ Wake-tail ignore window ended")

            if not wake_tail_ignored:
                if time.time() - start_time >= COMMAND_TIMEOUT:
                    print("⚠️ No command speech detected within timeout")
                    break
                time.sleep(0.05)
                continue

            if not command_started:
                speech_now = last_block_rms >= START_RMS_THRESHOLD

                if speech_now:
                    command_started = True
                    command_start_time = time.time()
                    last_active_time = command_start_time

                    if pre_roll_chunks:
                        frames.extend(list(pre_roll_chunks))
                        pre_roll_chunks.clear()
                        pre_roll_samples = 0

                    print("🎤 Command speech detected")
                elif time.time() - start_time >= COMMAND_TIMEOUT:
                    print("⚠️ No command speech detected within timeout")
                    break
            else:
                # Drive end-of-command from signal energy so VAD flicker
                # does not keep resetting the silence timer.
                active_now = last_block_rms >= ACTIVE_RMS_THRESHOLD

                if active_now:
                    last_active_time = time.time()
                elif (
                    last_active_time is not None
                    and time.time() - last_active_time >= END_SILENCE
                ):
                    # Keep a short post-roll so trailing consonants are captured.
                    post_roll_until = time.time() + END_POST_ROLL_SECONDS

                    while time.time() < post_roll_until:
                        while not audio_queue.empty():
                            chunk = audio_queue.get()
                            frames.append(chunk)
                        time.sleep(0.01)

                    print("🛑 Command ended after silence")
                    break

            # Safety: max command time.
            if command_started and command_start_time is not None:
                if time.time() - command_start_time >= MAX_COMMAND_TIME:
                    print("⚠️ Maximum command time reached")
                    break
            elif time.time() - start_time >= COMMAND_TIMEOUT:
                print("⚠️ No command speech detected within timeout")
                break

            # Defensive fallback if state desyncs.
            if time.time() - start_time >= (COMMAND_TIMEOUT + MAX_COMMAND_TIME + 1.0):
                print("⚠️ Maximum command time reached")
                break

            time.sleep(0.05)

    # Convert frames to numpy array.
    if not frames:
        print("⚠️ No audio captured")
        return None

    audio = np.concatenate(frames, axis=0)

    # Ensure float32 format for STT.
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    duration = len(audio) / SAMPLE_RATE
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0

    if VERBOSE_RUNTIME_LOGS:
        print(f"Recording length: {duration:.2f} sec")
        print(f"Recording peak: {peak:.6f}")
        print(f"Recording RMS: {rms:.6f}")

    _last_command_doa = _qualified_command_doa(command_doa_samples)

    return audio
