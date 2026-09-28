"""PowerPoint deck inspection and speaker-note extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import posixpath
import xml.etree.ElementTree as ET
import zipfile


_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NEXT_SLIDE_MARKER = re.compile(r"\[next slide\]", re.IGNORECASE)
_QUESTION_LABEL = re.compile(r"\bQ\s*(\d+)\b", re.IGNORECASE)


class PresentationError(RuntimeError):
    """Raised when a presentation cannot be opened or controlled."""


def part_relationships(package, part):
    directory, name = posixpath.split(part)
    path = posixpath.join(directory, "_rels", name + ".rels")
    try:
        root = ET.fromstring(package.read(path))
    except KeyError:
        return {}
    relationships = {}
    for node in root:
        if node.get("TargetMode") == "External":
            continue
        target = node.get("Target", "")
        target = posixpath.normpath(target.lstrip("/") if target.startswith("/")
                                   else posixpath.join(directory, target))
        if target.startswith("../"):
            raise PresentationError("Invalid PowerPoint relationship target")
        relationships[node.get("Id")] = (node.get("Type", ""), target)
    return relationships


def ordered_slide_parts(package):
    """Read the presentation's logical order, independent of part filenames."""
    try:
        root = ET.fromstring(package.read("ppt/presentation.xml"))
        relationships = part_relationships(package, "ppt/presentation.xml")
        parts = []
        for node in root.findall(f"{{{_PRESENTATION_NS}}}sldIdLst/{{{_PRESENTATION_NS}}}sldId"):
            kind, target = relationships[node.attrib[f"{{{_RELATIONSHIP_NS}}}id"]]
            if not kind.endswith("/slide"):
                raise PresentationError("Invalid slide relationship")
            parts.append(target)
        return parts
    except KeyError as exc:
        raise PresentationError("PowerPoint slide relationships are missing") from exc


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
                slide_parts = ordered_slide_parts(package)
                parsed_notes = tuple(
                    _read_note(package, part) for part in slide_parts
                )
                notes = tuple(note for note, _ in parsed_notes)
                auto_advance = tuple(requested for _, requested in parsed_notes)
                reveal_slides = tuple(
                    _has_reveal_content(package, part)
                    for part in slide_parts
                )
                question_numbers = tuple(
                    _read_question_number(package, part)
                    for part in slide_parts
                )
        except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
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


def _read_note(package, slide_part):
    name = next((target for kind, target in part_relationships(package, slide_part).values()
                 if kind.endswith("/notesSlide")), None)
    if name is None:
        return "", False
    root = ET.fromstring(package.read(name))

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
        text, marker_count = _NEXT_SLIDE_MARKER.subn("", text)
        if marker_count:
            auto_advance = True
        text = text.strip()
        if text:
            paragraphs.append(text)
        if sources_found:
            break
    return "\n".join(paragraphs), auto_advance


def _has_reveal_content(package, slide_part):
    root = ET.fromstring(package.read(slide_part))
    for identity in root.iter(f"{{{_PRESENTATION_NS}}}cNvPr"):
        if identity.get("name", "").startswith("answer-"):
            return True
    return False


def _read_question_number(package, slide_part):
    root = ET.fromstring(package.read(slide_part))
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
