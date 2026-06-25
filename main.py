import string
from datetime import datetime
import os
import sys

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

import state

from audio import listen
from config import *
from ezra_brain import ask_ezra
from ezra_emotion import set_emotion
from stt import transcribe
from tts import speak
from wake_word import (
    CONTINUOUS_CAPTURE_AFTER_WAKE,
    reset_idle_timer,
    wait_for_wake_word_with_audio,
)

# STT: Using local Whisper (base.en) for fast, offline transcription.
# No external API dependency or cost. compare_stt.py can benchmark
# against online models if needed.

# Common Whisper misinterpretations of "Ezra."
WAKE_WORDS = {
    "ezra",
    "zra",
    "ra",
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


def log_audio_stats(label, audio, sample_rate=16000):
    """Print compact duration/level stats for captured audio."""

    if audio is None:
        print(f"🧪 {label}: none")
        return

    arr = np.asarray(audio, dtype=np.float32).flatten()

    if arr.size == 0:
        print(f"🧪 {label}: empty")
        return

    duration = arr.size / float(sample_rate)
    peak = float(np.max(np.abs(arr)))
    rms = float(np.sqrt(np.mean(arr**2)))

    print(f"🧪 {label}: duration={duration:.2f}s " f"peak={peak:.4f} rms={rms:.4f}")


def save_debug_wav(audio, sample_rate=16000, debug_wav="/tmp/whisper_input.wav"):
    """Save captured audio as debug WAV normalized to peak 0.9 for consistent playback."""

    if audio is None:
        return

    arr = np.asarray(audio, dtype=np.float32).flatten()

    if arr.size == 0:
        return

    # Normalize to peak 0.9 like STT does.
    peak = float(np.max(np.abs(arr)))
    if peak > 0:
        gain = 0.9 / peak
        arr = np.clip(arr * gain, -1.0, 1.0)

    # Write as 16-bit PCM.
    arr_int16 = np.int16(np.clip(arr * 32767.0, -32768, 32767))
    wav.write(debug_wav, sample_rate, arr_int16)


def get_single_key():
    """Read a single key press without requiring Enter (Unix/Linux)."""
    try:
        import tty
        import termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch.lower()
    except Exception:
        # Fallback if tty/termios unavailable.
        return input().lower()


def playback_diagnostic():
    """Auto-play the STT debug WAV file with optional repeat."""

    debug_wav = "/tmp/whisper_input.wav"

    if not os.path.isfile(debug_wav):
        print("🧪 No debug WAV found")
        return

    try:
        sample_rate, data = wav.read(debug_wav)
    except Exception as e:
        print(f"⚠️ Failed to read debug WAV: {e}")
        return

    print("\n🧪 Playback diagnostic")
    print("🧪 Playing recorded command...")

    try:
        sd.play(data, sample_rate)
        sd.wait()
        print("🧪 Playback finished")
    except Exception as e:
        print(f"⚠️ Playback failed: {e}")
        return

    # Repeat loop with single-key input.
    while True:
        print("🧪 Play again? [y/n]: ", end="", flush=True)
        try:
            ch = get_single_key()
            print(ch)  # Echo the key press
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if ch not in {"y", "yes"}:
            break

        try:
            sd.play(data, sample_rate)
            sd.wait()
            print("🧪 Playback finished")
        except Exception as e:
            print(f"⚠️ Playback failed: {e}")
            break


def strip_wake_word(text):
    """Remove the wake word from recognized text."""

    if not text:
        return ""

    # Normalize the text.
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    text = text.strip()

    words = text.split()

    # Whisper can hallucinate "hey ezra" as "here's what".
    if len(words) >= 2 and words[0] == "heres" and words[1] == "what":
        words = words[2:]

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
        "heres what",
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
    interaction_count = 0

    try:
        while not state.shutting_down:

            # Wait for Ezra or Hey Ezra.
            wake_text, wake_audio = wait_for_wake_word_with_audio()

            interaction_count += 1

            print(f"\n🧪 Wake/listen probe #{interaction_count}")

            print(f"DEBUG wake text: [{wake_text}]")

            reset_idle_timer()

            # Check whether the wake result also contained a command.
            command = strip_wake_word(wake_text)

            # Usually the command is spoken after the wake word.
            if not command:
                audio = None

                if CONTINUOUS_CAPTURE_AFTER_WAKE:
                    audio = wake_audio
                else:
                    print("👂 Listening for command...")
                    audio = listen(wake_audio, wake_text)

                if audio is None:
                    if wake_audio is not None:
                        save_debug_wav(wake_audio)
                        playback_diagnostic()

                    print("⏱️ Timeout waiting for command")
                    continue

                # Convert the command audio to text.
                text = transcribe(audio)
                print(f"🧪 STT raw text: [{text}]")

                if not text:
                    continue

                command = strip_wake_word(text)
                print(f"🧪 STT stripped command: [{command}]")

                # Ignore recordings containing only the wake word.
                if is_wake_word_only(command):
                    print("⚠️ Wake word only — " "returning to standby")
                    continue

            else:
                # Supports wake detection returning a full command.
                print(f"⚡ Direct command: {command}")
                # Save wake audio as debug WAV so playback diagnostic works.
                save_debug_wav(wake_audio)

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
                # Run optional audio replay diagnostics after Ezra responds.
                playback_diagnostic()
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

            # Run optional audio replay diagnostics after Ezra responds.
            playback_diagnostic()

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
