"""Handle commands that can be answered without Ezra's GPT brain."""

from datetime import datetime
import re
import subprocess
import time

import state
import operating_mode

from bible_display import (
    close_bible_display,
    scroll_active_bible_display,
    show_bible_passage,
    split_passage_response,
)
from bible_service import get_bible_response
from command_phrases import (
    GOOD_NIGHT_RESPONSE,
    looks_like_good_night_command,
    looks_like_poweroff_command,
    looks_like_quit_command,
    looks_like_look_here_command,
    looks_like_sleep_command,
)
from command_normalization import is_cancel_command
from config import ENABLE_BIBLE_DISPLAY, GOODBYE_TEXT, SHUTDOWN_SLEEP_SETTLE_SECONDS
from live_info import get_live_info_response
from network_status import internet_access_allowed
from presentations import (
    handle_presentation_command,
    is_introduction_request,
    is_name_origin_request,
    is_presentation_request,
    is_rehearsal_request,
    present_introduction,
    present_name_origin,
    requested_start_slide,
    start_presentation,
)
from presentations.powerpoint import PresentationError
from presentations.presenter import (
    NARROW_AUDIENCE_BEARINGS,
    audience_look_targets,
)
from tts import speak
from wake_word import enter_sleep, reset_idle_timer, wake_up

VOLUME_WORDS = {
    "one": 1,
    "won": 1,
    "two": 2,
    "too": 2,
    "to": 2,
    "three": 3,
    "four": 4,
    "for": 4,
    "forward": 4,
    "floor": 4,
    "five": 5,
    "fire": 5,
    "fife": 5,
    "that": 5,
    "flat": 5,
    "back": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "ate": 8,
    "nine": 9,
    "ten": 10,
}

VOLUME_WORD_PATTERN = r"\b(?:volume|volumes|value|vol|aim|bomb)\b"
VOLUME_FILLER_WORDS = {"to", "at", "on", "of", "the", "a"}


def parse_volume_level(command):
    """Return a requested volume level from 1 to 10, or None."""

    text = command.lower()

    if not re.search(VOLUME_WORD_PATTERN, text):
        return None

    match = re.search(
        rf"{VOLUME_WORD_PATTERN}(?:\s+(?:to|at|on|of))?\s+(\d{{1,2}})\b",
        text,
    )

    if match:
        return int(match.group(1))

    words = text.split()

    for index, word in enumerate(words):
        if not re.fullmatch(VOLUME_WORD_PATTERN, word):
            continue

        candidates = words[index + 1 : index + 5]

        for candidate in candidates:
            candidate = candidate.strip(".,!?;:")

            if candidate in VOLUME_FILLER_WORDS:
                continue
            if candidate in VOLUME_WORDS:
                return VOLUME_WORDS[candidate]

    return None


