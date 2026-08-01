import state
from config import EMOTION_STANDBY
from robot import robot_emotions

print("🤖 Starting robot emotions...")

robot_emotions.start(EMOTION_STANDBY)


def set_emotion(emotion):
    if state.shutting_down:
        return

    print(f"👀 Emotion: {emotion}")

    try:
        robot_emotions.set_emotion(emotion)

    except Exception as e:
        print(f"Emotion error: {e}")


def set_temporary_emotion(emotion, seconds, fallback_emotion=EMOTION_STANDBY):
    if state.shutting_down:
        return

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
