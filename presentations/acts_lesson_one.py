"""Runtime and spoken material for the Acts lesson-one prototype."""

from __future__ import annotations

from pathlib import Path
import re
import threading

from config import PRESENTATION_TTS_CHUNK_MAX_CHARS

from .browser_slideshow import BrowserSlideshow
from .powerpoint import PowerPointDeck, PresentationError, RehearsalSlideshow
from .presenter import speak_with_head_motion


DECK_PATH = Path(__file__).with_name("Lesson_One_Acts.pptx")

_START_PATTERN = re.compile(
    r"\b(?:start|begin|open|present|run)\b.*\b(?:acts|presentation|lesson)\b",
    re.IGNORECASE,
)
_START_SLIDE_PATTERN = re.compile(
    r"\b(?:start|begin|open|run)\s+(?:the\s+)?presentation\s+"
    r"(?:on|at|from|with)\s+slide(?:\s+number)?\s+"
    r"(?P<number>\d{1,3}|[a-z]+(?:[\s-]+[a-z]+){0,2})"
    r"(?:\s+please)?[.!?]?$",
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
    r"\b(?:reveal|show)\b.*\b(?:answers?|responses?)\b"
    r"|\bthe\s+answers\s+please\b",
    re.IGNORECASE,
)
_DISPLAY_ANSWERS_PATTERN = re.compile(
    r"\bdisplay\b.*\b(?:answers?|responses?)\b", re.IGNORECASE
)
_NARRATE_PATTERN = re.compile(
    r"\b(?:please\s+)?tell\s+(?:us|me)\s+about\s+(?:this|the)\s+slide\b",
    re.IGNORECASE,
)
_QUESTION_JUMP_PATTERN = re.compile(
    r"\b(?:show|go\s+to|display)\s+(?:us\s+)?(?:the\s+)?question\s+"
    r"(?P<number>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_SLIDE_JUMP_PATTERN = re.compile(
    r"\bgo\s+to\s+(?:the\s+)?slide(?:\s+number)?\s+"
    r"(?P<number>\d{1,3}|[a-z]+(?:[\s-]+[a-z]+){0,2})"
    r"(?:\s+please)?[.!?]?$",
    re.IGNORECASE,
)
_SMALL_NUMBER_WORDS = {
    "one": 1,
    "first": 1,
    "two": 2,
    "second": 2,
    "three": 3,
    "third": 3,
    "four": 4,
    "fourth": 4,
    "five": 5,
    "fifth": 5,
    "six": 6,
    "sixth": 6,
    "seven": 7,
    "seventh": 7,
    "eight": 8,
    "eighth": 8,
    "nine": 9,
    "ninth": 9,
    "ten": 10,
    "tenth": 10,
    "eleven": 11,
    "eleventh": 11,
    "twelve": 12,
    "twelfth": 12,
    "thirteen": 13,
    "thirteenth": 13,
    "fourteen": 14,
    "fourteenth": 14,
    "fifteen": 15,
    "fifteenth": 15,
    "sixteen": 16,
    "sixteenth": 16,
    "seventeen": 17,
    "seventeenth": 17,
    "eighteen": 18,
    "eighteenth": 18,
    "nineteen": 19,
    "nineteenth": 19,
}
_TENS_NUMBER_WORDS = {
    "twenty": 20,
    "twentieth": 20,
    "thirty": 30,
    "thirtieth": 30,
    "forty": 40,
    "fortieth": 40,
    "fifty": 50,
    "fiftieth": 50,
    "sixty": 60,
    "sixtieth": 60,
    "seventy": 70,
    "seventieth": 70,
    "eighty": 80,
    "eightieth": 80,
    "ninety": 90,
    "ninetieth": 90,
}
_CARDINAL_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _parse_slide_number(value):
    text = value.lower().replace("-", " ").strip()
    if text.endswith(" please"):
        text = text.removesuffix(" please").strip()
    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 100 else None
    if text in ("one hundred", "one hundredth", "hundred", "hundredth"):
        return 100
    if text in _SMALL_NUMBER_WORDS:
        return _SMALL_NUMBER_WORDS[text]
    if text in _TENS_NUMBER_WORDS:
        return _TENS_NUMBER_WORDS[text]
    words = text.split()
    if len(words) == 2 and words[0] in _TENS_NUMBER_WORDS:
        ones = _SMALL_NUMBER_WORDS.get(words[1])
        tens = _TENS_NUMBER_WORDS[words[0]]
        if ones is not None and ones < 10 and tens % 10 == 0:
            return tens + ones
    return None


