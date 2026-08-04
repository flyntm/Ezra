import string

from config import (
    WAKE_ONLY_PHRASES,
    WAKE_SECOND_WORD_VARIANTS,
    WAKE_WORD_ALIASES,
)

WAKE_WORDS = set(WAKE_WORD_ALIASES)
WAKE_SECOND_WORDS = WAKE_WORDS | set(WAKE_SECOND_WORD_VARIANTS)
WAKE_ONLY_SET = {p.lower().strip() for p in WAKE_ONLY_PHRASES}
FOLLOW_UP_CANCEL_PHRASES = {
    "ah",
    "cancel",
    "hmm",
    "never mind",
    "nevermind",
    "no",
    "no thanks",
    "no thank you",
    "nope",
    "nothing",
    "pfft",
    "stop",
    "thats all",
    "uh",
    "uh huh",
    "um",
}


def strip_wake_word(text):
    """Remove wake-word prefixes from recognized text."""

    if not text:
        return ""

    normalized = text.lower()
    normalized = normalized.translate(str.maketrans("", "", string.punctuation))
    normalized = normalized.strip()

    words = normalized.split()

    # Strip wake prefix up to twice to handle repeated/misheard wake phrases.
    for _ in range(2):
        # Whisper can hallucinate "hey ezra" as "here's what".
        if len(words) >= 2 and words[0] == "heres" and words[1] == "what":
            words = words[2:]
            continue

        # Remove "Hey Ezra" and common near-matches like "hey theres".
        if len(words) >= 2 and words[0] == "hey" and words[1] in WAKE_SECOND_WORDS:
            words = words[2:]
            continue

        # Remove a single wake word.
        if words and words[0] in WAKE_WORDS:
            words = words[1:]
            continue

        break

    return " ".join(words).strip()


def is_wake_word_only(command):
    """Check whether the recording contains only a wake phrase."""

    return command.lower().strip() in WAKE_ONLY_SET


def is_follow_up_cancel(command):
    """Return True for a declined follow-up or a noise/filler-only transcript."""

    normalized = command.lower().translate(
        str.maketrans("", "", string.punctuation)
    )
    return " ".join(normalized.split()) in FOLLOW_UP_CANCEL_PHRASES