def set_system_volume(level):
    """Set default PipeWire output volume using a 1-10 voice scale."""

    percent = level * 10

    subprocess.run(
        ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def looks_like_volume_command(command):
    """Return True for clear volume commands and common STT mishears."""

    text = command.lower()

    if re.search(r"\b(?:volume|volumes|value|vol)\b", text):
        return True

    if re.search(r"\bset\b", text) and re.search(r"\b(?:aim|bomb)\b", text):
        return True

    if re.search(r"\bshut\b", text) and re.search(r"\bbomb\b", text):
        return True

    return False


def request_system_poweroff():
    """Attempt system poweroff without blocking on a sudo password prompt."""

    commands = [
        ["sudo", "-n", "poweroff"],
        ["poweroff"],
    ]

    for cmd in commands:
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    return False


def handle_local_command(command):
    """Handle a command locally, returning whether it was handled."""

    text_lower = command.lower()

    if is_cancel_command(text_lower):
        reset_idle_timer()
        return True

    if looks_like_sleep_command(command):
        speak("Going to sleep.")
        enter_sleep()
        return True

    if looks_like_look_here_command(command):
        from config import ENABLE_HEAD_TRACKING, ENABLE_INTERACTION_DIAGNOSTIC

        if not ENABLE_HEAD_TRACKING or ENABLE_INTERACTION_DIAGNOSTIC:
            speak("Head tracking is disabled.")
        else:
            from robot.head_tracking import head_tracker

            if not head_tracker.face_command_speaker():
                speak("I couldn't turn toward you. Please say look over here again.")
        reset_idle_timer()
        return True

    if operating_mode.status_requested(command):
        current_mode = operating_mode.get_mode()
        speak(f"I'm in {current_mode.title()} mode.")
        reset_idle_timer()
        return True

    requested_mode = operating_mode.requested_mode(command)
    if requested_mode is not None:
        operating_mode.set_mode(requested_mode)
        speak(f"{requested_mode.title()} mode.")
        reset_idle_timer()
        return True

    scroll_match = re.search(
        r"\b(?:scroll|roll|show)\s+(up|down)\b",
        text_lower,
    )
    if scroll_match and scroll_active_bible_display(scroll_match.group(1)):
        reset_idle_timer()
        return True

    if handle_presentation_command(command, speak):
        reset_idle_timer()
        return True

    if is_rehearsal_request(command) or is_presentation_request(command):
        try:
            if is_presentation_request(command):
                close_bible_display()
            start_presentation(
                speak,
                rehearsal=is_rehearsal_request(command),
                slide_number=requested_start_slide(command),
            )
        except PresentationError as exc:
            print(f"⚠️ Presentation failed: {exc}")
            speak(f"I couldn't start the presentation. {exc}")
        reset_idle_timer()
        return True

    if looks_like_quit_command(command):
        speak(GOODBYE_TEXT)
        state.exit_requested = True
        state.shutting_down = True
        return True

    if looks_like_poweroff_command(command):
        speak("See ya later.")
        enter_sleep()
        time.sleep(SHUTDOWN_SLEEP_SETTLE_SECONDS)

        if request_system_poweroff():
            state.shutting_down = True
            return True

        print("⚠️ System shutdown command failed")
        wake_up()
        speak("I couldn't shut down the system.")
        return True

    if looks_like_good_night_command(command):
        speak(GOOD_NIGHT_RESPONSE)
        reset_idle_timer()
        return True

    if looks_like_volume_command(command):
        volume_level = parse_volume_level(command)

        if volume_level is None or not 1 <= volume_level <= 10:
            speak("Please choose a volume from one to ten.")
            reset_idle_timer()
            return True

        try:
            set_system_volume(volume_level)
            speak(f"Volume set to {volume_level}.")
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            print(f"⚠️ Volume command failed: {e}")
            speak("I couldn't change the volume.")

        reset_idle_timer()
        return True

    if is_introduction_request(command):
        # Keep presentation-only hardware hooks lazy so normal startup and
        # every existing command retain their previous behavior.
        from ezra_emotion import set_temporary_emotion
        from robot.head_tracking import head_tracker

        # Treat these bearings as different people spread across the audience.
        # The presenter shuffles them and varies how long Ezra holds each gaze.
        look_targets = audience_look_targets(head_tracker)

        present_introduction(
            speak,
            smile=lambda seconds: set_temporary_emotion("happy", seconds),
            look_targets=look_targets,
            offline=not internet_access_allowed(),
        )
        head_tracker.center()
        reset_idle_timer()
        return True

    if is_name_origin_request(command):
        from ezra_emotion import set_temporary_emotion
        from robot.head_tracking import head_tracker

        look_targets = audience_look_targets(
            head_tracker,
            NARROW_AUDIENCE_BEARINGS,
        )

        present_name_origin(
            speak,
            smile=lambda seconds: set_temporary_emotion("happy", seconds),
            look_targets=look_targets,
        )
        head_tracker.center()
        reset_idle_timer()
        return True

    if "what time" in text_lower or "time is it" in text_lower:
        now = datetime.now().strftime("%I:%M %p")
        speak(f"It is {now}")
        reset_idle_timer()
        return True

    bible_response = get_bible_response(command)
    if bible_response:
        display_request = re.search(
            r"\b(?:show|display(?:ing)?|just playing)\b", text_lower
        )
        display_content = split_passage_response(bible_response)
        if display_request:
            if not ENABLE_BIBLE_DISPLAY:
                speak("Bible passage display is disabled.")
            elif display_content is None:
                speak(bible_response)
            else:
                try:
                    show_bible_passage(*display_content, read_along=False)
                    speak(f"Displaying {display_content[0]}.")
                except (OSError, RuntimeError) as exc:
                    print(f"⚠️ Bible display unavailable: {exc}")
                    speak("I couldn't display that Bible passage.")
            reset_idle_timer()
            return True

        bible_display = None
        if ENABLE_BIBLE_DISPLAY and display_content is not None:
            try:
                bible_display = show_bible_passage(*display_content)
            except (OSError, RuntimeError) as exc:
                print(f"⚠️ Bible display unavailable: {exc}")
        speak(
            getattr(bible_response, "tts_text", bible_response),
            on_playback_start=(
                bible_display.begin_reading if bible_display is not None else None
            ),
            on_playback_complete=(
                bible_display.finish_reading if bible_display is not None else None
            ),
            on_playback_end=(
                bible_display.stop_reading if bible_display is not None else None
            ),
        )
        reset_idle_timer()
        return True

    live_info_response = get_live_info_response(text_lower)
    if live_info_response:
        speak(live_info_response)
        reset_idle_timer()
        return True

    return False
