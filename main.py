from audio import listen
from stt import transcribe
from tts import speak
from ezra_brain import ask_ezra
from ezra_emotion import set_emotion
from config import *
from wake_word import wait_for_wake_word
import state


def main():
    print("🤖 Ezra ready!\n")

    try:
        while True:
            # 👂 Wait for wake word (returns full spoken phrase)
            text = wait_for_wake_word()
            text_lower = text.lower()

            # 🧹 Strip wake word
            for w in ["ezra", "extra", "israel"]:
                if w in text_lower:
                    text = text_lower.replace(w, "").strip()
                    break

            # 🎯 If user ONLY said "Ezra" → ask for command
            if len(text.split()) <= 1:
                print("👂 Listening for command...")
                speak("Yes?")  # optional but improves UX

                audio = listen()
                if audio is None:
                    continue

                text = transcribe(audio)
                if not text:
                    continue

                text_lower = text.lower()

            # 🎭 Set listening emotion
            set_emotion(EMOTION_LISTENING)

            # 🚪 Quit handling
            if any(word in text_lower for word in QUIT_KEYWORDS):
                speak(GOODBYE_TEXT)
                break

            # 🧠 Ask Ezra (GPT)
            result = ask_ezra(text)

            response = result.get("response", "")
            emotion = result.get("emotion", "neutral")

            if not response:
                response = "I'm not sure how to respond to that."

            # 🎭 Map AI emotion → robot emotion
            EMOTION_MAP = {
                "neutral": "listening",
                "happy": "happy",
                "curious": "thinking",
                "thinking": "thinking",
                "confused": "confused",
                "excited": "surprised",
            }

            mapped_emotion = EMOTION_MAP.get(emotion, "listening")

            set_emotion(mapped_emotion)
            speak(response)

    except KeyboardInterrupt:
        state.shutting_down = True
        print("\n🛑 Shutting down Ezra...")

        from robot import robot_emotions

        robot_emotions.stop()


if __name__ == "__main__":
    main()
