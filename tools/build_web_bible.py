#!/usr/bin/env python3
"""Build Ezra's local WEB SQLite database from eBible.org chapter HTML."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3


CHAPTER_FILE = re.compile(r"^(?P<book>[1-3A-Z]{3})(?P<chapter>\d{2,3})\.htm$")


class ChapterParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main = False
        self.finished = False
        self.suppressed = 0
        self.verse_label_depth = 0
        self.current_verse = None
        self.current_text = []
        self.verses = []

    def _flush(self):
        if self.current_verse is None:
            return
        text = re.sub(r"\s+", " ", "".join(self.current_text)).strip()
        if text:
            self.verses.append((self.current_verse, text))
        self.current_verse = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "div" and "main" in classes:
            self.in_main = True
            return
        if not self.in_main or self.finished:
            return
        if tag == "ul" and "tnav" in classes and self.current_verse is not None:
            self._flush()
            self.finished = True
            return
        if self.verse_label_depth:
            self.verse_label_depth += 1
            return
        if self.suppressed:
            self.suppressed += 1
            return
        if classes.intersection({"notemark", "popup", "footnote", "copyright"}):
            self.suppressed = 1
            return
        if tag == "span" and "verse" in classes:
            verse_id = attributes.get("id", "")
            if verse_id.startswith("V") and verse_id[1:].isdigit():
                self._flush()
                self.current_verse = int(verse_id[1:])
                self.verse_label_depth = 1

    def handle_endtag(self, tag):
        if self.verse_label_depth:
            self.verse_label_depth -= 1
            return
        if self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data):
        if (
            self.in_main
            and not self.finished
            and not self.suppressed
            and not self.verse_label_depth
            and self.current_verse is not None
        ):
            self.current_text.append(data)

    def close(self):
        super().close()
        self._flush()


def parse_title(path):
    match = CHAPTER_FILE.match(path.name)
    if not match:
        return None
    raw = path.read_text(encoding="utf-8-sig")
    title_match = re.search(
        r"<title>World English Bible (.+?) (\d+)</title>", raw, re.IGNORECASE
    )
    if not title_match:
        # The archive contains front matter and glossary pages whose filenames
        # resemble chapter files but which are not Scripture chapters.
        return None
    parser = ChapterParser()
    parser.feed(raw)
    parser.close()
    return (
        match.group("book"),
        title_match.group(1),
        int(match.group("chapter")),
        parser.verses,
    )


def build_database(source, output):
    source = Path(source)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()

    with sqlite3.connect(temporary) as connection:
        connection.executescript(
            """
            CREATE TABLE verses (
                book_id TEXT NOT NULL,
                book_name TEXT NOT NULL,
                chapter INTEGER NOT NULL,
                verse INTEGER NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (book_id, chapter, verse)
            );
            CREATE INDEX verses_reference ON verses(book_id, chapter, verse);
            """
        )
        verse_count = 0
        chapter_count = 0
        books = set()
        for path in sorted(source.glob("*.htm")):
            parsed = parse_title(path)
            if parsed is None:
                continue
            book_id, book_name, chapter, verses = parsed
            books.add(book_id)
            chapter_count += 1
            connection.executemany(
                "INSERT INTO verses VALUES (?, ?, ?, ?, ?)",
                (
                    (book_id, book_name, chapter, verse, text)
                    for verse, text in verses
                ),
            )
            verse_count += len(verses)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    temporary.replace(output)
    return len(books), chapter_count, verse_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    books, chapters, verses = build_database(args.source, args.output)
    print(f"Built {args.output}: {books} books, {chapters} chapters, {verses} verses")


if __name__ == "__main__":
    main()
