from dotenv import load_dotenv
from pathlib import Path

# 🔥 Load .env FIRST
load_dotenv(Path(__file__).parent / ".env", override=True)

# Imports
from audio import listen
from stt import transcribe
from tts import speak
from ezra_brain import ask_ezra
from ezra_emotion import set_emotion
import state


def main():
    print("🤖 Ezra ready!\n")

    try:
        while True:
            set_emotion("listening")

            audio = listen()

            if audio is None:
                continue

            text = transcribe(audio)

            if not text:
                continue

            if "quit" in text.lower():
                speak("Goodbye!")
                break

            result = ask_ezra(text)
            speak(result["response"])

    except KeyboardInterrupt:
        state.shutting_down = True
        print("\n🛑 Shutting down Ezra...")


# 🔥 MUST be at top level (no indent)
if __name__ == "__main__":
    main()
