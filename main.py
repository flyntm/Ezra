import shutil
import subprocess
import threading
import time

import state

from audio import listen
from audio_debug import playback_diagnostic, save_debug_wav
from command import handle_local_command
from command_normalization import is_wake_word_only, strip_wake_word
from config import *
from ezra_brain import ask_ezra
from ezra_emotion import set_emotion, set_temporary_emotion
from item_tests import display_command_text_diagnostic, display_doa_diagnostic
from stt import transcribe
from thinking_comments import prepare_thinking_comments, start_comment
from tts import speak
from wake_word import (
    CONTINUOUS_CAPTURE_AFTER_WAKE,
    get_last_command_doa as get_last_continuous_command_doa,
    get_last_command_doa_diagnostic,
    reset_idle_timer,
    wait_for_wake_word_with_audio,
)

# STT: Using local Whisper (base.en) for fast, offline transcription.
# No external API dependency or cost. compare_stt.py can benchmark
# against online models if needed.

# Convert GnPT emotion names to Ezra emotion names.
EMOTION_MAP = {
    "neutral": "listening",
    "happy": "happy",
    "curious": "thinking",
    "thinking": "thinking",
    "confused": "confused",
    "excited": "surprised",
}


def maybe_playback_diagnostic(debug_audio=None):
    """Run optional playback diagnostics when enabled in config."""

    if not ENABLE_PLAYBACK_DIAGNOSTICS:
        return

    if debug_audio is not None:
        save_debug_wav(debug_audio)

    playback_diagnostic()


def stop_thinking_comment(cancel_event, comment_thread):
    """Cancel a pending comment, but allow a started comment to finish."""
    if cancel_event is None:
        return

    if (
        comment_thread is not None
        and comment_thread.comment_started_event.is_set()
    ):
        # Once Ezra starts a sentence, finishing it sounds more natural than
        # cutting it off when transcription or the AI response completes.
        comment_thread.join(timeout=10.0)
        if not comment_thread.is_alive():
            return

        print("⚠️ Thinking comment timed out; stopping playback")

    cancel_event.set()
    if comment_thread is not None:
        comment_thread.join(timeout=0.30)


