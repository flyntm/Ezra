"""Test ReSpeaker direction-of-arrival tracking with Ezra's head servo.

Stop main.py before running this test. Speak briefly from different positions;
Ezra samples the bearing, then turns after a stable voice detection. Press
Ctrl+C to stop and return the head to center.
"""

import math
import os
import select
import sys
import termios
import time
import tty

import numpy as np
import sounddevice as sd

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from respeaker_io import create_respeaker_or_raise
from config import (
    LISTEN_ACTIVE_RMS_THRESHOLD,
    LISTEN_BLOCKSIZE,
    LISTEN_CHANNELS,
    LISTEN_MIC_DEVICE,
    LISTEN_SAMPLE_RATE,
)
from robot import calibration, servos
from robot.constants import CH_HEAD_TURN

# Match the head convention: negative is left and positive is right.
DOA_DIRECTION = 1.0
# This installed ReSpeaker reports its front-center LED near 180 degrees.
MIC_FORWARD_AZIMUTH = 180.0

HEAD_YAW_LIMIT = 90.0
SAMPLE_INTERVAL_SECONDS = 0.05
MIN_SPEECH_SECONDS = 0.6
MIN_SPEECH_SAMPLES = math.ceil(MIN_SPEECH_SECONDS / SAMPLE_INTERVAL_SECONDS)
MIN_CONTINUOUS_SPEECH_SECONDS = 0.2
MIN_CONTINUOUS_SPEECH_SAMPLES = math.ceil(
    MIN_CONTINUOUS_SPEECH_SECONDS / SAMPLE_INTERVAL_SECONDS
)
DOA_AVERAGE_SECONDS = 0.25
DOA_AVERAGE_SAMPLES = math.ceil(DOA_AVERAGE_SECONDS / SAMPLE_INTERVAL_SECONDS)
POST_SPEECH_SETTLE_SECONDS = 0.5
HEAD_CENTER_DEADBAND_DEGREES = 8.0
MAX_TRACKABLE_DOA_DEGREES = 90.0
MIN_ACTIVE_AUDIO_SECONDS = 0.4
MIN_ACTIVE_AUDIO_SAMPLES = math.ceil(
    MIN_ACTIVE_AUDIO_SECONDS / SAMPLE_INTERVAL_SECONDS
)
HEAD_STEP_DEGREES = 2.0
HEAD_STEP_DELAY_SECONDS = 0.035

MANUAL_HEAD_POSITIONS = {
    "c": ("center", 0.0),
    "l": ("left", -45.0),
    "r": ("right", 45.0),
}


def clamp(value, low, high):
    return max(low, min(high, value))


def signed_bearing(angle):
    """Convert a 0..360 mic azimuth to signed degrees from the mic's front."""
    relative = (float(angle) - MIC_FORWARD_AZIMUTH + 180.0) % 360.0 - 180.0
    return DOA_DIRECTION * relative


def circular_mean_degrees(angles):
    """Average bearings correctly across the -180/180 boundary."""
    sin_sum = sum(math.sin(math.radians(angle)) for angle in angles)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in angles)
    return math.degrees(math.atan2(sin_sum, cos_sum))


def yaw_to_servo(yaw, head_cal):
    """Map conceptual head yaw to the calibrated asymmetric servo endpoints."""
    yaw = clamp(float(yaw), -HEAD_YAW_LIMIT, HEAD_YAW_LIMIT)
    center = float(head_cal["center"])

    if yaw >= 0.0:
        # Positive yaw is right.
        endpoint = float(head_cal["right"])
        fraction = yaw / HEAD_YAW_LIMIT
    else:
        endpoint = float(head_cal["left"])
        fraction = -yaw / HEAD_YAW_LIMIT

    return center + ((endpoint - center) * fraction)


def move_head_smooth(current_yaw, target_yaw, head_cal):
    """Move at a controlled speed and return the reached conceptual yaw."""
    target_yaw = clamp(target_yaw, -HEAD_YAW_LIMIT, HEAD_YAW_LIMIT)
    distance = target_yaw - current_yaw
    steps = max(1, math.ceil(abs(distance) / HEAD_STEP_DEGREES))

    for step in range(1, steps + 1):
        yaw = current_yaw + distance * (step / steps)
        servos.set_servo_angle(CH_HEAD_TURN, yaw_to_servo(yaw, head_cal))
        time.sleep(HEAD_STEP_DELAY_SECONDS)

    return target_yaw


def read_doa(mic):
    """Return (angle, speech) from the project's XVF3800 control wrapper."""
    values = mic.read("DOA_VALUE")

    if len(values) != 2:
        raise RuntimeError(
            f"Expected (angle, speech) DOA_VALUE response, received: {values!r}"
        )

    return float(values[0]), bool(values[1])


