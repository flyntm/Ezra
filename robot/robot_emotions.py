# robot_emotions.py - reusable robot emotion controller

import math
import random
import threading
import time

from robot import animation
from robot import eyelids
from robot import eyes
from robot import servos
from robot import testmode
from robot.constants import CH_LID_LEFT, CH_LID_RIGHT


AVAILABLE_EMOTIONS = (
    "normal_talking",
    "listening",
    "happy",
    "sad",
    "surprised",
    "confused",
    "exasperated",
    "thinking",
)

EMOTION_ALIASES = {
    "normal": "normal_talking",
    "talking": "normal_talking",
    "talk": "normal_talking",
    "listen": "listening",
    "surprise": "surprised",
    "exasperate": "exasperated",
    "think": "thinking",
}


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
        self._emotion = "listening"
        self._running = False
        self._initialized = False
        self._thread = None
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._last_blink_at = 0.0
        self._next_blink_after = random.uniform(10.0, 18.0)
        self._next_mouth_frame = 0.0
        self._mouth_is_lit = False
        self._next_confused_shift = 0.0
        self._confused_side = -1
        self._exasperated_sigh_until = 0.0

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
            testmode.init_neopixel(silent=True)
            animation.reset()

            eyes.center()
            eyelids.open_lids()
            self._clear_mouth()
            self._initialized = True
            return True

    def start(self, initial_emotion="listening"):
        """Start the background animation loop."""
        if not self.initialize():
            return False

        with self._lock:
            self._emotion = _normalize_emotion(initial_emotion)
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
            self._next_confused_shift = 0.0
            self._exasperated_sigh_until = 0.0
            self._apply_entry_pose_locked(emotion)

        return emotion

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
            t = now - self._started_at

            if emotion == "normal_talking":
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

    def _run_loop(self):
        while True:
            with self._lock:
                running = self._running
            if not running:
                break

            self.tick()
            time.sleep(self.tick_seconds)

    def _apply_entry_pose_locked(self, emotion):
        if emotion == "normal_talking":
            self._set_lids(1.0)
            eyes.gaze_smooth(90, 90, steps=12, duration=0.12)
        elif emotion == "listening":
            self._set_lids(1.0)
            eyes.gaze_smooth(90, 86, steps=12, duration=0.12)
            self._mouth_color((0, 0, 0))
        elif emotion == "happy":
            self._set_lids(0.96)
            eyes.gaze_smooth(90, 86, steps=14, duration=0.16)
            self._mouth_color((180, 125, 0), width=6)
        elif emotion == "sad":
            self._set_lids(0.52)
            self._gaze_independent_smooth(90, 98, 90, 106, steps=18, duration=0.25)
            self._mouth_color((0, 0, 70), width=3)
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
            self._mouth_left_side((110, 85, 0), count=2)

    def _tick_normal_talking(self, now, t):
        h = 90 + 7 * math.sin(t * 0.55)
        v = 90 + 3 * math.sin(t * 0.8)
        eyes.gaze(h, v)
        self._maybe_blink(now)
        self._mouth_talk_frame(now, base_color=(190, 125, 0))

    def _tick_listening(self, now, t):
        h = 90 + 4 * math.sin(t * 0.35)
        v = 86 + 2 * math.sin(t * 0.45)
        eyes.gaze(h, v)
        self._set_lids(1.0)
        self._maybe_blink(now)
        self._clear_mouth()

    def _tick_happy(self, now, t):
        h = 90 + 9 * math.sin(t * 1.1)
        v = 86 + 3 * math.sin(t * 1.7)
        eyes.gaze(h, v)
        self._set_lids(0.92 + 0.04 * math.sin(t * 2.2))
        self._maybe_blink(now, every=(9.0, 16.0))
        if now >= self._next_mouth_frame:
            level = random.randint(90, 180)
            self._mouth_color((level, max(0, level - 40), 0), width=random.randint(5, 8))
            self._next_mouth_frame = now + 0.12

    def _tick_sad(self, now, t):
        h = 90 + 3 * math.sin(t * 0.22)
        left_v = 98 + 2 * math.sin(t * 0.3)
        right_v = 106 + 2 * math.sin(t * 0.3)
        self._gaze_independent(h, left_v, h, right_v)
        self._set_lids(0.50 + 0.04 * math.sin(t * 0.6))
        self._maybe_blink(now, every=(11.0, 20.0), closed_seconds=0.30)
        self._mouth_color((0, 0, 55), width=3)

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
        self._mouth_left_side((110, 85, 0), count=2)

    def _maybe_blink(self, now, every=(6.0, 12.0), closed_seconds=0.16):
        if self._last_blink_at == 0.0:
            self._last_blink_at = now

        if now - self._last_blink_at < self._next_blink_after:
            return

        eyelids.close_lids()
        time.sleep(closed_seconds)
        with self._lock:
            self._restore_lids_after_blink_locked(self._emotion)
        self._last_blink_at = time.time()
        self._next_blink_after = random.uniform(*every)

    def _restore_lids_after_blink_locked(self, emotion):
        if emotion in ("normal_talking", "listening"):
            self._set_lids(1.0)
        elif emotion == "happy":
            self._set_lids(0.96)
        elif emotion == "sad":
            self._set_lids(0.52)
        elif emotion == "surprised":
            eyelids.wide_open_lids()
        elif emotion == "confused":
            self._set_lids(0.82)
        elif emotion == "exasperated":
            eyelids.wide_open_lids()
        elif emotion == "thinking":
            self._set_lids(0.90)

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

        servos.set_servo_angle(CH_LID_LEFT, angle_for("lid_l"))
        servos.set_servo_angle(CH_LID_RIGHT, angle_for("lid_r"))

    def _gaze_independent(self, left_h, left_v, right_h, right_v):
        left_targets = eyes._gaze_targets(left_h, left_v)
        right_targets = eyes._gaze_targets(right_h, right_v)
        eyes.look(left_targets[0], left_targets[1], right_targets[2], right_targets[3])

    def _gaze_independent_smooth(self, left_h, left_v, right_h, right_v, steps=12, duration=0.12):
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

    def _mouth_talk_frame(self, now, base_color):
        if now < self._next_mouth_frame:
            return

        if not testmode.neopixel_ready or testmode.pixels is None:
            return

        width = random.choice((1, 2, 3, 4, 6, 8))
        level = random.uniform(0.45, 1.0)
        color = tuple(int(component * level) for component in base_color)
        center = (testmode.LED_COUNT - 1) / 2

        testmode.pixels.fill((0, 0, 0))
        for i in range(testmode.LED_COUNT):
            distance = abs(i - center)
            if distance <= width / 2:
                falloff = 1.0 - (distance / max(1.0, width))
                testmode.pixels[i] = tuple(int(component * falloff) for component in color)

        testmode.pixels_show()
        self._mouth_is_lit = True
        self._next_mouth_frame = now + random.uniform(0.05, 0.12)

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


def start(initial_emotion="listening"):
    return _default_controller.start(initial_emotion=initial_emotion)


def stop(clear_mouth=True, relax_servos=False):
    _default_controller.stop(clear_mouth=clear_mouth, relax_servos=relax_servos)


def set_emotion(emotion):
    return _default_controller.set_emotion(emotion)


def speak():
    return _default_controller.speak()


def listen():
    return _default_controller.listen()


def tick():
    _default_controller.tick()
