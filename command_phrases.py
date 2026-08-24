"""Dependency-free recognition and responses for fixed local phrases."""

import re


GOOD_NIGHT_PATTERN = (
    r"^\s*(?:(?:say\s+)?ezra[,.]?\s+)*(?:please\s+)?(?:say\s+)?good\s*night"
    r"(?:\s+to\s+everyone)?(?:\s+please)?[.!?]*\s*$"
)
GOOD_NIGHT_RESPONSE = (
    "[Humor]Good night to everyone. "
    "Thank you for letting me participate. Tonight, you almost made me feel "
    "human.[/Humor] [Smile]"
)


def looks_like_good_night_command(command):
    """Return True when Ezra is asked to wish everyone good night."""

    return bool(re.fullmatch(GOOD_NIGHT_PATTERN, command.lower()))