def read_key_nonblocking():
    """Return one available keyboard character without pausing DoA sampling."""
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return None
    return sys.stdin.read(1).lower()


def main():
    mic = create_respeaker_or_raise()
    cal = calibration.load_cal()
    head_cal = cal["head"]

    if not servos.init():
        raise RuntimeError("Could not initialize the head servo controller")

    current_yaw = 0.0
    servos.set_servo_angle(CH_HEAD_TURN, yaw_to_servo(current_yaw, head_cal))

    print("\n=== Ezra ReSpeaker Head-Tracking Test ===")
    print("Stop main.py before using this test.")
    print("Head centered. Speak briefly from one position at a time.")
    print("The head will turn after you finish speaking and the DoA has settled.")
    print("Head positions: -90 deg = left, 0 deg = center, +90 deg = right.")
    print("Movement direction is printed separately from its 0..180 deg size.")
    print("Manual head positions: C = center, L = 45 deg left, R = 45 deg right.")
    print("Press Ctrl+C to stop and return the head to center.\n")
    print(
        "Calibration: "
        f"left={head_cal['left']}, center={head_cal['center']}, "
        f"right={head_cal['right']}"
    )

    samples = []
    speech_sample_count = 0
    consecutive_speech_samples = 0
    max_consecutive_speech_samples = 0
    active_audio_samples = 0
    tracking_this_utterance = False
    silence_started_at = None
    terminal_settings = None

    if sys.stdin.isatty():
        terminal_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    audio_state = {"rms": 0.0}

    def audio_callback(indata, frames, time_info, status):
        audio_state["rms"] = float(np.sqrt(np.mean(indata**2))) if indata.size else 0.0

    audio_stream = sd.InputStream(
        device=LISTEN_MIC_DEVICE,
        samplerate=LISTEN_SAMPLE_RATE,
        channels=LISTEN_CHANNELS,
        dtype="float32",
        callback=audio_callback,
        blocksize=LISTEN_BLOCKSIZE,
    )
    audio_stream.start()

    try:
        while True:
            key = read_key_nonblocking() if terminal_settings is not None else None
            if key in MANUAL_HEAD_POSITIONS:
                position_name, target_yaw = MANUAL_HEAD_POSITIONS[key]
                print(
                    f"\nManual position: {position_name} "
                    f"({target_yaw:+.1f} deg)"
                )
                current_yaw = move_head_smooth(current_yaw, target_yaw, head_cal)
                samples.clear()
                speech_sample_count = 0
                consecutive_speech_samples = 0
                max_consecutive_speech_samples = 0
                active_audio_samples = 0
                tracking_this_utterance = False
                silence_started_at = None
                print("Ready for voice direction or another C/L/R command.\n")

            raw_angle, respeaker_speech = read_doa(mic)
            active_audio = audio_state["rms"] >= LISTEN_ACTIVE_RMS_THRESHOLD
            # The ReSpeaker VAD can occasionally assert in a quiet room. Only
            # treat a sample as speech when the capture stream independently
            # confirms that audible energy is present at the same moment.
            speech = respeaker_speech and active_audio

            if speech:
                active_audio_samples += 1

            if speech:
                if silence_started_at is not None:
                    if tracking_this_utterance:
                        speech_sample_count = 0
                        consecutive_speech_samples = 0
                        max_consecutive_speech_samples = 0
                        active_audio_samples = 0
                    tracking_this_utterance = False
                silence_started_at = None

                if not tracking_this_utterance:
                    relative = signed_bearing(raw_angle)
                    samples.append(relative)
                    speech_sample_count += 1
                    consecutive_speech_samples += 1
                    max_consecutive_speech_samples = max(
                        max_consecutive_speech_samples,
                        consecutive_speech_samples,
                    )
                    print(
                        f"\rMeasured DoA: {relative:+6.1f} deg (-180..+180)  "
                        f"Voice samples: {speech_sample_count:2d}",
                        end="",
                        flush=True,
                    )
            else:
                consecutive_speech_samples = 0
                if silence_started_at is None:
                    silence_started_at = time.monotonic()
                if samples and not tracking_this_utterance:
                    # XVF3800 DoA can continue settling after VAD drops. Keep
                    # the post-speech bearings that drive the final LED.
                    samples.append(signed_bearing(raw_angle))

                if (
                    silence_started_at is not None
                    and time.monotonic() - silence_started_at
                    >= POST_SPEECH_SETTLE_SECONDS
                ):
                    if (
                        not tracking_this_utterance
                        and speech_sample_count >= MIN_SPEECH_SAMPLES
                        and max_consecutive_speech_samples
                        >= MIN_CONTINUOUS_SPEECH_SAMPLES
                        and active_audio_samples >= MIN_ACTIVE_AUDIO_SAMPLES
                    ):
                        # Turn only after the phrase ends, using the readings
                        # from when the ReSpeaker indication has settled.
                        settled_samples = samples[-DOA_AVERAGE_SAMPLES:]
                        correction = circular_mean_degrees(settled_samples)
                        if abs(correction) <= HEAD_CENTER_DEADBAND_DEGREES:
                            print(
                                "\n\nInitial head position: "
                                f"{current_yaw:+.1f} deg (-90..+90)\n"
                                "Measured ReSpeaker DoA: "
                                f"{correction:+.1f} deg (-180..+180)\n"
                                "Angle to be moved: "
                                f"{abs(correction):.1f} deg (0..180), "
                                "front center -- head stays put."
                            )
                            tracking_this_utterance = True
                            samples.clear()
                            speech_sample_count = 0
                            max_consecutive_speech_samples = 0
                            active_audio_samples = 0
                            print("Ready for the next voice direction.\n")
                            time.sleep(SAMPLE_INTERVAL_SECONDS)
                            continue

                        unclamped_target = current_yaw + correction
                        sound_is_behind = abs(correction) > MAX_TRACKABLE_DOA_DEGREES
                        target_is_unreachable = not (
                            -HEAD_YAW_LIMIT <= unclamped_target <= HEAD_YAW_LIMIT
                        )
                        if sound_is_behind or target_is_unreachable:
                            ignore_reason = (
                                "sound is behind the head"
                                if sound_is_behind
                                else "target is outside the head's range"
                            )
                            print(
                                "\n\nInitial head position: "
                                f"{current_yaw:+.1f} deg (-90..+90)\n"
                                "Measured ReSpeaker DoA: "
                                f"{correction:+.1f} deg (-180..+180)\n"
                                "Requested head target: "
                                f"{unclamped_target:+.1f} deg -- {ignore_reason}; "
                                "sound ignored."
                            )
                            tracking_this_utterance = True
                            samples.clear()
                            speech_sample_count = 0
                            max_consecutive_speech_samples = 0
                            active_audio_samples = 0
                            print("Ready for the next voice direction.\n")
                            time.sleep(SAMPLE_INTERVAL_SECONDS)
                            continue

                        target_yaw = unclamped_target
                        print(
                            "\n\nInitial head position: "
                            f"{current_yaw:+.1f} deg (-90..+90)\n"
                            "Measured ReSpeaker DoA: "
                            f"{correction:+.1f} deg (-180..+180)\n"
                            "Angle to be moved: "
                            f"{abs(correction):.1f} deg (0..180), "
                            f"direction={'right' if correction > 0 else 'left'}\n"
                            f"Final head target: {target_yaw:+.1f} deg (-90..+90)"
                        )
                        current_yaw = move_head_smooth(
                            current_yaw,
                            target_yaw,
                            head_cal,
                        )
                        tracking_this_utterance = True
                        samples.clear()
                        speech_sample_count = 0
                        max_consecutive_speech_samples = 0
                        active_audio_samples = 0
                        print("Ready for the next voice direction.\n")
                    elif not tracking_this_utterance and samples:
                        total_voice_seconds = (
                            speech_sample_count * SAMPLE_INTERVAL_SECONDS
                        )
                        longest_voice_seconds = (
                            max_consecutive_speech_samples * SAMPLE_INTERVAL_SECONDS
                        )
                        active_audio_seconds = active_audio_samples * SAMPLE_INTERVAL_SECONDS
                        print(
                            "Ignored non-speech/short sound: "
                            f"{total_voice_seconds:.2f}s total, "
                            f"{longest_voice_seconds:.2f}s longest continuous voice; "
                            f"need {MIN_SPEECH_SECONDS:.1f}s total and "
                            f"{MIN_CONTINUOUS_SPEECH_SECONDS:.2f}s continuous; "
                            f"real audio energy {active_audio_seconds:.2f}s "
                            f"(need {MIN_ACTIVE_AUDIO_SECONDS:.2f}s).\n"
                        )
                        samples.clear()
                        speech_sample_count = 0
                        max_consecutive_speech_samples = 0
                        active_audio_samples = 0

            time.sleep(SAMPLE_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nReturning head to center...")
    finally:
        audio_stream.stop()
        audio_stream.close()
        if terminal_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, terminal_settings)
        move_head_smooth(current_yaw, 0.0, head_cal)
        print("Test stopped.")


if __name__ == "__main__":
    main()
