import random
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import state

from audio import get_last_command_doa, listen
from audio_debug import playback_diagnostic, save_debug_wav
from bible_display import close_bible_display
from command import handle_local_command
from command_timing import (
    CommandTiming,
    clear_active_command_timing,
    set_active_command_timing,
)
from command_normalization import (
    is_follow_up_cancel,
    is_unclear_single_word,
    is_wake_word_only,
    strip_wake_word,
)
from config import *
from ezra_brain import InternetUnavailableError, ask_ezra
from ezra_emotion import set_emotion, set_temporary_emotion
from item_tests import display_command_text_diagnostic, display_doa_diagnostic
from local_ai_server import start_local_ai_server, stop_local_ai_server
from network_status import internet_access_allowed
from network_status import start_connectivity_monitor, stop_connectivity_monitor
from stt import transcribe
from thinking_comments import prepare_thinking_comments, start_comment
from tts import generate_speech_file, prepare_speech_cache, speak, speak_cached
from wake_word import (
    CONTINUOUS_CAPTURE_AFTER_WAKE,
    get_last_command_doa as get_last_continuous_command_doa,
    get_last_command_doa_diagnostic,
    get_last_command_capture_timing,
    get_last_wake_detected_at,
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


def acknowledge_wake_word(
    comment_cancel=None,
    comment_thread=None,
    command_timing=None,
):
    """Acknowledge a wake word, then listen once more without requiring it."""

    stop_thinking_comment(comment_cancel, comment_thread)
    response = random.choice(WAKE_ONLY_RESPONSES)
    print(f"👂 Wake word only — responding: {response}")
    set_emotion(EMOTION_LISTENING)
    speak_cached(response)

    while True:
        print("👂 Listening for a follow-up command...")
        audio = listen(wake_text="")
        if audio is None:
            break

        set_emotion(EMOTION_THINKING)
        if command_timing is not None:
            # The separate follow-up listener does not yet expose its final
            # active-audio timestamp; do not reuse the initial wake capture's
            # speech-end mark for this later recording.
            command_timing.marks.pop("command_speech_ended", None)
            command_timing.mark("command_capture_finished")
            command_timing.mark("stt_started")
        text = transcribe(audio)
        if command_timing is not None:
            command_timing.mark("stt_finished")
        if VERBOSE_RUNTIME_LOGS:
            print(f"🧪 Follow-up STT raw text: [{text}]")

        command = strip_wake_word(text) if text else ""
        if is_follow_up_cancel(command):
            print(f"👂 Follow-up ignored or canceled: {command}")
            break

        if command and not is_wake_word_only(command) and len(command.split()) >= 2:
            follow_up_bearing = get_last_command_doa()
            if (
                follow_up_bearing is not None
                and ENABLE_HEAD_TRACKING
                and not ENABLE_INTERACTION_DIAGNOSTIC
            ):
                from robot.head_tracking import head_tracker

                head_tracker.turn_toward_bearing(
                    follow_up_bearing,
                    source="follow-up command",
                )
            print(f"👂 Follow-up command received: {command}")
            if command_timing is not None:
                command_timing.reset_response_speech()
            return command

        if text and is_wake_word_only(command):
            print("👂 Repeated wake word — keeping command listener open")
            set_emotion(EMOTION_LISTENING)
            reset_idle_timer()
            continue

        if command:
            print(f"👂 Ignoring one-word follow-up: {command}")

        break

    print("⏱️ No follow-up command — returning to standby")
    set_emotion(EMOTION_STANDBY)
    reset_idle_timer()
    return None


def stop_thinking_comment(cancel_event, comment_thread):
    """Stop a pending or playing comment before the real response."""
    if cancel_event is None:
        return

    cancel_event.set()
    if comment_thread is not None:
        comment_thread.join(timeout=0.50)
        if comment_thread.is_alive():
            print("⚠️ Thinking comment did not stop promptly")


def finish_command_timing(command_timing, outcome="complete"):
    """Complete and print one optional interaction timing report."""
    if command_timing is None:
        return
    now = time.monotonic()
    if "processing_finished" not in command_timing.marks:
        command_timing.mark("processing_finished", now)
    command_timing.mark("response_finished", now)
    command_timing.report(outcome)
    clear_active_command_timing()


def log_speaker_output_sanity():
    """Print a quick, non-blocking speaker routing sanity check."""

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
        close_bible_display()
        stop_local_ai_server()

        if ENABLE_HEAD_TRACKING and not ENABLE_INTERACTION_DIAGNOSTIC:
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
    start_connectivity_monitor()
    prepare_thinking_comments()
    prepare_speech_cache(WAKE_ONLY_RESPONSES)

    internet_status = "online" if state.internet_connected else "offline"
    speak(f"Internet status: {internet_status}.")

    if not internet_access_allowed():
        try:
            start_local_ai_server()
        except (OSError, RuntimeError) as exc:
            print(f"⚠️ Local AI unavailable: {exc}")

    print("🤖 Ezra ready!\n")
    speak("Ezra ready!")
    log_speaker_output_sanity()
    interaction_count = 0

    try:
        while not state.shutting_down:

            # Wait for Ezra or Hey Ezra.
            wake_text, wake_audio = wait_for_wake_word_with_audio()

            command_timing = None
            if ENABLE_COMMAND_TIMING_DIAGNOSTIC:
                now = time.monotonic()
                command_timing = CommandTiming(get_last_wake_detected_at() or now)
                capture_timing = get_last_command_capture_timing()
                command_timing.mark(
                    "command_capture_finished",
                    capture_timing.get("capture_finished_at") or now,
                )
                speech_ended_at = capture_timing.get("speech_ended_at")
                if speech_ended_at is not None:
                    command_timing.mark("command_speech_ended", speech_ended_at)
                set_active_command_timing(command_timing)

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
                finish_command_timing(command_timing, "direction diagnostic")
                continue

            # ITEM TEST 3: wake_word.py has already applied any qualified wake
            # and post-wake command corrections. Report the resulting yaw and
            # re-arm without transcription or response processing.
            if ENABLE_HEAD_DIRECTION_DIAGNOSTIC:
                from robot.head_tracking import head_tracker

                direction = get_last_command_doa_diagnostic() or {}
                active_angle = direction.get("active_angle")
                settled_angle = direction.get("settled_angle")
                agreement = direction.get("settled_agreement")
                active_label = (
                    f"{active_angle:+.1f}°" if active_angle is not None else "n/a"
                )
                settled_label = (
                    f"{settled_angle:+.1f}°" if settled_angle is not None else "n/a"
                )
                agreement_label = (
                    f"{agreement:.1f}°" if agreement is not None else "n/a"
                )
                print(
                    "🧪 DOA CONFIDENCE | "
                    f"qualified={direction.get('qualified', False)} | "
                    f"samples={direction.get('sample_count', 0)} | "
                    f"active={direction.get('active_seconds', 0.0):.2f}s | "
                    f"cluster={direction.get('cluster_fraction', 0.0):.0%} | "
                    f"active bearing={active_label} | "
                    f"settled bearing={settled_label} | "
                    f"agreement={agreement_label} | "
                    f"reason={direction.get('reason', 'unavailable')}"
                )
                print(
                    f'🧪 HEAD DIRECTION TEST | Wake: "{wake_text}" | '
                    f"Final yaw: {head_tracker.current_yaw:+.1f}°"
                )
                set_emotion(EMOTION_STANDBY)
                reset_idle_timer()
                finish_command_timing(command_timing, "head diagnostic")
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
                    command = acknowledge_wake_word(command_timing=command_timing)
                    if command is None:
                        finish_command_timing(command_timing, "no command")
                        continue
                    command_was_transcribed = True
                    thinking_started_at = time.monotonic()

                # Convert the command audio to text.
                else:
                    set_emotion(EMOTION_THINKING)
                    # Record when processing began, but do not start a thinking
                    # comment until STT confirms that a command actually exists.
                    # Otherwise a wake-only interaction can say things such as
                    # "Give me a second" before the listening acknowledgement.
                    thinking_started_at = time.monotonic()
                    command_was_transcribed = True
                    if command_timing is not None:
                        command_timing.mark("stt_started")
                    text = transcribe(audio)
                    if command_timing is not None:
                        command_timing.mark("stt_finished")
                    if VERBOSE_RUNTIME_LOGS:
                        print(f"🧪 STT raw text: [{text}]")

                    command = strip_wake_word(text) if text else ""
                    if VERBOSE_RUNTIME_LOGS:
                        print(f"🧪 STT stripped command: [{command}]")

                    # A wake-only result gets one follow-up listening turn.
                    if not command or is_wake_word_only(command):
                        command = acknowledge_wake_word(
                            comment_cancel,
                            comment_thread,
                            command_timing,
                        )
                        comment_cancel = None
                        comment_thread = None
                        if command is None:
                            finish_command_timing(command_timing, "no command")
                            continue
                        thinking_started_at = time.monotonic()

            else:
                # Supports wake detection returning a full command.
                print(f"⚡ Direct command: {command}")
                # Save wake audio as debug WAV so playback diagnostic works.
                maybe_playback_diagnostic(wake_audio)

            # Ignore empty or unclear commands. In particular, do not send a
            # lone noise transcript from a false wake to the GPT conversation.
            if len(command) < 2 or is_unclear_single_word(command):
                print("⚠️ Ignoring short or unclear input")
                stop_thinking_comment(comment_cancel, comment_thread)
                set_emotion(EMOTION_STANDBY)
                reset_idle_timer()
                finish_command_timing(command_timing, "ignored command")
                continue

            print(f"📝 Command: {command}")
            if command_timing is not None:
                command_timing.mark("command_ready")

            # ITEM TEST 2: show the transcribed command, but do not execute it
            # or produce any response or head movement.
            if ENABLE_COMMAND_TEXT_DIAGNOSTIC:
                stop_thinking_comment(comment_cancel, comment_thread)
                display_command_text_diagnostic(command)
                reset_idle_timer()
                finish_command_timing(command_timing, "command-text diagnostic")
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

            if command_timing is not None:
                command_timing.mark("processing_started")
            if handle_local_command(command):
                if command_timing is not None:
                    command_timing.mark(
                        "processing_finished",
                        command_timing.speech_requested_at or time.monotonic(),
                    )
                # Spoken local commands return to standby when TTS finishes.
                # Silent commands, such as direct slide jumps or displaying
                # answers, need the same reset explicitly.
                set_emotion(EMOTION_STANDBY)
                # Run optional audio replay diagnostics after Ezra responds.
                maybe_playback_diagnostic()
                finish_command_timing(command_timing, "local command")
                continue

            # Send all other commands to Ezra's brain.
            if comment_cancel is None and not comment_was_started:
                comment_cancel = threading.Event()
                # Offline answers come from the local model. Avoid web-search
                # flavored filler such as "Let me see what I can find," and
                # keep an unavailable-local-model response immediate.
                if ENABLE_THINKING_COMMENTS and internet_access_allowed():
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

            streamed_speech_thread = None
            streamed_speech_interrupted = threading.Event()
            streamed_part_count = 0

            def speak_streamed_sentence(sentence):
                nonlocal comment_cancel, comment_thread
                nonlocal streamed_speech_thread, streamed_part_count
                stop_thinking_comment(comment_cancel, comment_thread)
                comment_cancel = None
                comment_thread = None
                if command_timing is not None and (
                    "processing_finished" not in command_timing.marks
                ):
                    command_timing.mark("processing_finished")

                streamed_part_count += 1
                if streamed_part_count == 1:
                    # Keep consuming the AI stream while the first sentence is
                    # spoken. This lets the model finish the remainder instead
                    # of blocking network reads for the duration of playback.
                    def play_first_part():
                        if command_timing is not None:
                            set_active_command_timing(command_timing)
                        try:
                            if speak(sentence):
                                streamed_speech_interrupted.set()
                        finally:
                            if command_timing is not None:
                                clear_active_command_timing()

                    streamed_speech_thread = threading.Thread(
                        target=play_first_part,
                        name="EzraStreamedSpeech",
                        daemon=True,
                    )
                    streamed_speech_thread.start()
                    return False

                # Piper can prepare the remainder while the first sentence is
                # still playing. Once playback ends, use that WAV immediately.
                with tempfile.TemporaryDirectory(
                    prefix="ezra-streamed-remainder-"
                ) as directory:
                    audio_path = Path(directory) / "remainder.wav"
                    prepared = generate_speech_file(sentence, audio_path)
                    streamed_speech_thread.join()
                    if streamed_speech_interrupted.is_set():
                        return True
                    return speak(
                        sentence,
                        audio_file=audio_path if prepared else None,
                    )

            try:
                result = ask_ezra(command, on_sentence=speak_streamed_sentence)
                if streamed_speech_thread is not None:
                    streamed_speech_thread.join()
                if streamed_speech_interrupted.is_set():
                    result["interrupted"] = True
                if command_timing is not None and (
                    "processing_finished" not in command_timing.marks
                ):
                    command_timing.mark("processing_finished")

            except InternetUnavailableError:
                stop_thinking_comment(comment_cancel, comment_thread)
                comment_cancel = None
                comment_thread = None
                set_emotion("confused")
                speak(
                    "Sorry, I'm not connected to the internet, "
                    "so I can't answer that."
                )
                reset_idle_timer()
                finish_command_timing(command_timing, "internet unavailable")
                continue
            except Exception as e:
                print(f"❌ Ezra brain error: {e}")

                set_emotion("confused")
                speak("I'm sorry. I had trouble answering that.")
                reset_idle_timer()
                finish_command_timing(command_timing, "AI error")
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
            if not result.get("streamed"):
                speak(response)

            if (
                not result.get("interrupted")
                and emotion in POST_RESPONSE_SMILE_EMOTIONS
            ):
                set_temporary_emotion(
                    "happy",
                    POST_RESPONSE_SMILE_SECONDS,
                    fallback_emotion=EMOTION_STANDBY,
                )

            # Run optional audio replay diagnostics after Ezra responds.
            maybe_playback_diagnostic()

            reset_idle_timer()
            finish_command_timing(command_timing)

    except KeyboardInterrupt:
        pass

    except Exception as e:
        print(f"\n❌ MAIN ERROR: {e}")

    finally:
        stop_connectivity_monitor()
        shutdown_robot()


# Run main only when this file is started directly.
if __name__ == "__main__":
    main()
