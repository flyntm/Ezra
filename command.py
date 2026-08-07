"""Handle commands that can be answered without Ezra's GPT brain."""

from datetime import datetime
import re
import subprocess

import state

from config import GOODBYE_TEXT
from live_info import get_live_info_response
from presentations import is_introduction_request, present_introduction
from tts import speak
from wake_word import reset_idle_timer

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
POWEROFF_PATTERN = r"\b(?:shutdown|shut down|power off|poweroff)\b"
QUIT_PROGRAM_PATTERN = r"\b(?:quit|exit|stop|quit program|stop program|exit program)\b"


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


def looks_like_poweroff_command(command):
    """Return True for shutdown intent phrasing."""

    return bool(re.search(POWEROFF_PATTERN, command.lower()))


def looks_like_quit_command(command):
    """Return True for app-exit intent phrasing."""

    return bool(re.search(QUIT_PROGRAM_PATTERN, command.lower()))


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

    if looks_like_quit_command(command):
        speak(GOODBYE_TEXT)
        state.shutting_down = True
        return True

    if looks_like_poweroff_command(command):
        speak("Shutting down now.")
        state.shutting_down = True

        if request_system_poweroff():
            return True

        print("⚠️ System shutdown command failed")
        speak("I couldn't shut down the system.")
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
        audience_bearings = (
            -48.0,
            -35.0,
            -22.0,
            -10.0,
            0.0,
            12.0,
            25.0,
            38.0,
            50.0,
        )
        look_targets = [
            lambda target=target: head_tracker.turn_toward_bearing(
                target - head_tracker.current_yaw,
                source="presentation",
                step_delay_seconds=0.05,
                announce=False,
            )
            for target in audience_bearings
        ]

        present_introduction(
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

    live_info_response = get_live_info_response(text_lower)
    if live_info_response:
        speak(live_info_response)
        reset_idle_timer()
        return True

    return False
