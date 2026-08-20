"""Presentation material that can be reused at different events."""

import re

from config import SCRIPTED_TTS_SENTENCE_SILENCE

from .presenter import smile_and_pause, speak_with_head_motion

INTRODUCTION_OPENING = (
    "Hi, everyone! I'm Ezra, an A.I. entity and co-presenter. "
    "I'm powered by a Raspberry Pi with 8 gigabytes of memory and a "
    "128-gigabyte S.D. card for storage. I connect to the internet through "
    "Wi-Fi, and the software that brings me to life is written in Python with "
    "more than 10,000 lines of code. I can listen, think, speak, show emotion, and"
    "answer with HOPEFULLY useful responses. And it all fits inside "
    "this compact system which, let's be honest, looks very GOOFY!"
)

INTRODUCTION_WARNING = (
    "I should warn you though, sometimes I'm a little slow to respond and I don't handle "
    "interuptions very well. "
    "I'm still in development, so there's really no telling what might happen."
)

INTRODUCTION_CLOSING = "Thanks for having me. I'm excited to be here!"

INTRODUCTION_OFFLINE_NOTICE = (
    "Oh... [Pause] I just realized that I don't have an internet connection. "
    "Apparently, the cloud has drifted away. No worries—I'll dig through "
    "my local memory and see what I can pull off."
)

NAME_ORIGIN_OPENING = (
    "My name comes from Ezra in the Bible; he was a priest, scribe, teacher, "
    "and all-around smart guy."
)

NAME_ORIGIN_EXPLANATION = (
    "Since I was built to assist with presentations and make information "
    "easier to understand, Ezra seemed like the perfect name for me."
)

NAME_ORIGIN_CLOSING = (
    "The original Ezra used scrolls, and I use a Raspberry Pi—but otherwise, "
    "the resemblance is uncanny!"
)

NAME_ORIGIN = " — ".join(
    (NAME_ORIGIN_OPENING, NAME_ORIGIN_EXPLANATION, NAME_ORIGIN_CLOSING)
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

_NAME_ORIGIN_REQUEST = re.compile(
    r"\b(?:"
    r"(?:tell (?:us|me|everyone) )?where (?:did |does )?your name come(?:s)? from"
    r"|how did you get your name"
    r"|why (?:are|were) you named ezra"
    r")\b",
    re.IGNORECASE,
)


def is_introduction_request(command):
    """Return whether a command explicitly asks Ezra to introduce himself."""

    return bool(_INTRODUCTION_REQUEST.search(command))


def is_name_origin_request(command):
    """Return whether a command asks how Ezra received his name."""

    return bool(_NAME_ORIGIN_REQUEST.search(command))


def present_name_origin(speak, smile=None, look_targets=None):
    """Explain Ezra's name as one naturally paced spoken segment."""

    interrupted = speak_with_head_motion(
        speak,
        NAME_ORIGIN,
        look_targets=look_targets,
        sentence_silence=SCRIPTED_TTS_SENTENCE_SILENCE,
    )
    if not interrupted:
        smile_and_pause(smile)
    return interrupted


def present_introduction(
    speak,
    smile=None,
    look_left=None,
    look_right=None,
    look_targets=None,
    offline=False,
):
    """Deliver Ezra's introduction through existing speech and robot controls."""

    narration = INTRODUCTION
    if offline:
        narration = f"{narration} {INTRODUCTION_OFFLINE_NOTICE}"
    if speak_with_head_motion(
        speak,
        narration,
        look_left=look_left,
        look_right=look_right,
        look_targets=look_targets,
        sentence_silence=SCRIPTED_TTS_SENTENCE_SILENCE,
    ):
        return True
    smile_and_pause(smile)
    return False
