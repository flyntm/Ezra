import state
from config import (
    EMOTION_STANDBY,
    ENABLE_FACE_MOTION_DIAGNOSTIC,
    VERBOSE_RUNTIME_LOGS,
)
from robot import robot_emotions

_emotions_started = False


def start_emotions():
    """Initialize the face only when the rest of Ezra is ready to be seen."""
    global _emotions_started

    if _emotions_started:
        return True

    print("🤖 Starting robot emotions...")

    if ENABLE_FACE_MOTION_DIAGNOSTIC:
        print("🧪 Diagnostic face lock enabled: eye and eyelid animation disabled")
        started = robot_emotions.start("wake")
        # The normal wake expression intentionally lights one mouth pixel. Stop
        # the animation controller after applying the stationary pose so the
        # diagnostic remains mechanically quiet with every mouth LED off.
        robot_emotions.stop(clear_mouth=True, relax_servos=False)
    else:
        started = robot_emotions.start(EMOTION_STANDBY)
        if started:
            print("✅ Servo and mouth hardware ready")

    _emotions_started = bool(started)
    return _emotions_started


def set_emotion(emotion):
    if state.shutting_down:
        return

    if ENABLE_FACE_MOTION_DIAGNOSTIC:
        return

    if VERBOSE_RUNTIME_LOGS:
        print(f"👀 Emotion: {emotion}")

    try:
        robot_emotions.set_emotion(emotion)

    except Exception as e:
        print(f"Emotion error: {e}")


def set_temporary_emotion(emotion, seconds, fallback_emotion=EMOTION_STANDBY):
    if state.shutting_down:
        return

    if ENABLE_FACE_MOTION_DIAGNOSTIC:
        return

    if VERBOSE_RUNTIME_LOGS:
        print(f"👀 Emotion: {emotion} for {seconds:.1f}s")

    try:
        robot_emotions.set_temporary_emotion(
            emotion,
            seconds,
            fallback_emotion=fallback_emotion,
        )

    except Exception as e:
        print(f"Emotion error: {e}")


def set_talk_level(level):
    """Set the live TTS mouth opening from zero (closed) to one (wide)."""
    if state.shutting_down:
        return

    try:
        robot_emotions.set_talk_level(level)
    except Exception as e:
        print(f"Mouth sync error: {e}")
