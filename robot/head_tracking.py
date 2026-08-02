"""ReSpeaker direction-of-arrival tracking for Ezra's head servo."""

import math
import time

from config import (
    HEAD_TRACKING_AVERAGE_SECONDS,
    HEAD_TRACKING_CENTER_DEADBAND_DEGREES,
    HEAD_TRACKING_DIRECTION,
    HEAD_TRACKING_MAX_YAW_DEGREES,
    HEAD_TRACKING_MIC_FORWARD_AZIMUTH,
    HEAD_TRACKING_MIN_ACTIVE_AUDIO_SECONDS,
    HEAD_TRACKING_MIN_CONTINUOUS_SPEECH_SECONDS,
    HEAD_TRACKING_MIN_SPEECH_SECONDS,
    HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS,
    HEAD_TRACKING_STEP_DELAY_SECONDS,
    HEAD_TRACKING_STEP_DEGREES,
    LISTEN_ACTIVE_RMS_THRESHOLD,
)
from robot import calibration, servos
from robot.constants import CH_HEAD_TURN


def _clamp(value, low, high):
    return max(low, min(high, value))


def _signed_bearing(angle):
    relative = (
        float(angle) - HEAD_TRACKING_MIC_FORWARD_AZIMUTH + 180.0
    ) % 360.0 - 180.0
    return HEAD_TRACKING_DIRECTION * relative


def _circular_mean_degrees(angles):
    sin_sum = sum(math.sin(math.radians(angle)) for angle in angles)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in angles)
    return math.degrees(math.atan2(sin_sum, cos_sum))


class HeadTracker:
    """Collect synchronized speech/DoA samples and turn after an utterance."""

    def __init__(self):
        self._head_cal = calibration.load_cal()["head"]
        self._current_yaw = 0.0
        self.reset_utterance()

    def reset_utterance(self):
        self._samples = []
        self._speech_samples = 0
        self._consecutive_speech_samples = 0
        self._max_consecutive_speech_samples = 0
        self._active_audio_samples = 0

    @property
    def current_yaw(self):
        """Current logical head yaw in degrees for diagnostics."""
        return self._current_yaw

    def observe(self, raw_angle, respeaker_speech, rms):
        """Record one DoA sample synchronized with the capture stream's RMS."""
        active_audio = float(rms) >= LISTEN_ACTIVE_RMS_THRESHOLD
        speech = bool(respeaker_speech) and active_audio

        if speech:
            self._samples.append(_signed_bearing(raw_angle))
            self._speech_samples += 1
            self._consecutive_speech_samples += 1
            self._max_consecutive_speech_samples = max(
                self._max_consecutive_speech_samples,
                self._consecutive_speech_samples,
            )
            self._active_audio_samples += 1
        else:
            self._consecutive_speech_samples = 0
            if self._samples:
                # Preserve post-speech DoA readings while the XVF3800 bearing
                # settles to the final direction shown by its LED.
                self._samples.append(_signed_bearing(raw_angle))

    def finish_utterance(self):
        """Turn toward a qualifying utterance, then clear its sample state."""
        try:
            min_speech = math.ceil(
                HEAD_TRACKING_MIN_SPEECH_SECONDS
                / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
            )
            min_continuous = math.ceil(
                HEAD_TRACKING_MIN_CONTINUOUS_SPEECH_SECONDS
                / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
            )
            min_active = math.ceil(
                HEAD_TRACKING_MIN_ACTIVE_AUDIO_SECONDS
                / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
            )

            if (
                self._speech_samples < min_speech
                or self._max_consecutive_speech_samples < min_continuous
                or self._active_audio_samples < min_active
            ):
                return False

            average_samples = max(
                1,
                math.ceil(
                    HEAD_TRACKING_AVERAGE_SECONDS
                    / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
                ),
            )
            correction = _circular_mean_degrees(self._samples[-average_samples:])

            return self._turn_by_correction(correction, source="speaker")
        finally:
            self.reset_utterance()

    def turn_toward_wake(self, raw_angles):
        """Turn using only DoA samples retained from the confirmed wake word."""
        if not raw_angles:
            print("👂 No wake-word direction samples; head stays put")
            return False

        average_samples = max(
            1,
            math.ceil(
                HEAD_TRACKING_AVERAGE_SECONDS
                / HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS
            ),
        )
        bearings = [_signed_bearing(angle) for angle in raw_angles[-average_samples:]]
        correction = _circular_mean_degrees(bearings)
        return self._turn_by_correction(correction, source="wake word")

    def turn_toward_bearing(self, bearing, source="command"):
        """Apply an already normalized bearing as a relative correction."""
        return self._turn_by_correction(float(bearing), source=source)

    def _turn_by_correction(self, correction, source):
        if abs(correction) <= HEAD_TRACKING_CENTER_DEADBAND_DEGREES:
            print(
                f"👂 {source.capitalize()} direction {correction:+.1f}° is centered; "
                "head stays put"
            )
            return False

        requested_yaw = self._current_yaw + correction
        target_yaw = _clamp(
            requested_yaw,
            -HEAD_TRACKING_MAX_YAW_DEGREES,
            HEAD_TRACKING_MAX_YAW_DEGREES,
        )

        if target_yaw != requested_yaw:
            print(
                f"👂 Clamping unreachable {source} target "
                f"{requested_yaw:+.1f}° to {target_yaw:+.1f}°"
            )

        if abs(target_yaw - self._current_yaw) < 0.01:
            print(f"👂 Head already at {target_yaw:+.1f}° limit")
            return False

        print(
            f"👂 Turning toward {source}: {self._current_yaw:+.1f}° "
            f"→ {target_yaw:+.1f}°"
        )
        self._move_smooth(target_yaw)
        return True

    def center(self):
        """Return the head to its calibrated center when servos are available."""
        self.reset_utterance()
        if servos.pca is None:
            self._current_yaw = 0.0
            return
        self._move_smooth(0.0)

    def _yaw_to_servo(self, yaw):
        yaw = _clamp(
            float(yaw),
            -HEAD_TRACKING_MAX_YAW_DEGREES,
            HEAD_TRACKING_MAX_YAW_DEGREES,
        )
        center = float(self._head_cal["center"])

        if yaw >= 0.0:
            endpoint = float(self._head_cal["right"])
            fraction = yaw / HEAD_TRACKING_MAX_YAW_DEGREES
        else:
            endpoint = float(self._head_cal["left"])
            fraction = -yaw / HEAD_TRACKING_MAX_YAW_DEGREES

        return center + ((endpoint - center) * fraction)

    def _move_smooth(self, target_yaw):
        target_yaw = _clamp(
            target_yaw,
            -HEAD_TRACKING_MAX_YAW_DEGREES,
            HEAD_TRACKING_MAX_YAW_DEGREES,
        )
        distance = target_yaw - self._current_yaw
        steps = max(1, math.ceil(abs(distance) / HEAD_TRACKING_STEP_DEGREES))

        for step in range(1, steps + 1):
            yaw = self._current_yaw + distance * (step / steps)
            servos.set_servo_angle(CH_HEAD_TURN, self._yaw_to_servo(yaw))
            time.sleep(HEAD_TRACKING_STEP_DELAY_SECONDS)

        self._current_yaw = target_yaw


head_tracker = HeadTracker()
