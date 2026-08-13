"""PowerPoint deck inspection and speaker-note extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")


class PresentationError(RuntimeError):
    """Raised when a presentation cannot be opened or controlled."""


@dataclass(frozen=True)
class PowerPointDeck:
    """The slide count and speaker notes extracted from a pptx package."""

    path: Path
    notes: tuple[str, ...]

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
                notes = tuple(
                    _read_note(package, number) for number in slide_numbers
                )
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            raise PresentationError(
                f"Invalid PowerPoint file: {deck_path}"
            ) from exc

        if not notes:
            raise PresentationError(f"No slides found in: {deck_path}")
        return cls(deck_path, notes)


def _read_note(package, slide_number):
    name = f"ppt/notesSlides/notesSlide{slide_number}.xml"
    try:
        root = ET.fromstring(package.read(name))
    except KeyError:
        return ""

    paragraphs = []
    for paragraph in root.iter(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}p"
    ):
        text = "".join(
            node.text or ""
            for node in paragraph.iter(f"{{{_DRAWING_NS}}}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


class RehearsalSlideshow:
    """Non-GUI slideshow backend used by tests and script rehearsals."""

    def start(self):
        print("[slides] open slide 1")

    def next(self):
        print("[slides] next")

    def previous(self):
        print("[slides] previous")

    def reveal(self):
        print("[slides] reveal")

    def close(self):
        print("[slides] close")
