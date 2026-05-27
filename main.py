print("🔥 USING NEW STT FILE 🔥")
from audio import listen
from stt import transcribe
from tts import speak
from ezra_brain import ask_ezra
from ezra_emotion import set_emotion
from config import *
from wake_word import wait_for_wake_word
import state
import string

WAKE_WORDS = ["ezra", "extra", "israel", "ezrah", "ez", "you"]


def strip_wake_word(text):
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))

    words = text.split()

    # Remove wake word ANYWHERE in first 2 words
    if words and words[0] in WAKE_WORDS:
        words.pop(0)
    elif len(words) > 1 and words[1] in WAKE_WORDS:
        words.pop(1)

    return " ".join(words).strip()


def main():
    print("🤖 Ezra ready!\n")

    try:
        while True:
            # =========================
            # WAIT FOR WAKE WORD
            # =========================
            text = wait_for_wake_word()

            # strip wake words
            command = strip_wake_word(text)

            # =========================
            # HANDLE "JUST EZRA"
            # =========================
            if not command:
                print("👂 Listening for command...")
                speak("Yes?")

                audio = listen()

                if audio is None:
                    print("⏱️ Timeout waiting for command")
                    continue

                text = transcribe(audio)
                if not text:
                    continue

                command = strip_wake_word(text)

            else:
                print(f"⚡ Direct command: {command}")

            # =========================
            # FILTER GARBAGE INPUT
            # =========================
            if len(command.strip()) < 2:
                print("⚠️ Ignoring short/unclear input")
                speak("I didn't catch that.")
                continue

            text_lower = command.lower()

            # =========================
            # EMOTION: LISTENING
            # =========================
            set_emotion(EMOTION_LISTENING)

            # =========================
            # QUIT HANDLING
            # =========================
            if any(word in text_lower for word in QUIT_KEYWORDS):
                speak(GOODBYE_TEXT)
                break

            # =========================
            # ASK EZRA (GPT)
            # =========================
            result = ask_ezra(command)

            response = result.get("response", "")
            emotion = result.get("emotion", "neutral")

            if not response:
                response = "I'm not sure how to respond to that."

            # =========================
            # EMOTION MAPPING
            # =========================
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
