import string
import re

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

# Single words that are meaningful on their own. Other one-word transcripts
# are commonly coughs, filler, or wake-word handoff noise such as "pfft".
ACTIONABLE_SINGLE_WORD_COMMANDS = {
    "back",
    "cancel",
    "chancel",
    "explain",
    "exit",
    "forward",
    "goodbye",
    "next",
    "poweroff",
    "previous",
    "quit",
    "shutdown",
    "stop",
    "time",
    "why",
}


def is_cancel_command(command):
    """Return True when cancel or its common ASR variant ends the utterance."""

    words = re.findall(r"[a-z]+", command.lower())
    return bool(words and words[-1] in {"cancel", "chancel"})


def strip_wake_word(text):
    """Remove wake-word prefixes from recognized text."""

    if not text:
        return ""

    normalized = text.lower()
    # Keep separators between digits: Scripture references, ranges, decimals,
    # times and fractions lose their meaning when punctuation is deleted.
    normalized = re.sub(
        "[" + re.escape(string.punctuation) + "]",
        lambda match: (
            match.group()
            if (
                match.group() in ":-./"
                and match.start() > 0
                and match.end() < len(normalized)
                and normalized[match.start() - 1].isdigit()
                and normalized[match.end()].isdigit()
            )
            else ""
        ),
        normalized,
    )
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

    normalized = command.lower().translate(str.maketrans("", "", string.punctuation))
    return " ".join(normalized.split()) in FOLLOW_UP_CANCEL_PHRASES


def is_unclear_single_word(command):
    """Return whether a lone transcript is unlikely to be a real command."""

    normalized = command.lower().translate(str.maketrans("", "", string.punctuation))
    words = normalized.split()
    return len(words) == 1 and words[0] not in ACTIONABLE_SINGLE_WORD_COMMANDS
