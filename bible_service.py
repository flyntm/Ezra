"""Read exact Bible passages from online NIV with a local WEB fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
import html
from html.parser import HTMLParser
import os
import re
import sqlite3

import requests

from network_status import internet_access_allowed

from config import (
    API_BIBLE_BASE_URL,
    API_BIBLE_NIV_ID,
    API_BIBLE_TIMEOUT_SECONDS,
    BIBLE_MAX_SPOKEN_VERSES,
    ENABLE_BIBLE_PASSAGES,
    WEB_BIBLE_DATABASE,
)


load_dotenv(Path(__file__).parent / ".env", override=False)


@dataclass(frozen=True)
class BibleReference:
    book_id: str
    book_name: str
    chapter: int
    verse_start: int | None = None
    verse_end: int | None = None

    @property
    def display(self):
        if self.verse_start is None:
            return f"{self.book_name} {self.chapter}"
        if self.verse_end is None or self.verse_end == self.verse_start:
            return f"{self.book_name} {self.chapter}:{self.verse_start}"
        return (
            f"{self.book_name} {self.chapter}:"
            f"{self.verse_start}-{self.verse_end}"
        )

    @property
    def api_passage_id(self):
        if self.verse_start is None:
            return f"{self.book_id}.{self.chapter}"
        first = f"{self.book_id}.{self.chapter}.{self.verse_start}"
        if self.verse_end is None or self.verse_end == self.verse_start:
            return first
        return f"{first}-{self.book_id}.{self.chapter}.{self.verse_end}"


@dataclass(frozen=True)
class BiblePassage:
    reference: str
    text: str
    translation_name: str
    translation_abbreviation: str
    online: bool
    copyright: str = ""
    verses: tuple[tuple[int | str, str], ...] = ()


class SpokenBibleResponse(str):
    """Spoken passage text with structured verses for the visual display."""

    def __new__(cls, value, verses=(), tts_text=None):
        response = super().__new__(cls, value)
        response.verses = tuple(verses)
        response.tts_text = str(tts_text if tts_text is not None else value)
        return response


_BOOKS = (
    ("GEN", "Genesis", ()),
    ("EXO", "Exodus", ()),
    ("LEV", "Leviticus", ()),
    ("NUM", "Numbers", ()),
    ("DEU", "Deuteronomy", ()),
    ("JOS", "Joshua", ()),
    ("JDG", "Judges", ()),
    ("RUT", "Ruth", ()),
    ("1SA", "1 Samuel", ("first samuel",)),
    ("2SA", "2 Samuel", ("second samuel",)),
    ("1KI", "1 Kings", ("first kings",)),
    ("2KI", "2 Kings", ("second kings",)),
    ("1CH", "1 Chronicles", ("first chronicles",)),
    ("2CH", "2 Chronicles", ("second chronicles",)),
    ("EZR", "Ezra", ()),
    ("NEH", "Nehemiah", ()),
    ("EST", "Esther", ()),
    ("JOB", "Job", ()),
    ("PSA", "Psalms", ("psalm",)),
    ("PRO", "Proverbs", ()),
    ("ECC", "Ecclesiastes", ()),
    ("SNG", "Song of Solomon", ("song of songs",)),
    ("ISA", "Isaiah", ()),
    ("JER", "Jeremiah", ()),
    ("LAM", "Lamentations", ()),
    ("EZK", "Ezekiel", ()),
    ("DAN", "Daniel", ()),
    ("HOS", "Hosea", ()),
    ("JOL", "Joel", ()),
    ("AMO", "Amos", ()),
    ("OBA", "Obadiah", ()),
    ("JON", "Jonah", ()),
    ("MIC", "Micah", ()),
    ("NAM", "Nahum", ()),
    ("HAB", "Habakkuk", ()),
    ("ZEP", "Zephaniah", ()),
    ("HAG", "Haggai", ()),
    ("ZEC", "Zechariah", ()),
    ("MAL", "Malachi", ()),
    ("MAT", "Matthew", ()),
    ("MRK", "Mark", ()),
    ("LUK", "Luke", ()),
    ("JHN", "John", ()),
    ("ACT", "Acts", ()),
    ("ROM", "Romans", ()),
    ("1CO", "1 Corinthians", ("first corinthians",)),
    ("2CO", "2 Corinthians", ("second corinthians",)),
    ("GAL", "Galatians", ()),
    ("EPH", "Ephesians", ()),
    ("PHP", "Philippians", ()),
    ("COL", "Colossians", ()),
    ("1TH", "1 Thessalonians", ("first thessalonians",)),
    ("2TH", "2 Thessalonians", ("second thessalonians",)),
    ("1TI", "1 Timothy", ("first timothy",)),
    ("2TI", "2 Timothy", ("second timothy",)),
    ("TIT", "Titus", ()),
    ("PHM", "Philemon", ()),
    ("HEB", "Hebrews", ()),
    ("JAS", "James", ()),
    ("1PE", "1 Peter", ("first peter",)),
    ("2PE", "2 Peter", ("second peter",)),
    ("1JN", "1 John", ("first john",)),
    ("2JN", "2 John", ("second john",)),
    ("3JN", "3 John", ("third john",)),
    ("JUD", "Jude", ()),
    ("REV", "Revelation", ()),
)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "one hundred": 100,
    "one hundred nineteen": 119, "one hundred fifty": 150,
}


def _number(value):
    cleaned = re.sub(r"[-\s]+", " ", value.strip().lower())
    if cleaned.isdigit():
        return int(cleaned)
    if cleaned in _NUMBER_WORDS:
        return _NUMBER_WORDS[cleaned]
    parts = cleaned.split()
    if len(parts) == 2 and parts[0] in _NUMBER_WORDS and parts[1] in _NUMBER_WORDS:
        first, second = _NUMBER_WORDS[parts[0]], _NUMBER_WORDS[parts[1]]
        if first >= 20 and first % 10 == 0 and second < 10:
            return first + second
    if len(parts) == 3 and parts[:2] == ["one", "hundred"]:
        return 100 + _NUMBER_WORDS.get(parts[2], -100)
    return None


def _book_aliases():
    aliases = []
    for book_id, name, extra_aliases in _BOOKS:
        names = {name.lower(), *extra_aliases}
        if name[0].isdigit():
            ordinal = {"1": "first", "2": "second", "3": "third"}[name[0]]
            names.add(f"{ordinal}{name[1:]}")
        for alias in names:
            aliases.append((alias, book_id, name))
    return sorted(aliases, key=lambda item: len(item[0]), reverse=True)


_ALIASES = _book_aliases()
_NUMBER_PATTERN = r"(?:\d{1,3}|[a-z]+(?:[\s-]+[a-z]+){0,2})"


def _consume_number(text):
    digit_match = re.match(r"^(\d{1,3})\b", text)
    if digit_match:
        return int(digit_match.group(1)), text[digit_match.end():].strip()

    words = text.split()
    for size in range(min(3, len(words)), 0, -1):
        value = _number(" ".join(words[:size]))
        if value is not None:
            return value, " ".join(words[size:]).strip()
    return None, text


def parse_bible_reference(command):
    """Return an explicit Bible reference found in a spoken command."""

    normalized = re.sub(r"[,.?]", " ", command.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()

    for alias, book_id, book_name in _ALIASES:
        match = re.search(rf"\b{re.escape(alias)}\b", normalized)
        if not match:
            continue

        remainder = normalized[match.end():].strip()
        remainder = re.sub(r"^chapter\s+", "", remainder)
        chapter, tail = _consume_number(remainder)
        if chapter is None or chapter < 1:
            continue

        tail = re.sub(r"^(?::|verses?)\s*", "", tail)
        verse_start, range_tail = _consume_number(tail)
        if verse_start is None:
            return BibleReference(book_id, book_name, chapter)

        if verse_start < 1:
            return BibleReference(book_id, book_name, chapter)

        verse_end = None
        range_match = re.match(r"^(?:-|through|thru|to)\s*(.*)$", range_tail)
        if range_match:
            verse_end, _unused = _consume_number(range_match.group(1))

        if verse_end is not None and verse_end < verse_start:
            verse_end = None

        return BibleReference(
            book_id,
            book_name,
            chapter,
            verse_start,
            verse_end,
        )

    return None


def _clean_passage_text(value):
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class _VerseContentParser(HTMLParser):
    """Extract API.Bible verse boundaries without speaking their numbers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.verses = []
        self._number = None
        self._text_parts = []
        self._inside_number = False

    def _finish_verse(self):
        if self._number is None:
            return
        text = re.sub(r"\s+", " ", " ".join(self._text_parts)).strip()
        if text:
            self.verses.append((self._number, text))
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "span" and "v" in classes and attributes.get("data-number"):
            self._finish_verse()
            self._number = attributes["data-number"]
            self._inside_number = True

    def handle_endtag(self, tag):
        if tag == "span" and self._inside_number:
            self._inside_number = False

    def handle_data(self, data):
        if self._number is not None and not self._inside_number and data.strip():
            self._text_parts.append(data)

    def close(self):
        super().close()
        self._finish_verse()