class ActsLessonOneSession:
    """A small state machine that keeps slides and narration synchronized."""

    def __init__(
        self,
        speak,
        slideshow=None,
        look_targets=None,
        center_head=None,
    ):
        self.speak = speak
        self.look_targets = look_targets
        self.center_head = center_head
        self.deck = PowerPointDeck.load(DECK_PATH)
        slides_without_notes = [
            str(number)
            for number, note in enumerate(self.deck.notes, 1)
            if not note.strip()
        ]
        if slides_without_notes:
            raise PresentationError(
                "Speaker notes are missing from slide"
                + ("s " if len(slides_without_notes) > 1 else " ")
                + ", ".join(slides_without_notes)
            )
        self.slideshow = slideshow or BrowserSlideshow(self.deck.path)
        self.slide_index = 0
        self.answer_revealed = False
        self.active = False

    def start(self, slide_number=1):
        self.slideshow.start()
        self.active = True
        if slide_number != 1:
            self.go_to(slide_number)
        return self._speak_current()

    def _speak_current(self):
        slide_number = self.slide_index + 1
        automatic = self.deck.auto_advance[self.slide_index]
        playback_complete = threading.Event()
        print(
            f"[presentation] slide={slide_number} "
            f"automatic_advance={automatic}"
        )

        def speech_started():
            print(f"[presentation] slide={slide_number} speech_start")

        def speech_completed():
            print(f"[presentation] slide={slide_number} speech_complete")
            playback_complete.set()

        try:
            interrupted = speak_with_head_motion(
                self.speak,
                self.deck.notes[self.slide_index],
                look_targets=self.look_targets,
                on_playback_start=speech_started,
                on_playback_complete=speech_completed,
                allow_keyboard_skip=True,
                presentation_skip_event=getattr(
                    self.slideshow, "skip_event", None
                ),
                chunk_max_chars=PRESENTATION_TTS_CHUNK_MAX_CHARS,
            )
        finally:
            if self.center_head is not None:
                self.center_head()
        if interrupted:
            print(
                f"[presentation] slide={slide_number} "
                "speech_interrupted=True presentation_active=True"
            )
            return interrupted

        if automatic and playback_complete.is_set():
            if self.slide_index < self.deck.slide_count - 1:
                self.slide_index += 1
                self.slideshow.go_to(self.slide_index)
                self.answer_revealed = False
                if self.deck.reveal_slides[self.slide_index]:
                    self.slideshow.reveal()
                    self.answer_revealed = True
                print(
                    f"[presentation] slide={slide_number} "
                    f"advancement_command=next resulting_slide={self.slide_index + 1}"
                )
                return self._speak_current()
            else:
                print(
                    f"[presentation] slide={slide_number} "
                    "advancement_command=none reason=final_slide"
                )
        elif automatic:
            print(
                f"[presentation] slide={slide_number} "
                "advancement_command=none reason=playback_incomplete"
            )
        return interrupted

    def next(self):
        self._require_active()
        if self.slide_index >= self.deck.slide_count - 1:
            self.speak("This is the final slide.")
            return False
        self.slide_index += 1
        self.slideshow.go_to(self.slide_index)
        self.answer_revealed = False
        if self.deck.reveal_slides[self.slide_index]:
            self.slideshow.reveal()
            self.answer_revealed = True
        print(
            f"[presentation] navigation_command=next "
            f"resulting_slide={self.slide_index + 1}"
        )
        return self._speak_current()

    def previous(self):
        self._require_active()
        if self.slide_index == 0:
            self.speak("This is the first slide.")
            return False
        self.slide_index -= 1
        self.slideshow.go_to(self.slide_index)
        self.answer_revealed = False
        if self.deck.reveal_slides[self.slide_index]:
            self.slideshow.reveal()
            self.answer_revealed = True
        print(
            f"[presentation] navigation_command=previous "
            f"resulting_slide={self.slide_index + 1}"
        )
        return False

    def go_to(self, slide_number):
        """Display a numbered slide without reading its script."""
        self._require_active()
        if not 1 <= slide_number <= self.deck.slide_count:
            raise PresentationError(
                f"This presentation has {self.deck.slide_count} slides."
            )
        self.slideshow.go_to(slide_number - 1)
        self.slide_index = slide_number - 1
        self.answer_revealed = False
        if self.deck.reveal_slides[self.slide_index]:
            self.slideshow.reveal()
            self.answer_revealed = True

    def narrate_current(self):
        """Read the script for the slide that is currently displayed."""
        self._require_active()
        return self._speak_current()

    def go_to_question(self, question_number):
        """Display a labeled question slide regardless of its slide number."""
        self._require_active()
        for index, number in enumerate(self.deck.question_numbers):
            if number == question_number and not self.deck.reveal_slides[index]:
                self.slideshow.go_to(index)
                self.slide_index = index
                self.answer_revealed = False
                return
        raise PresentationError(
            f"Question {question_number} was not found in this presentation."
        )

    def reveal(self, read_script=True):
        self._require_active()
        if not self.deck.reveal_slides[self.slide_index]:
            next_index = self.slide_index + 1
            if (
                next_index < self.deck.slide_count
                and self.deck.reveal_slides[next_index]
            ):
                self.slide_index = next_index
                self.slideshow.go_to(self.slide_index)
                self.answer_revealed = False
            else:
                self.speak("There is no answer to reveal on this slide.")
                return False
        if self.answer_revealed:
            self.speak("The response has already been revealed.")
            return False
        self.slideshow.reveal()
        self.answer_revealed = True
        if read_script:
            return self._speak_current()
        return False

    def stop(self):
        if self.active:
            self.slideshow.close()
        self.active = False

    def _require_active(self):
        if not self.active:
            raise PresentationError("No presentation is currently active")


