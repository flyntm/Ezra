"""Resolve Bible reading instructions embedded in narration scripts."""

import re

from bible_service import get_bible_response, parse_bible_reference

_READ_MARKER = re.compile(r"\[Read\b([^\]]*)\]", re.IGNORECASE)
_REFERENCE = re.compile(
    r"\s*(?P<book>(?:[1-3]\s+)?[A-Za-z]+(?:\s+[A-Za-z]+)*)\s+"
    r"(?P<chapter>\d+)\s*:\s*(?P<start>\d+)"
    r"(?:\s*[-–:]\s*(?P<end>\d+))?\s*\.?\s*"
)


def expand_bible_readings(text, cancel_event=None, readings=None):
    """Insert sourced passage text in place of each [Read Book C:V-V] marker."""
    def expand(match):
        if cancel_event is not None and cancel_event.is_set():
            return ""
        reference_match = _REFERENCE.fullmatch(match.group(1))
        if reference_match is None:
            return " I couldn't read that Bible reference. "
        book, chapter, start, end = reference_match.group('book', 'chapter', 'start', 'end')
        if min(int(chapter), int(start)) < 1 or (end is not None and int(end) < int(start)):
            return " I couldn't read that Bible reference. "
        reference = f"{book} {chapter}:{start}" + (f"-{end}" if end else "")
        if parse_bible_reference(reference) is None:
            return " I couldn't read that Bible reference. "
        response = get_bible_response(f"Read {reference}")
        if cancel_event is not None and cancel_event.is_set():
            return ""
        if response is None:
            return " Bible reading is unavailable. "
        spoken = getattr(response, 'tts_text', response)
        if readings is not None:
            from bible_display import split_passage_response

            content = split_passage_response(response)
            if content is not None:
                index = len(readings)
                readings.append(content)
                return f" [BibleStart{index}] {spoken} [BibleEnd] "
        return f" {spoken} "

    return _READ_MARKER.sub(expand, str(text))


class ScriptBibleDisplay:
    """Temporarily cover the slide with a passage, closing it at its boundary."""

    def __init__(self, readings):
        self.readings = readings
        self.display = None
        self.started = False

    def open(self, index):
        from bible_display import BibleDisplay
        from config import ENABLE_BIBLE_DISPLAY

        self.close()
        if not ENABLE_BIBLE_DISPLAY:
            return
        display = BibleDisplay(*self.readings[index])
        try:
            display.start()
        except (OSError, RuntimeError) as exc:
            display.close()
            print(f"⚠️ Bible display unavailable: {exc}")
            return
        self.display = display
        self.started = False

    def begin_reading(self):
        if self.display is not None and not self.started:
            self.display.begin_reading()
            self.started = True

    def close(self):
        display, self.display = self.display, None
        if display is not None:
            display.stop_reading()
            display.close()