def _parse_api_bible_verses(content):
    parser = _VerseContentParser()
    parser.feed(str(content))
    parser.close()
    return tuple(parser.verses)


class BibleService:
    def __init__(self, session=None, database_path=None):
        self.session = session or requests.Session()
        self.database_path = Path(database_path or WEB_BIBLE_DATABASE)
        self._niv_id = os.getenv("API_BIBLE_NIV_ID", API_BIBLE_NIV_ID).strip()

    @property
    def api_key(self):
        return os.getenv("API_BIBLE_KEY", "").strip()

    def _request(self, path, **kwargs):
        response = self.session.get(
            f'{API_BIBLE_BASE_URL.rstrip("/")}/{path.lstrip("/")}',
            headers={"api-key": self.api_key},
            timeout=API_BIBLE_TIMEOUT_SECONDS,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _resolve_niv_id(self):
        if self._niv_id:
            return self._niv_id
        payload = self._request("bibles", params={"language": "eng"})
        for bible in payload.get("data") or []:
            abbreviation = str(bible.get("abbreviation", "")).upper()
            name = str(bible.get("name", "")).lower()
            if abbreviation == "NIV" or "new international version" in name:
                self._niv_id = str(bible["id"])
                return self._niv_id
        raise RuntimeError("NIV is not enabled for this API.Bible account")

    def get_niv(self, reference):
        if not self.api_key:
            raise RuntimeError("API_BIBLE_KEY is not configured")
        bible_id = self._resolve_niv_id()
        payload = self._request(
            f"bibles/{bible_id}/passages/{reference.api_passage_id}",
            params={
                "content-type": "html",
                "include-notes": "false",
                "include-titles": "false",
                "include-chapter-numbers": "false",
                "include-verse-numbers": "true",
                "include-verse-spans": "true",
            },
        )
        data = payload["data"]
        content = data.get("content", "")
        verses = _parse_api_bible_verses(content)
        spoken_text = " ".join(text for _number, text in verses)
        if not spoken_text:
            spoken_text = _clean_passage_text(content)
        return BiblePassage(
            reference=data.get("reference") or reference.display,
            text=spoken_text,
            translation_name="New International Version",
            translation_abbreviation="NIV",
            online=True,
            copyright=str(data.get("copyright", "")).strip(),
            verses=verses,
        )

    def get_web(self, reference):
        if not self.database_path.exists():
            raise RuntimeError("Local World English Bible database is missing")
        end = reference.verse_end or reference.verse_start
        query = (
            "SELECT verse, text FROM verses "
            "WHERE book_id = ? AND chapter = ?"
        )
        parameters = [reference.book_id, reference.chapter]
        if reference.verse_start is not None:
            query += " AND verse BETWEEN ? AND ?"
            parameters.extend((reference.verse_start, end))
        query += " ORDER BY verse"

        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        if not rows:
            raise LookupError(f"Passage not found: {reference.display}")
        if len(rows) > BIBLE_MAX_SPOKEN_VERSES:
            rows = rows[:BIBLE_MAX_SPOKEN_VERSES]

        text = " ".join(verse_text for _verse, verse_text in rows)
        return BiblePassage(
            reference=reference.display,
            text=text,
            translation_name="World English Bible",
            translation_abbreviation="WEB",
            online=False,
            verses=tuple((verse, verse_text) for verse, verse_text in rows),
        )

    def get_passage(self, reference):
        if not internet_access_allowed():
            return self.get_web(reference), RuntimeError("offline test mode enabled")

        try:
            return self.get_niv(reference), None
        except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
            return self.get_web(reference), exc


_service = BibleService()
_last_reference = None


def get_bible_response(command, service=None):
    """Return a spoken exact-passage response, or None for non-references."""

    global _last_reference

    if not ENABLE_BIBLE_PASSAGES:
        return None

    normalized = re.sub(r"\s+", " ", command.lower()).strip()
    mentions_unnumbered_peter = (
        re.search(r"\bpeter\b", normalized) is not None
        and re.search(r"\b(?:1|2|first|second)\s+peter\b", normalized) is None
    )
    looks_like_passage_request = (
        re.search(r"\b(?:read|chapter|verse|verses)\b", normalized) is not None
    )
    if mentions_unnumbered_peter and looks_like_passage_request:
        return "Do you mean First Peter or Second Peter?"

    reference = parse_bible_reference(command)
    bookless_passage_request = (
        reference is None
        and re.search(r"\b(?:read|repeat)\b", normalized) is not None
        and re.search(r"\b(?:chapter|verse|verses)\b", normalized) is not None
    )
    if bookless_passage_request and _last_reference is not None:
        contextual_command = re.sub(
            r"\bchapter\b",
            f"{_last_reference.book_name} chapter",
            command,
            count=1,
            flags=re.IGNORECASE,
        )
        reference = parse_bible_reference(contextual_command)
    elif bookless_passage_request:
        return "Which book of the Bible would you like me to read?"

    if reference is None:
        return None

    selected_service = service or _service
    try:
        passage, online_error = selected_service.get_passage(reference)
    except (RuntimeError, LookupError, sqlite3.Error) as exc:
        print(f"⚠️ Bible passage lookup failed: {exc}")
        return "I couldn't find that Bible passage."

    if passage.online:
        prefix = f"{passage.reference}, from the NIV."
    else:
        if online_error is not None:
            print(f"ℹ️ NIV unavailable; using WEB: {online_error}")
        prefix = f"{passage.reference} from the World English Bible."
    _last_reference = reference
    return SpokenBibleResponse(
        f"{prefix} {passage.text}",
        verses=passage.verses,
        tts_text=f"{prefix} [Pause] {passage.text}",
    )
