"""Runtime and spoken material for the Acts lesson-one prototype."""

from __future__ import annotations

from pathlib import Path
import re

from .browser_slideshow import BrowserSlideshow
from .powerpoint import PowerPointDeck, PresentationError, RehearsalSlideshow


DECK_PATH = Path(__file__).with_name("acts-lesson-one-prototype.pptx")

SLIDE_SCRIPTS = (
    (
        "Acts is the only New Testament book devoted to the early years of "
        "the church, but Luke is not attempting to record everything that "
        "happened or to trace every apostle. Acts is the second part of the "
        "work he began in his Gospel, and both volumes are addressed to "
        "Theophilus. Luke selects people and events that help us see the "
        "gospel moving outward: from Jerusalem, into Judea and Samaria, into "
        "the wider Gentile world, and finally to Rome. The main idea is "
        "continuity. Jesus' ministry did not simply stop at the ascension. "
        "Acts presents the risen Jesus continuing his work through the Holy "
        "Spirit and through his followers."
    ),
    (
        "Our first question is this: What was Luke trying to provide? Look "
        "closely at Luke chapter one, verses one through four. What does Luke "
        "say that Luke and Acts are meant to be? Take a moment to discuss it."
    ),
)

REVEAL_SCRIPT = (
    "Luke says he is preparing an orderly account. The material came through "
    "eyewitnesses and servants of the word, and Luke carefully investigated "
    "the events from the beginning. He wrote so Theophilus could have "
    "confidence and certainty about what he had been taught."
)

_START_PATTERN = re.compile(
    r"\b(?:start|begin|open|present|run)\b.*\b(?:acts|presentation|lesson)\b",
    re.IGNORECASE,
)
_REHEARSE_PATTERN = re.compile(
    r"\b(?:rehearse|preview|test)\b.*\b(?:acts|presentation|lesson)\b",
    re.IGNORECASE,
)
_STOP_PATTERN = re.compile(
    r"\b(?:stop|end|close|quit)\b.*\b(?:presentation|lesson)\b",
    re.IGNORECASE,
)
_NEXT_PATTERN = re.compile(r"\b(?:next|forward)\b(?:\s+slide)?\b", re.IGNORECASE)
_PREVIOUS_PATTERN = re.compile(
    r"\b(?:previous|back)\b(?:\s+slide)?\b", re.IGNORECASE
)
_REVEAL_PATTERN = re.compile(
    r"\b(?:reveal|show)\b.*\b(?:answer|response)\b", re.IGNORECASE
)


class ActsLessonOneSession:
    """A small state machine that keeps slides and narration synchronized."""

    def __init__(self, speak, slideshow=None):
        self.speak = speak
        self.deck = PowerPointDeck.load(DECK_PATH)
        if self.deck.slide_count != len(SLIDE_SCRIPTS):
            raise PresentationError(
                f"Deck has {self.deck.slide_count} slides but "
                f"{len(SLIDE_SCRIPTS)} scripts are configured"
            )
        self.slideshow = slideshow or BrowserSlideshow(self.deck.path)
        self.slide_index = 0
        self.answer_revealed = False
        self.active = False

    def start(self):
        self.slideshow.start()
        self.active = True
        return self._speak_current()

    def _speak_current(self):
        interrupted = bool(self.speak(SLIDE_SCRIPTS[self.slide_index]))
        if interrupted:
            self.stop()
        return interrupted

    def next(self):
        self._require_active()
        if self.slide_index >= self.deck.slide_count - 1:
            self.speak("This is the final slide.")
            return False
        self.slideshow.next()
        self.slide_index += 1
        return self._speak_current()

    def previous(self):
        self._require_active()
        if self.slide_index == 0:
            self.speak("This is the first slide.")
            return False
        self.slideshow.previous()
        self.slide_index -= 1
        self.answer_revealed = False
        return self._speak_current()

    def reveal(self):
        self._require_active()
        if self.slide_index != 1:
            self.speak("There is no answer to reveal on this slide.")
            return False
        if self.answer_revealed:
            self.speak("The response has already been revealed.")
            return False
        self.slideshow.reveal()
        self.answer_revealed = True
        return bool(self.speak(REVEAL_SCRIPT))

    def stop(self):
        if self.active:
            self.slideshow.close()
        self.active = False

    def _require_active(self):
        if not self.active:
            raise PresentationError("No presentation is currently active")


_session = None


def is_start_request(command):
    return bool(_START_PATTERN.search(command))


def is_rehearsal_request(command):
    return bool(_REHEARSE_PATTERN.search(command))


def has_active_presentation():
    return _session is not None and _session.active


def start_presentation(speak, rehearsal=False):
    global _session
    if has_active_presentation():
        _session.stop()
    backend = RehearsalSlideshow() if rehearsal else None
    rehearsal_speak = (
        (lambda text: print(f"[Ezra] {text}") or False)
        if rehearsal
        else speak
    )
    _session = ActsLessonOneSession(rehearsal_speak, backend)
    _session.start()
    if rehearsal:
        _session.next()
        _session.reveal()
        _session.stop()


def handle_active_command(command, speak):
    global _session
    patterns = (_STOP_PATTERN, _NEXT_PATTERN, _PREVIOUS_PATTERN, _REVEAL_PATTERN)
    if not any(pattern.search(command) for pattern in patterns):
        return False
    if not has_active_presentation():
        speak("There is no active presentation.")
        return True
    try:
        if _STOP_PATTERN.search(command):
            _session.stop()
            _session = None
            speak("Presentation stopped.")
            return True
        if _NEXT_PATTERN.search(command):
            _session.next()
            return True
        if _PREVIOUS_PATTERN.search(command):
            _session.previous()
            return True
        if _REVEAL_PATTERN.search(command):
            _session.reveal()
            return True
    except PresentationError as exc:
        speak(str(exc))
        return True
    return False


def rehearse_all():
    session = ActsLessonOneSession(
        lambda text: print(f"[Ezra] {text}") or False,
        RehearsalSlideshow(),
    )
    session.start()
    session.next()
    session.reveal()
    session.stop()


if __name__ == "__main__":
    rehearse_all()
