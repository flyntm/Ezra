"""Small choreography helpers built around Ezra's existing robot functions."""

import random
import threading
import time

WIDE_AUDIENCE_BEARINGS = (
    -48.0,
    -35.0,
    -22.0,
    -10.0,
    0.0,
    12.0,
    25.0,
    38.0,
    50.0,
)
NARROW_AUDIENCE_BEARINGS = (-35.0, -18.0, 0.0, 18.0, 35.0)


def audience_look_targets(head_tracker, bearings=WIDE_AUDIENCE_BEARINGS):
    """Build callbacks that turn Ezra toward fixed audience bearings."""

    return [
        lambda target=target: head_tracker.turn_toward_bearing(
            target - head_tracker.current_yaw,
            source="presentation",
            step_delay_seconds=0.05,
            announce=False,
        )
        for target in bearings
    ]


def speak_with_head_motion(
    speak,
    text,
    look_left=None,
    look_right=None,
    look_targets=None,
    **speak_kwargs,
):
    """Speak a segment while making optional, gentle head turns."""

    stop_motion = threading.Event()
    playback_started = threading.Event()

    def move_head():
        if not playback_started.wait(timeout=30.0):
            return
        if stop_motion.wait(random.uniform(0.45, 1.0)):
            return

        movements = [move for move in (look_targets or ()) if move is not None]
        if not movements:
            movements = [move for move in (look_left, look_right) if move is not None]
        if not movements:
            return

        previous_movement = None
        while not stop_motion.is_set():
            # A shuffled bag feels spontaneous without repeatedly snapping back
            # to the same person or falling into a left/right metronome pattern.
            random.shuffle(movements)
            if len(movements) > 1 and movements[0] is previous_movement:
                swap_index = random.randrange(1, len(movements))
                movements[0], movements[swap_index] = (
                    movements[swap_index],
                    movements[0],
                )
            for movement in movements:
                if stop_motion.is_set():
                    return
                movement()
                previous_movement = movement
                if stop_motion.wait(random.uniform(1.7, 3.4)):
                    return

    motion_thread = threading.Thread(target=move_head, daemon=True)
    motion_thread.start()
    original_playback_start = speak_kwargs.pop("on_playback_start", None)

    def speech_started():
        playback_started.set()
        if original_playback_start is not None:
            original_playback_start()

    try:
        interrupted = bool(
            speak(text, on_playback_start=speech_started, **speak_kwargs)
        )
    finally:
        stop_motion.set()
        motion_thread.join(timeout=0.5)

    return interrupted


def smile_and_pause(smile=None, pause_seconds=0.6):
    """Use Ezra's existing smile and hold it for a short presentation beat."""

    if smile is not None:
        smile(pause_seconds)
    time.sleep(pause_seconds)
