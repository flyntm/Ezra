"""ReSpeaker direction-of-arrival tracking for Ezra's head servo."""

import math
import threading
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
    HEAD_MOVEMENT_STEP_DELAY_SECONDS,
    LISTEN_ACTIVE_RMS_THRESHOLD,
    VERBOSE_RUNTIME_LOGS,
)
from robot import calibration, servos
from robot.constants import CH_HEAD_TURN


# The public setting retains its original meaning: the time Ezra would take
# between 5-degree motion increments.  Internally, use much smaller increments
# so slower settings do not turn into visible 5-degree jumps.
_HEAD_MOVEMENT_SPEED_REFERENCE_DEGREES = 5.0
_HEAD_MOVEMENT_MAX_STEP_DEGREES = 1.0
_HEAD_MOVEMENT_UPDATE_INTERVAL_SECONDS = 0.02


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
        self._center_hold = False
        # Presentation movement runs in a background thread. Serialize every
        # head command so centering, speaker tracking, and audience motion can
        # never issue competing servo positions.
        self._motion_lock = threading.RLock()
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
            if VERBOSE_RUNTIME_LOGS:
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

    def turn_toward_bearing(
        self,
        bearing,
        source="command",
        step_delay_seconds=None,
        announce=True,
        stop_event=None,
    ):
        """Apply an already normalized bearing as a relative correction."""
        return self._turn_by_correction(
            float(bearing),
            source=source,
            step_delay_seconds=step_delay_seconds,
            announce=announce,
            stop_event=stop_event,
        )

    def set_center_hold(self, active):
        """Block audience turns while a scripted centered gesture is active."""
        with self._motion_lock:
            self._center_hold = bool(active)

    def _turn_by_correction(
        self,
        correction,
        source,
        step_delay_seconds=None,
        announce=True,
        stop_event=None,
    ):
        if self._center_hold:
            return False
        announce = announce and VERBOSE_RUNTIME_LOGS
        if abs(correction) <= HEAD_TRACKING_CENTER_DEADBAND_DEGREES:
            if announce:
                print(
                    f"👂 {source.capitalize()} direction {correction:+.1f}° "
                    "is centered; head stays put"
                )
            return False

        requested_yaw = self._current_yaw + correction
        target_yaw = _clamp(
            requested_yaw,
            -HEAD_TRACKING_MAX_YAW_DEGREES,
            HEAD_TRACKING_MAX_YAW_DEGREES,
        )

        if announce and target_yaw != requested_yaw:
            print(
                f"👂 Clamping unreachable {source} target "
                f"{requested_yaw:+.1f}° to {target_yaw:+.1f}°"
            )

        if abs(target_yaw - self._current_yaw) < 0.01:
            if announce:
                print(f"👂 Head already at {target_yaw:+.1f}° limit")
            return False

        if announce:
            print(
                f"👂 Turning toward {source}: {self._current_yaw:+.1f}° "
                f"→ {target_yaw:+.1f}°"
            )
        return self._move_smooth(
            target_yaw,
            step_delay_seconds=step_delay_seconds,
            stop_event=stop_event,
        )

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

    def _move_smooth(self, target_yaw, step_delay_seconds=None, stop_event=None):
        with self._motion_lock:
            target_yaw = _clamp(
                target_yaw,
                -HEAD_TRACKING_MAX_YAW_DEGREES,
                HEAD_TRACKING_MAX_YAW_DEGREES,
            )
            start_yaw = self._current_yaw
            distance = target_yaw - start_yaw
            speed_setting = (
                HEAD_MOVEMENT_STEP_DELAY_SECONDS
                if step_delay_seconds is None
                else max(0.0, float(step_delay_seconds))
            )
            duration = (
                abs(distance)
                * speed_setting
                / _HEAD_MOVEMENT_SPEED_REFERENCE_DEGREES
            )
            steps = max(
                1,
                math.ceil(abs(distance) / _HEAD_MOVEMENT_MAX_STEP_DEGREES),
                math.ceil(duration / _HEAD_MOVEMENT_UPDATE_INTERVAL_SECONDS),
            )
            step_delay = duration / steps

            for step in range(1, steps + 1):
                if stop_event is not None and stop_event.is_set():
                    return False

                progress = step / steps
                # Cosine easing reduces the abrupt acceleration and braking
                # that made occasional wide audience moves look like snaps.
                eased_progress = 0.5 - (0.5 * math.cos(math.pi * progress))
                yaw = start_yaw + distance * eased_progress
                servos.set_servo_angle(CH_HEAD_TURN, self._yaw_to_servo(yaw))
                self._current_yaw = yaw

                if stop_event is not None:
                    if stop_event.wait(step_delay):
                        return False
                else:
                    time.sleep(step_delay)

            self._current_yaw = target_yaw
            return True


head_tracker = HeadTracker()
