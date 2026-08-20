"""Small choreography helpers built around Ezra's existing robot functions."""

import random
import threading
import time

from config import (
    PRESENTATION_HEAD_INITIAL_LOOK_DELAY_SECONDS,
    PRESENTATION_HEAD_LOOK_INTERVAL_SECONDS,
    PRESENTATION_NARROW_AUDIENCE_BEARINGS,
    PRESENTATION_WIDE_AUDIENCE_BEARINGS,
)


# Preserve these names for presentation modules that already import them.
WIDE_AUDIENCE_BEARINGS = PRESENTATION_WIDE_AUDIENCE_BEARINGS
NARROW_AUDIENCE_BEARINGS = PRESENTATION_NARROW_AUDIENCE_BEARINGS


def audience_look_targets(head_tracker, bearings=WIDE_AUDIENCE_BEARINGS):
    """Build callbacks that turn Ezra toward fixed audience bearings."""

    return [
        lambda stop_event=None, target=target: head_tracker.turn_toward_bearing(
            target - head_tracker.current_yaw,
            source="presentation",
            announce=False,
            stop_event=stop_event,
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
        playback_deadline = time.monotonic() + 30.0
        while not playback_started.wait(timeout=0.1):
            if stop_motion.is_set() or time.monotonic() >= playback_deadline:
                return
        if stop_motion.wait(
            random.uniform(*PRESENTATION_HEAD_INITIAL_LOOK_DELAY_SECONDS)
        ):
            return

        movements = [
            (move, True) for move in (look_targets or ()) if move is not None
        ]
        if not movements:
            movements = [
                (move, False)
                for move in (look_left, look_right)
                if move is not None
            ]
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
            for movement, accepts_stop_event in movements:
                if stop_motion.is_set():
                    return
                if accepts_stop_event:
                    movement(stop_motion)
                else:
                    movement()
                previous_movement = (movement, accepts_stop_event)
                if stop_motion.wait(
                    random.uniform(*PRESENTATION_HEAD_LOOK_INTERVAL_SECONDS)
                ):
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
        # Audience moves observe stop_motion at every servo step, so this join
        # completes promptly and guarantees callers can safely center the head.
        motion_thread.join()

    return interrupted


def smile_and_pause(smile=None, pause_seconds=0.6):
    """Use Ezra's existing smile and hold it for a short presentation beat."""

    if smile is not None:
        smile(pause_seconds)
    time.sleep(pause_seconds)
