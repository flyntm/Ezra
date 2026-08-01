# robot_emotions.py - reusable robot emotion controller

import colorsys
import math
import random
import threading
import time

from config import (
    EYELID_BLINK_STEPS,
    EYELID_BLINK_TRAVEL_SECONDS,
    MOUTH_LED_DEFAULT_HUE,
    MOUTH_LED_MODE_FROWN,
    MOUTH_LED_MODE_LISTENING,
    MOUTH_LED_MODE_SMILE,
    MOUTH_LED_MODE_TALK,
    MOUTH_LED_MODE_THINKING,
    MOUTH_LED_SELECTED_HUES,
    MOUTH_LED_TALK_FRAME_DELAY,
    MOUTH_LED_THINK_FULL_PAUSE,
    MOUTH_LED_THINK_STEP_DELAY,
)
from robot import animation
from robot import eyelids
from robot import eyes
from robot import servos
from robot import testmode
from robot.constants import CH_LID_LEFT, CH_LID_RIGHT

AVAILABLE_EMOTIONS = (
    "standby",
    "normal_talking",
    "listening",
    "happy",
    "sad",
    "surprised",
    "confused",
    "exasperated",
    "thinking",
    "wake",
)

EMOTION_ALIASES = {
    "idle": "standby",
    "sleeping": "standby",
    "normal": "normal_talking",
    "talking": "normal_talking",
    "talk": "normal_talking",
    "listen": "listening",
    "surprise": "surprised",
    "exasperate": "exasperated",
    "think": "thinking",
}

LISTENING_GAZE_CENTER = (90.0, 86.0)
LISTENING_MOTION_SCALE = 1.30
LISTENING_FIXATION_SECONDS = (
    0.8 / LISTENING_MOTION_SCALE,
    2.5 / LISTENING_MOTION_SCALE,
)
LISTENING_SACCADE_SECONDS = (0.08, 0.14)
STANDBY_GAZE_CENTER = (90.0, 86.0)
STANDBY_MOTION_SCALE = 1.30
STANDBY_FIXATION_SECONDS = (
    2.5 / STANDBY_MOTION_SCALE,
    6.0 / STANDBY_MOTION_SCALE,
)
STANDBY_SACCADE_SECONDS = (0.12, 0.22)


