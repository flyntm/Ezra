import string
from datetime import datetime

import state

from audio import listen
from config import *
from ezra_brain import ask_ezra
from ezra_emotion import set_emotion
from stt import transcribe
from tts import speak
from wake_word import (
    reset_idle_timer,
    wait_for_wake_word_with_audio,
)

# Common Whisper misinterpretations of "Ezra."
WAKE_WORDS = {
    "ezra",
    "edra",
    "extra",
    "israel",
    "ezrah",
    "ez",
    "you",
}


# Convert GPT emotion names to Ezra emotion names.
EMOTION_MAP = {
    "neutral": "listening",
    "happy": "happy",
    "curious": "thinking",
    "thinking": "thinking",
    "confused": "confused",
    "excited": "surprised",
}


def strip_wake_word(text):
    """Remove the wake word from recognized text."""

    if not text:
        return ""

    # Normalize the text.
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = text.strip()

    words = text.split()

    # Remove "Hey Ezra" together.
    if len(words) >= 2 and words[0] == "hey" and words[1] in WAKE_WORDS:
        words = words[2:]

    # Remove a single wake word.
    elif words and words[0] in WAKE_WORDS:
        words = words[1:]

    return " ".join(words).strip()


def is_wake_word_only(command):
    """Check whether the recording contains only a wake phrase."""

    normalized = command.lower().strip()

    return normalized in {
        "",
        "here's",
        "heres",
        "ezra",
        "edra",
        "hey ezra",
        "hey edra",
        "extra",
        "israel",
        "ezrah",
    }


def handle_local_command(command):
    """
    Handle commands that do not need GPT.

    Returns True if handled here.
    """

    text_lower = command.lower()

    if "what time" in text_lower:
        now = datetime.now().strftime("%I:%M %p")
        speak(f"It is {now}")
        reset_idle_timer()
        return True

    return False


def shutdown_robot():
    """Stop Ezra safely."""

    state.shutting_down = True

    print("\n🛑 Shutting down Ezra...")

    try:
        from robot import robot_emotions

        robot_emotions.stop(
            clear_mouth=True,
            relax_servos=False,
        )

    except Exception as e:
        print(f"Shutdown error: {e}")


def main():
    print("🤖 Ezra ready!\n")

    try:
        while not state.shutting_down:

            # Wait for Ezra or Hey Ezra.
            wake_text, wake_audio = wait_for_wake_word_with_audio()

            print(f"DEBUG wake text: [{wake_text}]")

            reset_idle_timer()

            # Check whether the wake result also contained a command.
            command = strip_wake_word(wake_text)

            # Usually the command is spoken after the wake word.
            if not command:
                print("👂 Listening for command...")

                audio = listen(wake_audio)

                if audio is None:
                    print("⏱️ Timeout waiting for command")
                    continue

                # Convert the command audio to text.
                text = transcribe(audio)

                if not text:
                    continue

                command = strip_wake_word(text)

                # Ignore recordings containing only the wake word.
                if is_wake_word_only(command):
                    print("⚠️ Wake word only — " "returning to standby")
                    continue

            else:
                # Supports wake detection returning a full command.
                print(f"⚡ Direct command: {command}")

            command = command.strip()

            # Ignore empty or unclear commands.
            if len(command) < 2:
                print("⚠️ Ignoring short or unclear input")
                continue

            print(f"📝 Command: {command}")

            text_lower = command.lower()

            # Check for shutdown phrases.
            if any(keyword in text_lower for keyword in QUIT_KEYWORDS):
                speak(GOODBYE_TEXT)
                break

            # Handle simple commands locally.
            if handle_local_command(command):
                continue

            # Send all other commands to Ezra's brain.
            set_emotion(EMOTION_LISTENING)

            try:
                result = ask_ezra(command)

            except Exception as e:
                print(f"❌ Ezra brain error: {e}")

                set_emotion("confused")
                speak("I'm sorry. I had trouble answering that.")
                reset_idle_timer()
                continue

            # Make sure the brain returned a dictionary.
            if not isinstance(result, dict):
                print("⚠️ Ezra brain returned an unexpected result")
                result = {}

            response = result.get("response", "")
            emotion = result.get("emotion", "neutral")

            if not response:
                response = "I'm not sure how to respond to that."

            # Convert the GPT emotion to an Ezra emotion.
            mapped_emotion = EMOTION_MAP.get(
                emotion,
                "listening",
            )

            set_emotion(mapped_emotion)
            speak(response)

            reset_idle_timer()

    except KeyboardInterrupt:
        pass

    except Exception as e:
        print(f"\n❌ MAIN ERROR: {e}")

    finally:
        shutdown_robot()


# Run main only when this file is started directly.
if __name__ == "__main__":
    main()