def log_speaker_output_sanity():
    """Print a quick, non-blocking speaker routing sanity check."""

    print(f"🔊 Configured speaker device: {SPEAKER_DEVICE}")

    if shutil.which("aplay") is None:
        print("⚠️ 'aplay' not found in PATH; TTS playback will fail.")

    if SPEAKER_DEVICE != "default":
        print(
            "⚠️ Using a fixed ALSA output device. If USB/audio routing changes, "
            "playback may fail until the device name is updated."
        )
        return

    if shutil.which("wpctl") is None:
        print(
            "⚠️ 'wpctl' not found in PATH; cannot verify current PipeWire default sink."
        )
        return

    try:
        result = subprocess.run(
            ["wpctl", "get-default"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except subprocess.TimeoutExpired:
        print("⚠️ Timed out while checking PipeWire default sink.")
        return
    except subprocess.CalledProcessError:
        # Some ALSA "default" setups do not have a PipeWire default sink to
        # report. Playback can still work, so keep this optional check quiet.
        return

    sink = result.stdout.strip()

    if sink:
        print(f"🔊 PipeWire default sink: {sink}")
    else:
        print("⚠️ PipeWire returned an empty default sink value.")


def shutdown_robot():
    """Stop Ezra safely."""

    state.shutting_down = True

    print("\n🛑 Shutting down Ezra...")

    try:
        if (
            ENABLE_HEAD_TRACKING
            and not ENABLE_INTERACTION_DIAGNOSTIC
        ):
            from robot.head_tracking import head_tracker

            head_tracker.center()

        from robot import robot_emotions

        robot_emotions.stop(
            clear_mouth=True,
            relax_servos=False,
        )

    except Exception as e:
        print(f"Shutdown error: {e}")


def main():
    prepare_thinking_comments()
    print("🤖 Ezra ready!\n")
    log_speaker_output_sanity()
    interaction_count = 0

    try:
        while not state.shutting_down:

            # Wait for Ezra or Hey Ezra.
            wake_text, wake_audio = wait_for_wake_word_with_audio()

            interaction_count += 1

            if VERBOSE_RUNTIME_LOGS:
                print(f"\n🧪 Wake/listen probe #{interaction_count}")
                print(f"DEBUG wake text: [{wake_text}]")

            # ITEM TEST 1: continuous capture has already gathered the complete
            # utterance and its DoA samples. Report them before Whisper/STT or
            # any command/response processing occurs.
            if ENABLE_DOA_DIAGNOSTIC:
                command_doa = get_last_continuous_command_doa()
                doa_diagnostic = get_last_command_doa_diagnostic()
                display_doa_diagnostic(
                    wake_text,
                    command_doa,
                    doa_diagnostic,
                )
                reset_idle_timer()
                continue

            # ITEM TEST 3: wake_word.py has already applied any qualified wake
            # and post-wake command corrections. Report the resulting yaw and
            # re-arm without transcription or response processing.
            if ENABLE_HEAD_DIRECTION_DIAGNOSTIC:
                from robot.head_tracking import head_tracker

                print(
                    f'🧪 HEAD DIRECTION TEST | Wake: "{wake_text}" | '
                    f"Final yaw: {head_tracker.current_yaw:+.1f}°"
                )
                reset_idle_timer()
                continue

            reset_idle_timer()
            set_emotion(EMOTION_LISTENING)

            # Check whether the wake result also contained a command.
            command = strip_wake_word(wake_text)
            command_was_transcribed = False
            comment_cancel = None
            comment_thread = None
            thinking_started_at = None

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
                        maybe_playback_diagnostic(wake_audio)

                    print("⏱️ Timeout waiting for command")
                    set_emotion(EMOTION_STANDBY)
                    continue

                # Convert the command audio to text.
                set_emotion(EMOTION_THINKING)
                if ENABLE_THINKING_COMMENTS:
                    thinking_started_at = time.monotonic()
                    comment_cancel = threading.Event()
                    comment_thread = start_comment(
                        comment_cancel,
                        THINKING_COMMENT_DELAY_SECONDS,
                    )
                command_was_transcribed = True
                text = transcribe(audio)
                if VERBOSE_RUNTIME_LOGS:
                    print(f"🧪 STT raw text: [{text}]")

                if not text:
                    stop_thinking_comment(comment_cancel, comment_thread)
                    set_emotion(EMOTION_STANDBY)
                    continue

                command = strip_wake_word(text)
                if VERBOSE_RUNTIME_LOGS:
                    print(f"🧪 STT stripped command: [{command}]")

                # Ignore recordings containing only the wake word.
                if is_wake_word_only(command):
                    print("⚠️ Wake word only — " "returning to standby")
                    stop_thinking_comment(comment_cancel, comment_thread)
                    set_emotion(EMOTION_STANDBY)
                    continue

            else:
                # Supports wake detection returning a full command.
                print(f"⚡ Direct command: {command}")
                # Save wake audio as debug WAV so playback diagnostic works.
                maybe_playback_diagnostic(wake_audio)

            # Ignore empty or unclear commands.
            if len(command) < 2:
                print("⚠️ Ignoring short or unclear input")
                stop_thinking_comment(comment_cancel, comment_thread)
                set_emotion(EMOTION_STANDBY)
                continue

            print(f"📝 Command: {command}")

            # ITEM TEST 2: show the transcribed command, but do not execute it
            # or produce any response or head movement.
            if ENABLE_COMMAND_TEXT_DIAGNOSTIC:
                stop_thinking_comment(comment_cancel, comment_thread)
                display_command_text_diagnostic(command)
                reset_idle_timer()
                continue

            if not command_was_transcribed:
                set_emotion(EMOTION_THINKING)

            # Handle simple commands locally.
            comment_was_started = False
            if command_was_transcribed:
                comment_was_started = bool(
                    comment_thread is not None
                    and comment_thread.comment_started_event.is_set()
                )
                stop_thinking_comment(comment_cancel, comment_thread)
                comment_cancel = None
                comment_thread = None

            if handle_local_command(command):
                # Run optional audio replay diagnostics after Ezra responds.
                maybe_playback_diagnostic()
                continue

            # Send all other commands to Ezra's brain.
            if comment_cancel is None and not comment_was_started:
                comment_cancel = threading.Event()
                if ENABLE_THINKING_COMMENTS:
                    elapsed_thinking = (
                        time.monotonic() - thinking_started_at
                        if thinking_started_at is not None
                        else 0.0
                    )
                    comment_thread = start_comment(
                        comment_cancel,
                        max(
                            0.0,
                            THINKING_COMMENT_DELAY_SECONDS - elapsed_thinking,
                        ),
                    )
            elif comment_cancel is None:
                comment_cancel = threading.Event()
            try:
                result = ask_ezra(command)

            except Exception as e:
                print(f"❌ Ezra brain error: {e}")

                set_emotion("confused")
                speak("I'm sorry. I had trouble answering that.")
                reset_idle_timer()
                continue
            finally:
                stop_thinking_comment(comment_cancel, comment_thread)

            # Make sure the brain returned a dictionary.
            if not isinstance(result, dict):
                print("⚠️ Ezra brain returned an unexpected result")
                result = {}

            response = result.get("response", "")
            emotion = str(result.get("emotion", "neutral")).strip().lower()

            if not response:
                response = "I'm not sure how to respond to that."

            # Convert the GPT emotion to an Ezra emotion.
            mapped_emotion = EMOTION_MAP.get(
                emotion,
                "listening",
            )

            set_emotion(mapped_emotion)
            speak(response)

            if emotion in POST_RESPONSE_SMILE_EMOTIONS:
                set_temporary_emotion(
                    "happy",
                    POST_RESPONSE_SMILE_SECONDS,
                    fallback_emotion=EMOTION_STANDBY,
                )

            # Run optional audio replay diagnostics after Ezra responds.
            maybe_playback_diagnostic()

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
