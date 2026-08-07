"""Small choreography helpers built around Ezra's existing robot functions."""

import random
import threading
import time


def speak_with_head_motion(
    speak,
    text,
    look_left=None,
    look_right=None,
    look_targets=None,
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
    try:
        interrupted = bool(
            speak(text, on_playback_start=playback_started.set)
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