class RobotEmotionController:
    """Control the robot face with non-blocking emotion animations.

    Typical chatbot use:

        import robot_emotions

        robot_emotions.start()
        robot_emotions.set_emotion("listening")
        robot_emotions.set_emotion("normal_talking")
        robot_emotions.stop()
    """

    def __init__(self, tick_seconds=0.04):
        self.tick_seconds = tick_seconds
        self._emotion = "standby"
        self._running = False
        self._initialized = False
        self._thread = None
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._last_blink_at = 0.0
        self._next_blink_after = random.uniform(10.0, 18.0)
        self._next_mouth_frame = 0.0
        self._mouth_is_lit = False
        self._talk_frame_index = 0
        self._external_talk_level = None
        self._last_talk_shape = None
        self._thinking_count = 0
        self._thinking_full_until = 0.0
        self._temporary_until = 0.0
        self._temporary_fallback = None
        self._next_confused_shift = 0.0
        self._confused_side = -1
        self._exasperated_sigh_until = 0.0
        self._lid_open_amount = 1.0
        self._next_standby_gaze_at = 0.0
        self._next_listening_gaze_at = 0.0

    @property
    def emotion(self):
        with self._lock:
            return self._emotion

    def initialize(self):
        """Initialize servos, eyes, eyelids, and mouth LEDs."""
        with self._lock:
            if self._initialized:
                return True

            if not servos.init():
                return False

            eyelids.init()
            eyes.init()
            testmode.init_neopixel(silent=False)
            animation.reset()
            eyes.center()
            eyelids.open_lids()
            self._clear_mouth()
            self._initialized = True
            return True

    def start(self, initial_emotion="standby"):
        """Start the background animation loop."""
        if not self.initialize():
            return False

        with self._lock:
            self._emotion = _normalize_emotion(initial_emotion)
            self._external_talk_level = None
            self._last_talk_shape = None
            self._temporary_until = 0.0
            self._temporary_fallback = None
            self._apply_entry_pose_locked(self._emotion)

            if self._running:
                return True

            self._running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name="RobotEmotionController",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, clear_mouth=True, relax_servos=False):
        """Stop animation. Leave servos holding pose unless relax_servos is True."""
        thread = None
        with self._lock:
            self._running = False
            thread = self._thread
            self._thread = None

        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

        if clear_mouth:
            self._clear_mouth()

        if relax_servos:
            servos.shutdown()
            with self._lock:
                self._initialized = False

    def set_emotion(self, emotion):
        """Switch to an emotion by name. Safe to call from chatbot code."""
        emotion = _normalize_emotion(emotion)

        if not self._initialized:
            self.initialize()

        with self._lock:
            self._emotion = emotion
            self._started_at = time.time()
            self._next_mouth_frame = 0.0
            self._talk_frame_index = 0
            self._external_talk_level = None
            self._last_talk_shape = None
            self._thinking_count = 0
            self._thinking_full_until = 0.0
            self._temporary_until = 0.0
            self._temporary_fallback = None
            self._next_confused_shift = 0.0
            self._exasperated_sigh_until = 0.0
            self._next_standby_gaze_at = 0.0
            self._next_listening_gaze_at = 0.0
            self._apply_entry_pose_locked(emotion)

        return emotion

    def set_temporary_emotion(self, emotion, seconds, fallback_emotion="standby"):
        """Switch to an emotion briefly, then return to a fallback in the loop."""
        emotion = _normalize_emotion(emotion)
        fallback_emotion = _normalize_emotion(fallback_emotion)

        if not self._initialized:
            self.initialize()

        with self._lock:
            self._emotion = emotion
            self._started_at = time.time()
            self._next_mouth_frame = 0.0
            self._talk_frame_index = 0
            self._external_talk_level = None
            self._last_talk_shape = None
            self._thinking_count = 0
            self._thinking_full_until = 0.0
            self._temporary_until = time.time() + max(0.0, float(seconds))
            self._temporary_fallback = fallback_emotion
            self._next_confused_shift = 0.0
            self._exasperated_sigh_until = 0.0
            self._next_standby_gaze_at = 0.0
            self._next_listening_gaze_at = 0.0
            self._apply_entry_pose_locked(emotion)

        return emotion

    def set_talk_level(self, level):
        """Drive the talking mouth from an external normalized audio level."""
        with self._lock:
            if level is None:
                self._external_talk_level = None
            else:
                self._external_talk_level = max(0.0, min(1.0, float(level)))

    def speak(self):
        return self.set_emotion("normal_talking")

    def listen(self):
        return self.set_emotion("listening")

    def tick(self):
        """Advance the current emotion once.

        Use this instead of start() if another program already has its own loop.
        """
        if not self._initialized:
            self.initialize()

        with self._lock:
            emotion = self._emotion
            now = time.time()

            if self._temporary_until and now >= self._temporary_until:
                emotion = self._temporary_fallback or "standby"
                self._emotion = emotion
                self._started_at = now
                self._next_mouth_frame = 0.0
                self._talk_frame_index = 0
                self._external_talk_level = None
                self._last_talk_shape = None
                self._thinking_count = 0
                self._thinking_full_until = 0.0
                self._temporary_until = 0.0
                self._temporary_fallback = None
                self._next_standby_gaze_at = 0.0
                self._next_listening_gaze_at = 0.0
                self._apply_entry_pose_locked(emotion)

            t = now - self._started_at

            if emotion == "standby":
                self._tick_standby(now, t)
            elif emotion == "normal_talking":
                self._tick_normal_talking(now, t)
            elif emotion == "listening":
                self._tick_listening(now, t)
            elif emotion == "happy":
                self._tick_happy(now, t)
            elif emotion == "sad":
                self._tick_sad(now, t)
            elif emotion == "surprised":
                self._tick_surprised(now, t)
            elif emotion == "confused":
                self._tick_confused(now, t)
            elif emotion == "exasperated":
                self._tick_exasperated(now, t)
            elif emotion == "thinking":
                self._tick_thinking(now, t)
            elif emotion == "wake":
                pass  # 👈 HOLD the pose, no animation

    def _run_loop(self):
        while True:
            with self._lock:
                running = self._running
            if not running:
                break

            self.tick()
            time.sleep(self.tick_seconds)

    def _apply_entry_pose_locked(self, emotion):
        if emotion == "standby":
            self._set_lids(1.0)
            eyes.gaze_smooth(90, 86, steps=12, duration=0.12)
            self._clear_mouth()
        elif emotion == "normal_talking":
            self._set_lids(1.0)
            eyes.gaze_smooth(90, 90, steps=12, duration=0.12)
        elif emotion == "listening":
            self._set_lids(1.0)
            eyes.gaze_smooth(90, 86, steps=12, duration=0.12)
            self._mouth_listening()
        elif emotion == "happy":
            self._set_lids(0.96)
            eyes.gaze_smooth(90, 86, steps=14, duration=0.16)
            self._mouth_smile()
        elif emotion == "sad":
            self._set_lids(0.52)
            self._gaze_independent_smooth(90, 98, 90, 106, steps=18, duration=0.25)
            self._mouth_frown()
        elif emotion == "surprised":
            eyelids.wide_open_lids()
            eyes.gaze_smooth(90, 86, steps=10, duration=0.10)
            self._mouth_color((150, 150, 150))
        elif emotion == "confused":
            self._set_lids(0.82)
            self._gaze_independent_smooth(120, 98, 60, 98, steps=12, duration=0.14)
            self._mouth_color((70, 0, 95), width=4)
        elif emotion == "exasperated":
            eyelids.wide_open_lids()
            eyes.gaze_smooth(90, 64, steps=16, duration=0.22)
            self._mouth_color((120, 30, 0), width=5)
        elif emotion == "thinking":
            self._set_lids(0.90)
            eyes.gaze_smooth(90, 70, steps=14, duration=0.18)
            self._mouth_thinking_frame(1)
        elif emotion == "wake":
            eyes.center()
            self._set_lids(1.0)
            self._mouth_left_side((150, 150, 150), count=1)

    def _tick_standby(self, now, t):
        if now >= self._next_standby_gaze_at:
            h, v = self._choose_standby_gaze()
            eyes.gaze_smooth(
                h,
                v,
                steps=8,
                duration=random.uniform(*STANDBY_SACCADE_SECONDS),
            )
            self._next_standby_gaze_at = time.time() + random.uniform(
                *STANDBY_FIXATION_SECONDS
            )

        self._maybe_blink(now)
        self._clear_mouth()

    @staticmethod
    def _choose_standby_gaze():
        """Choose a calm fixation that stays connected to the person ahead."""
        center_h, center_v = STANDBY_GAZE_CENTER
        choice = random.random()

        if choice < 0.25:
            return center_h, center_v

        if choice < 0.40:
            side = random.choice((-1.0, 1.0))
            return center_h + side * random.uniform(
                5.0 * STANDBY_MOTION_SCALE,
                8.0 * STANDBY_MOTION_SCALE,
            ), center_v + random.uniform(
                -2.0 * STANDBY_MOTION_SCALE,
                2.0 * STANDBY_MOTION_SCALE,
            )

        h_limit = 4.0 * STANDBY_MOTION_SCALE
        v_limit = 2.0 * STANDBY_MOTION_SCALE
        h_offset = max(
            -h_limit,
            min(h_limit, random.gauss(0.0, 1.8 * STANDBY_MOTION_SCALE)),
        )
        v_offset = max(
            -v_limit,
            min(v_limit, random.gauss(0.0, 0.9 * STANDBY_MOTION_SCALE)),
        )
        return center_h + h_offset, center_v + v_offset

    def _tick_normal_talking(self, now, t):
        h = 90 + 7 * math.sin(t * 0.55)
        v = 90 + 3 * math.sin(t * 0.8)
        eyes.gaze(h, v)
        self._maybe_blink(now)
        if self._external_talk_level is None:
            self._mouth_talk_frame(now)
        else:
            self._mouth_talk_level(self._external_talk_level)

    def _tick_listening(self, now, t):
        if now >= self._next_listening_gaze_at:
            h, v = self._choose_listening_gaze()
            eyes.gaze_smooth(
                h,
                v,
                steps=6,
                duration=random.uniform(*LISTENING_SACCADE_SECONDS),
            )
            self._next_listening_gaze_at = time.time() + random.uniform(
                *LISTENING_FIXATION_SECONDS
            )

        self._maybe_blink(now)
        self._mouth_listening()

    @staticmethod
    def _choose_listening_gaze():
        """Choose an attentive fixation, favoring small shifts near center."""
        center_h, center_v = LISTENING_GAZE_CENTER
        choice = random.random()

        if choice < 0.10:
            # Periodically reconnect with the person directly ahead.
            return center_h + random.uniform(
                -1.0 * LISTENING_MOTION_SCALE,
                1.0 * LISTENING_MOTION_SCALE,
            ), center_v + random.uniform(
                -1.0 * LISTENING_MOTION_SCALE,
                1.0 * LISTENING_MOTION_SCALE,
            )

        if choice < 0.30:
            # An occasional brief glance gives the eyes some personality.
            side = random.choice((-1.0, 1.0))
            return center_h + side * random.uniform(
                8.0 * LISTENING_MOTION_SCALE,
                12.0 * LISTENING_MOTION_SCALE,
            ), center_v + random.uniform(
                -3.0 * LISTENING_MOTION_SCALE,
                3.0 * LISTENING_MOTION_SCALE,
            )

        # Most movements are subtle and remain focused near the listener.
        h_limit = 6.0 * LISTENING_MOTION_SCALE
        v_limit = 3.0 * LISTENING_MOTION_SCALE
        h_offset = max(
            -h_limit,
            min(h_limit, random.gauss(0.0, 2.8 * LISTENING_MOTION_SCALE)),
        )
        v_offset = max(
            -v_limit,
            min(v_limit, random.gauss(0.0, 1.4 * LISTENING_MOTION_SCALE)),
        )
        return center_h + h_offset, center_v + v_offset

    def _tick_happy(self, now, t):
        h = 90 + 9 * math.sin(t * 1.1)
        v = 86 + 3 * math.sin(t * 1.7)
        eyes.gaze(h, v)
        self._set_lids(0.92 + 0.04 * math.sin(t * 2.2))
        self._maybe_blink(now, every=(9.0, 16.0))
        self._mouth_smile()

    def _tick_sad(self, now, t):
        h = 90 + 3 * math.sin(t * 0.22)
        left_v = 98 + 2 * math.sin(t * 0.3)
        right_v = 106 + 2 * math.sin(t * 0.3)
        self._gaze_independent(h, left_v, h, right_v)
        self._set_lids(0.50 + 0.04 * math.sin(t * 0.6))
        self._maybe_blink(now, every=(11.0, 20.0), closed_seconds=0.30)
        self._mouth_frown()

    def _tick_surprised(self, now, t):
        h = 90 + 2 * math.sin(t * 2.4)
        v = 86 + 2 * math.sin(t * 2.0)
        eyes.gaze(h, v)
        eyelids.wide_open_lids()
        if now >= self._next_mouth_frame:
            level = random.randint(95, 165)
            self._mouth_color((level, level, level), width=8)
            self._next_mouth_frame = now + 0.16

    def _tick_confused(self, now, t):
        wobble = 3 * math.sin(t * 1.7)
        self._gaze_independent(120 - wobble, 98, 60 + wobble, 98)
        self._set_lids(0.78 + 0.06 * math.sin(t * 1.4))
        self._maybe_blink(now, every=(10.0, 17.0))
        if now >= self._next_mouth_frame:
            width = random.choice((3, 4, 5))
            self._mouth_color((65, 0, 90), width=width)
            self._next_mouth_frame = now + 0.35

    def _tick_exasperated(self, now, t):
        roll = (t * 1.15) % (2 * math.pi)
        h = 90 + 18 * math.sin(roll)
        v = 74 - 10 * math.cos(roll)
        eyes.gaze(h, v)
        eyelids.wide_open_lids()
        if now >= self._next_mouth_frame:
            self._mouth_color((115, 22, 0), width=random.choice((2, 3, 4)))
            self._next_mouth_frame = now + 0.20

    def _tick_thinking(self, now, t):
        h = 90 + 4 * math.sin(t * 0.45)
        v = 70 + 2 * math.sin(t * 0.55)
        eyes.gaze(h, v)
        self._set_lids(0.90)
        self._maybe_blink(now, every=(10.0, 18.0))
        self._tick_mouth_thinking(now)

    def _maybe_blink(self, now, every=(12.0, 18.0), closed_seconds=0.3):
        if self._last_blink_at == 0.0:
            self._last_blink_at = now

        if now - self._last_blink_at < self._next_blink_after:
            return

        open_amount = self._lid_open_amount
        self._move_lids_smooth(open_amount, 0.0)
        time.sleep(closed_seconds)

        self._move_lids_smooth(0.0, self._lid_amount_for_emotion(self._emotion))

        self._last_blink_at = time.time()
        self._next_blink_after = random.uniform(*every)

    @staticmethod
    def _lid_amount_for_emotion(emotion):
        return {
            "happy": 0.96,
            "sad": 0.52,
            "confused": 0.82,
            "thinking": 0.90,
        }.get(emotion, 1.0)

    def _move_lids_smooth(self, start, end):
        """Ease the eyelids between positions in the animation thread."""
        steps = max(1, int(EYELID_BLINK_STEPS))
        step_delay = max(0.0, float(EYELID_BLINK_TRAVEL_SECONDS)) / steps

        for step in range(1, steps + 1):
            progress = step / steps
            eased = progress * progress * (3.0 - (2.0 * progress))
            self._set_lids(start + ((end - start) * eased))
            if step < steps and step_delay:
                time.sleep(step_delay)

    def _set_lids(self, open_amount):
        cal = eyelids.CAL
        open_amount = max(0.0, min(1.2, float(open_amount)))

        def angle_for(key):
            low = cal["servos"][key]["low"]
            high = cal["servos"][key]["high"]
            wide = cal["servos"][key].get("wide_open", high)
            if open_amount <= 1.0:
                return low + ((high - low) * open_amount)
            return high + ((wide - high) * (open_amount - 1.0) / 0.2)

        def set_if_changed(channel, new_angle, key):
            last = getattr(self, f"_last_{key}", None)
            if last is None or abs(last - new_angle) > 1.0:
                servos.set_servo_angle(channel, new_angle)
                setattr(self, f"_last_{key}", new_angle)

        set_if_changed(CH_LID_LEFT, angle_for("lid_l"), "lid_l")
        set_if_changed(CH_LID_RIGHT, angle_for("lid_r"), "lid_r")
        self._lid_open_amount = open_amount

    def _gaze_independent(self, left_h, left_v, right_h, right_v):
        left_targets = eyes._gaze_targets(left_h, left_v)
        right_targets = eyes._gaze_targets(right_h, right_v)
        eyes.look(left_targets[0], left_targets[1], right_targets[2], right_targets[3])

    def _gaze_independent_smooth(
        self, left_h, left_v, right_h, right_v, steps=12, duration=0.12
    ):
        left_targets = eyes._gaze_targets(left_h, left_v)
        right_targets = eyes._gaze_targets(right_h, right_v)
        eyes.look_smooth(
            left_targets[0],
            left_targets[1],
            right_targets[2],
            right_targets[3],
            steps=steps,
            duration=duration,
        )

    def _mouth_talk_frame(self, now):
        if now < self._next_mouth_frame:
            return

        frames = (
            [
                [0, 0, 0, 0, 0, 0, 0, 0],
                [1, 1, 1, 1, 1, 1, 1, 1],
                [0, 1, 1, 1, 1, 1, 1, 0],
            ],
            [
                [0, 1, 1, 1, 1, 1, 1, 0],
                [1, 0, 0, 0, 0, 0, 0, 1],
                [0, 1, 1, 1, 1, 1, 1, 0],
            ],
        )
        self._show_mouth_pattern(
            frames[self._talk_frame_index % len(frames)],
            self._mouth_mode_color(MOUTH_LED_MODE_TALK),
        )
        self._talk_frame_index += 1
        self._next_mouth_frame = now + MOUTH_LED_TALK_FRAME_DELAY

    def _mouth_talk_level(self, level):
        """Render one of four mouth openings from a normalized audio level."""
        if level < 0.10:
            shape = 0
        elif level < 0.38:
            shape = 1
        elif level < 0.72:
            shape = 2
        else:
            shape = 3

        if shape == self._last_talk_shape:
            return

        patterns = (
            [
                [0, 0, 0, 0, 0, 0, 0, 0],
                [0, 1, 1, 1, 1, 1, 1, 0],
                [0, 0, 0, 0, 0, 0, 0, 0],
            ],
            [
                [0, 0, 0, 0, 0, 0, 0, 0],
                [1, 1, 1, 1, 1, 1, 1, 1],
                [0, 0, 0, 0, 0, 0, 0, 0],
            ],
            [
                [0, 0, 1, 1, 1, 1, 0, 0],
                [1, 1, 0, 0, 0, 0, 1, 1],
                [0, 0, 1, 1, 1, 1, 0, 0],
            ],
            [
                [0, 1, 1, 1, 1, 1, 1, 0],
                [1, 0, 0, 0, 0, 0, 0, 1],
                [0, 1, 1, 1, 1, 1, 1, 0],
            ],
        )
        self._show_mouth_pattern(
            patterns[shape],
            self._mouth_mode_color(MOUTH_LED_MODE_TALK),
        )
        self._last_talk_shape = shape

    def _mouth_smile(self):
        self._show_mouth_pattern(
            [
                [1, 0, 0, 0, 0, 0, 0, 1],
                [0, 1, 0, 0, 0, 0, 1, 0],
                [0, 0, 1, 1, 1, 1, 0, 0],
            ],
            self._mouth_mode_color(MOUTH_LED_MODE_SMILE),
        )

    def _mouth_frown(self):
        self._show_mouth_pattern(
            [
                [0, 0, 1, 1, 1, 1, 0, 0],
                [0, 1, 0, 0, 0, 0, 1, 0],
                [1, 0, 0, 0, 0, 0, 0, 1],
            ],
            self._mouth_mode_color(MOUTH_LED_MODE_FROWN),
        )

    def _mouth_listening(self):
        self._show_mouth_pattern(
            [
                [0, 0, 0, 0, 0, 0, 0, 0],
                [1, 1, 0, 0, 0, 0, 0, 0],
                [0, 0, 0, 0, 0, 0, 0, 0],
            ],
            self._mouth_mode_color(MOUTH_LED_MODE_LISTENING),
        )

    def _tick_mouth_thinking(self, now):
        if now < self._thinking_full_until:
            return

        if now < self._next_mouth_frame:
            return

        self._thinking_count += 1
        if self._thinking_count > testmode.LEDS_PER_STRIP:
            self._thinking_count = 1

        self._mouth_thinking_frame(self._thinking_count)

        if self._thinking_count == testmode.LEDS_PER_STRIP:
            self._thinking_full_until = now + MOUTH_LED_THINK_FULL_PAUSE
            self._next_mouth_frame = self._thinking_full_until
        else:
            self._next_mouth_frame = now + MOUTH_LED_THINK_STEP_DELAY

    def _mouth_thinking_frame(self, count):
        count = max(0, min(testmode.LEDS_PER_STRIP, int(count)))
        self._show_mouth_pattern(
            [
                [0, 0, 0, 0, 0, 0, 0, 0],
                [
                    1 if i >= testmode.LEDS_PER_STRIP - count else 0
                    for i in range(testmode.LEDS_PER_STRIP)
                ],
                [0, 0, 0, 0, 0, 0, 0, 0],
            ],
            self._mouth_mode_color(MOUTH_LED_MODE_THINKING),
        )

    def _mouth_mode_color(self, mode):
        hue = int(MOUTH_LED_SELECTED_HUES.get(mode, MOUTH_LED_DEFAULT_HUE)) % 360
        h = hue / 360.0
        r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
        return int(r * 255), int(g * 255), int(b * 255)

    def _show_mouth_pattern(self, pattern, color):
        if not testmode.neopixel_ready or testmode.pixels is None:
            return

        testmode.pixels.fill((0, 0, 0))
        for row in range(min(testmode.LED_STRIP_COUNT, len(pattern))):
            for col in range(min(testmode.LEDS_PER_STRIP, len(pattern[row]))):
                if pattern[row][col]:
                    # Patterns are authored top-to-bottom, but the physical
                    # mouth strips are mounted bottom-to-top.
                    physical_row = testmode.LED_STRIP_COUNT - 1 - row
                    pixel_index = physical_row * testmode.LEDS_PER_STRIP + col
                    testmode.pixels[pixel_index] = color

        testmode.pixels_show()
        self._mouth_is_lit = True

    def _mouth_color(self, color, width=None):
        if not testmode.neopixel_ready or testmode.pixels is None:
            return

        if width is None:
            testmode.pixels.fill(color)
        else:
            width = max(0, min(testmode.LED_COUNT, int(width)))
            start = (testmode.LED_COUNT - width) // 2
            testmode.pixels.fill((0, 0, 0))
            for i in range(start, start + width):
                testmode.pixels[i] = color

        testmode.pixels_show()
        self._mouth_is_lit = color != (0, 0, 0)

    def _mouth_left_side(self, color, count=2):
        if not testmode.neopixel_ready or testmode.pixels is None:
            return

        count = max(0, min(testmode.LED_COUNT, int(count)))
        testmode.pixels.fill((0, 0, 0))
        for i in range(count):
            testmode.pixels[i] = color
        testmode.pixels_show()
        self._mouth_is_lit = count > 0

    def _clear_mouth(self):
        if not self._mouth_is_lit and not testmode.neopixel_ready:
            return

        if testmode.neopixel_ready and testmode.pixels is not None:
            testmode.pixels.fill((0, 0, 0))
            testmode.pixels_show()
        self._mouth_is_lit = False


def _normalize_emotion(emotion):
    key = str(emotion).strip().lower().replace("-", "_").replace(" ", "_")
    key = EMOTION_ALIASES.get(key, key)
    if key not in AVAILABLE_EMOTIONS:
        allowed = ", ".join(AVAILABLE_EMOTIONS)
        raise ValueError(f"Unknown emotion {emotion!r}. Choose one of: {allowed}")
    return key


_default_controller = RobotEmotionController()


def start(initial_emotion="standby"):
    return _default_controller.start(initial_emotion=initial_emotion)


def stop(clear_mouth=True, relax_servos=False):
    _default_controller.stop(clear_mouth=clear_mouth, relax_servos=relax_servos)


def set_emotion(emotion):
    return _default_controller.set_emotion(emotion)


def set_temporary_emotion(emotion, seconds, fallback_emotion="standby"):
    return _default_controller.set_temporary_emotion(
        emotion,
        seconds,
        fallback_emotion=fallback_emotion,
    )


def set_talk_level(level):
    return _default_controller.set_talk_level(level)


def speak():
    return _default_controller.speak()


def listen():
    return _default_controller.listen()


def tick():
    _default_controller.tick()
