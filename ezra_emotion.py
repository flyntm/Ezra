from robot import robot_emotions

print("🤖 Starting robot emotions...")

robot_emotions.start("listening")


def set_emotion(emotion):

    print(f"👀 Emotion: {emotion}")

    try:
        robot_emotions.set_emotion(emotion)

    except Exception as e:
        print(f"Emotion error: {e}")