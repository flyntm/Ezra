"""Presentation material that can be reused at different events."""

import re

from .presenter import smile_and_pause, speak_with_head_motion

INTRODUCTION_OPENING = (
    "Hi, everyone! I'm Ezra, an A.I. entity and co-presenter. "
    "I'm powered by a Raspberry Pi with 8 gigabytes of memory and a "
    "128-gigabyte S.D. card for storage. I connect to the internet through "
    "Wi-Fi, and the software that brings me to life is written in Python and "
    "contains more than 5,000 lines of code. Those instructions help me "
    "listen, think, speak, show emotion, control my movements, answer "
    "questions and create hopefully useful responses. And it all fits inside "
    "this compact system which, let's be honest, looks very GOOFY!"
)

INTRODUCTION_WARNING = (
    "I should warn you though, sometimes I'm a little slow to respond and I'm "
    "still in development, so there's really no telling what might happen."
)

INTRODUCTION_CLOSING = (
    "Thanks for having me. I'm excited to be here!"
)

# Retain a complete text form for previews, tests, and other non-choreographed
# uses of the introduction.
INTRODUCTION = " ".join(
    (INTRODUCTION_OPENING, INTRODUCTION_WARNING, INTRODUCTION_CLOSING)
)

_INTRODUCTION_REQUEST = re.compile(
    r"\b(?:introduce yourself|tell (?:us|everyone) (?:about|who) you are)\b",
    re.IGNORECASE,
)


def is_introduction_request(command):
    """Return whether a command explicitly asks Ezra to introduce himself."""

    return bool(_INTRODUCTION_REQUEST.search(command))


def present_introduction(
    speak,
    smile=None,
    look_left=None,
    look_right=None,
    look_targets=None,
):
    """Deliver Ezra's introduction through existing speech and robot controls."""

    if speak_with_head_motion(
        speak,
        INTRODUCTION_OPENING,
        look_left=look_left,
        look_right=look_right,
        look_targets=look_targets,
    ):
        return True
    smile_and_pause(smile)
    if speak_with_head_motion(
        speak,
        INTRODUCTION_WARNING,
        look_left=look_right,
        look_right=look_left,
        look_targets=look_targets,
    ):
        return True
    smile_and_pause(smile)
    if speak(INTRODUCTION_CLOSING):
        return True
    smile_and_pause(smile)
    return False