_session = None


def _rehearsal_speak(text, **callbacks):
    callbacks.get("on_playback_start", lambda: None)()
    print(f"[Ezra] {text}")
    callbacks.get("on_playback_complete", lambda: None)()
    return False


def is_start_request(command):
    return bool(_START_PATTERN.search(command))


def is_rehearsal_request(command):
    return bool(_REHEARSE_PATTERN.search(command))


def requested_start_slide(command):
    match = _START_SLIDE_PATTERN.search(command)
    if not match:
        return 1
    number = _parse_slide_number(match.group("number"))
    if number is None:
        raise PresentationError("Please choose a slide number from 1 through 100.")
    return number


def has_active_presentation():
    return _session is not None and _session.active


def start_presentation(speak, rehearsal=False, slide_number=1):
    global _session
    if has_active_presentation():
        _session.stop()
    backend = RehearsalSlideshow() if rehearsal else None
    rehearsal_speak = _rehearsal_speak if rehearsal else speak
    look_targets = None
    center_head = None
    if not rehearsal:
        # Aim at a varied set of audience positions while each slide's speaker
        # notes are being read. Default arguments bind each bearing separately.
        from robot.head_tracking import head_tracker

        audience_bearings = (-48.0, -35.0, -22.0, -10.0, 0.0, 12.0, 25.0, 38.0, 50.0)
        look_targets = [
            lambda target=target: head_tracker.turn_toward_bearing(
                target - head_tracker.current_yaw,
                source="presentation",
                step_delay_seconds=0.05,
                announce=False,
            )
            for target in audience_bearings
        ]
        center_head = head_tracker.center
    _session = ActsLessonOneSession(
        rehearsal_speak,
        backend,
        look_targets=look_targets,
        center_head=center_head,
    )
    _session.start(slide_number=slide_number)
    if rehearsal:
        while _session.slide_index < _session.deck.slide_count - 1:
            _session.next()
            if _session.deck.reveal_slides[_session.slide_index]:
                _session.reveal()
        _session.stop()


def handle_active_command(command, speak):
    global _session
    jump_match = _SLIDE_JUMP_PATTERN.search(command)
    question_jump_match = _QUESTION_JUMP_PATTERN.search(command)
    patterns = (
        _STOP_PATTERN,
        _NEXT_PATTERN,
        _PREVIOUS_PATTERN,
        _REVEAL_PATTERN,
        _DISPLAY_ANSWERS_PATTERN,
        _NARRATE_PATTERN,
    )
    if not question_jump_match and not jump_match and not any(
        pattern.search(command) for pattern in patterns
    ):
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
        if question_jump_match:
            matched_number = question_jump_match.group("number").lower()
            question_number = (
                int(matched_number)
                if matched_number.isdigit()
                else _CARDINAL_WORDS[matched_number]
            )
            _session.go_to_question(question_number)
            return True
        if jump_match:
            slide_number = _parse_slide_number(jump_match.group("number"))
            if slide_number is None:
                raise PresentationError(
                    "Please choose a slide number from 1 through 100."
                )
            _session.go_to(slide_number)
            return True
        if _REVEAL_PATTERN.search(command):
            _session.reveal()
            return True
        if _DISPLAY_ANSWERS_PATTERN.search(command):
            _session.reveal(read_script=False)
            return True
        if _NARRATE_PATTERN.search(command):
            _session.narrate_current()
            return True
    except PresentationError as exc:
        speak(str(exc))
        return True
    return False


def rehearse_all():
    session = ActsLessonOneSession(
        _rehearsal_speak,
        RehearsalSlideshow(),
    )
    session.start()
    while session.slide_index < session.deck.slide_count - 1:
        session.next()
        if session.deck.reveal_slides[session.slide_index]:
            session.reveal()
    session.stop()


if __name__ == "__main__":
    rehearse_all()
