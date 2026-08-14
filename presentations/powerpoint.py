"""PowerPoint deck inspection and speaker-note extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_NEXT_SLIDE_MARKERS = ("[NEXT SLIDE]", "[Next Slide]")
_QUESTION_LABEL = re.compile(r"\bQ\s*(\d+)\b", re.IGNORECASE)


class PresentationError(RuntimeError):
    """Raised when a presentation cannot be opened or controlled."""


@dataclass(frozen=True)
class PowerPointDeck:
    """The slide count and speaker notes extracted from a pptx package."""

    path: Path
    notes: tuple[str, ...]
    auto_advance: tuple[bool, ...]
    reveal_slides: tuple[bool, ...]
    question_numbers: tuple[int | None, ...]

    @property
    def slide_count(self):
        return len(self.notes)

    @classmethod
    def load(cls, path):
        deck_path = Path(path).expanduser().resolve()
        if not deck_path.is_file():
            raise PresentationError(f"Presentation not found: {deck_path}")

        try:
            with zipfile.ZipFile(deck_path) as package:
                slide_numbers = sorted(
                    int(match.group(1))
                    for name in package.namelist()
                    if (match := _SLIDE_RE.match(name))
                )
                parsed_notes = tuple(
                    _read_note(package, number) for number in slide_numbers
                )
                notes = tuple(note for note, _ in parsed_notes)
                auto_advance = tuple(requested for _, requested in parsed_notes)
                reveal_slides = tuple(
                    _has_reveal_content(package, number)
                    for number in slide_numbers
                )
                question_numbers = tuple(
                    _read_question_number(package, number)
                    for number in slide_numbers
                )
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise PresentationError(
                f"Invalid PowerPoint file: {deck_path}"
            ) from exc

        if not notes:
            raise PresentationError(f"No slides found in: {deck_path}")
        return cls(
            deck_path,
            notes,
            auto_advance,
            reveal_slides,
            question_numbers,
        )


def _read_note(package, slide_number):
    name = f"ppt/notesSlides/notesSlide{slide_number}.xml"
    try:
        root = ET.fromstring(package.read(name))
    except KeyError:
        return "", False

    paragraphs = []
    auto_advance = False
    for paragraph in root.iter(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}p"
    ):
        text = "".join(
            node.text or ""
            for node in paragraph.iter(f"{{{_DRAWING_NS}}}t")
        ).strip()
        sources_position = text.casefold().find("[sources]")
        sources_found = sources_position >= 0
        if sources_found:
            text = text[:sources_position].strip()
        for marker in _NEXT_SLIDE_MARKERS:
            if marker in text:
                auto_advance = True
                text = text.replace(marker, "")
        text = text.strip()
        if text:
            paragraphs.append(text)
        if sources_found:
            break
    return "\n".join(paragraphs), auto_advance


def _has_reveal_content(package, slide_number):
    root = ET.fromstring(package.read(f"ppt/slides/slide{slide_number}.xml"))
    for identity in root.iter(f"{{{_PRESENTATION_NS}}}cNvPr"):
        if identity.get("name", "").startswith("answer-"):
            return True
    return False


def _read_question_number(package, slide_number):
    root = ET.fromstring(package.read(f"ppt/slides/slide{slide_number}.xml"))
    visible_text = " ".join(
        node.text or "" for node in root.iter(f"{{{_DRAWING_NS}}}t")
    )
    match = _QUESTION_LABEL.search(visible_text)
    return int(match.group(1)) if match else None


class RehearsalSlideshow:
    """Non-GUI slideshow backend used by tests and script rehearsals."""

    def start(self):
        print("[slides] open slide 1")

    def next(self):
        print("[slides] next")

    def previous(self):
        print("[slides] previous")

    def go_to(self, slide_index):
        print(f"[slides] show slide {slide_index + 1}")

    def reveal(self):
        print("[slides] reveal")

    def close(self):
        print("[slides] close")
