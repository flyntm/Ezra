"""Retrieve lesson, speaker-note, and Scripture context for Ezra's answers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

from bible_service import BibleService, parse_bible_reference
from config import WEB_BIBLE_DATABASE


PRESENTATIONS_DIR = Path(__file__).parent / "presentations"
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?", re.IGNORECASE)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do",
    "does", "for", "from", "how", "i", "in", "is", "it", "of", "on",
    "or", "that", "the", "this", "to", "was", "were", "what", "when",
    "where", "which", "who", "why", "with", "you",
}
_material_cache = None
_material_signature = None
_pending_context = []
_pending_question = None
_MORE_REQUEST = re.compile(
    r"^(?:ezra[,.]?\s*)?(?:please\s+)?(?:tell|show|give)\s+"
    r"(?:us|me)?\s*more\b",
    re.IGNORECASE,
)
_OWN_EXPLANATION_REQUEST = re.compile(
    r"\b(?:"
    r"(?:give|tell)\s+(?:us|me)\s+(?:your\s+)?(?:own\s+)?"
    r"(?:broader\s+)?(?:non[- ]?scriptural\s+)?explanation"
    r"|(?:answer|explain)\s+(?:this\s+)?(?:more\s+)?broadly"
    r"|outside\s+(?:of\s+)?scripture"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextChunk:
    source: str
    label: str
    text: str


def _terms(text):
    return {
        word.casefold()
        for word in _WORD.findall(str(text))
        if len(word) > 2 and word.casefold() not in _STOP_WORDS
    }


def _score(question, text):
    query_terms = _terms(question)
    if not query_terms:
        return 0
    text_terms = _terms(text)
    overlap = query_terms & text_terms
    return sum(2 if len(term) >= 7 else 1 for term in overlap)


def _jsonl_chunks(directory):
    chunks = []
    for path in sorted(Path(directory).glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            print(f"[lesson-context] could not read {path.name}: {exc}")
            continue
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"[lesson-context] skipping invalid JSON in {path.name}:"
                    f"{line_number}: {exc.msg}"
                )
                continue
            if isinstance(item, str):
                text = item
                metadata = {}
            elif isinstance(item, dict):
                text = next(
                    (str(item[key]) for key in ("text", "content", "page_content")
                     if item.get(key)),
                    "",
                )
                metadata = item.get("metadata") or {}
            else:
                continue
            if not text.strip():
                continue
            title = metadata.get("title") if isinstance(metadata, dict) else None
            label = str(title or path.stem)
            chunks.append(ContextChunk("study book", label, text.strip()))
    return chunks


def _lesson_material(directory):
    """Cache parsed files, while noticing additions and edits automatically."""
    global _material_cache, _material_signature
    directory = Path(directory)
    paths = sorted(directory.glob("*.jsonl"))
    signature = tuple(
        (path, path.stat().st_mtime_ns, path.stat().st_size) for path in paths
    )
    if signature != _material_signature:
        _material_cache = _jsonl_chunks(directory)
        _material_signature = signature
    return list(_material_cache or ())


def _scripture_chunks(question, database_path):
    path = Path(database_path)
    if not path.is_file():
        return []

    reference = parse_bible_reference(question)
    if reference is not None:
        try:
            passage = BibleService(database_path=path).get_web(reference)
        except (LookupError, RuntimeError, sqlite3.Error):
            return []
        return [ContextChunk("Scripture", passage.reference, passage.text)]

    # For topical questions, search individual verses in the local Bible and
    # return only unusually strong lexical matches. This keeps unrelated verses
    # out of the model prompt when the question is ordinary conversation.
    query_terms = _terms(question)
    if len(query_terms) < 2:
        return []
    try:
        with sqlite3.connect(path) as connection:
            rows = connection.execute(
                "SELECT book_name, chapter, verse, text FROM verses"
            ).fetchall()
    except sqlite3.Error:
        return []
    ranked = sorted(
        ((_score(question, row[3]), row) for row in rows),
        key=lambda item: item[0],
        reverse=True,
    )
    minimum = max(3, len(query_terms) // 2)
    return [
        ContextChunk("Scripture", f"{book} {chapter}:{verse}", text)
        for score, (book, chapter, verse, text) in ranked[:2]
        if score >= minimum
    ]


def retrieve_context(
    question,
    directory=PRESENTATIONS_DIR,
    database_path=WEB_BIBLE_DATABASE,
    max_chunks=5,
    max_chars=3000,
):
    """Return the most relevant labeled context without requiring embeddings."""
    lesson_material = _lesson_material(directory)
    ranked = sorted(
        ((_score(question, chunk.text), chunk) for chunk in lesson_material),
        key=lambda item: item[0],
        reverse=True,
    )
    scripture = _scripture_chunks(question, database_path)
    if parse_bible_reference(question) is not None:
        # An explicitly requested passage is authoritative for that request.
        selected = scripture + [chunk for score, chunk in ranked if score > 0]
    else:
        # For topical questions, let Scripture and study-book material
        # compete on relevance instead of favoring a merely incidental match.
        selected = [
            chunk
            for score, chunk in sorted(
                [*ranked, *((_score(question, chunk.text), chunk) for chunk in scripture)],
                key=lambda item: item[0],
                reverse=True,
            )
            if score > 0
        ]
    selected = selected[:max_chunks]

    result = []
    used = 0
    for chunk in selected:
        remaining = max_chars - used
        if remaining <= 0:
            break
        text = chunk.text[:remaining].strip()
        if text:
            result.append(ContextChunk(chunk.source, chunk.label, text))
            used += len(text)
    return result


def _answer_prompt(question, chunks, more_available, continuation=False):
    evidence = "\n\n".join(
        f"[Source: {chunk.source}; {chunk.label}]\n{chunk.text}"
        for chunk in chunks
    )
    ending = (
        'End the response with the exact sentence "There is more."'
        if more_available
        else "Do not say there is more."
    )
    opening = (
        f'Continue your answer to the earlier question: "{question}"'
        if continuation
        else question
    )
    return f"""{opening}

Use only the evidence below for this part of the answer. Give the single most
relevant point in no more than two short sentences. Naturally identify whether
it comes from the study book or Scripture. If you add an inference, identify it
as your own explanation. {ending}

{evidence}"""


def augment_question(question):
    """Attach one stage of evidence and retain later evidence for follow-ups."""
    global _pending_context, _pending_question

    if _OWN_EXPLANATION_REQUEST.search(str(question)):
        _pending_context = []
        _pending_question = None
        return f"""{question}

The user explicitly wants a broader, non-scriptural response. Do not use the
study book, Scripture retrieval, or speaker notes for this answer. Answer from
general knowledge and reasoning, begin naturally with "My own explanation is",
and keep the answer to no more than two short sentences."""

    if _MORE_REQUEST.search(str(question).strip()) and _pending_context:
        chunks = [_pending_context.pop(0)]
        return _answer_prompt(
            _pending_question,
            chunks,
            more_available=bool(_pending_context),
            continuation=True,
        )

    chunks = retrieve_context(question)
    if not chunks:
        _pending_context = []
        _pending_question = None
        return question
    _pending_question = str(question)
    _pending_context = list(chunks[1:])
    return _answer_prompt(
        _pending_question,
        [chunks[0]],
        more_available=bool(_pending_context),
    )
