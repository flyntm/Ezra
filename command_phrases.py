"""Dependency-free recognition and responses for fixed local phrases."""

import re


def _explicit_request(command, action):
    """Match a complete instruction, never a keyword inside a question."""
    return bool(
        re.fullmatch(
            r"\s*(?:ezra[, ]+)?(?:please\s+)?"
            r"(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?"
            + action
            + r"(?:\s+now)?(?:\s+please)?[.!?]*\s*",
            str(command),
            re.IGNORECASE,
        )
    )


def looks_like_poweroff_command(command):
    return _explicit_request(
        command,
        r"(?:shutdown|shut down|power off|poweroff)"
        r"(?:\s+(?:the\s+)?(?:pi|raspberry pi|system|robot|ezra))?",
    )


def looks_like_quit_command(command):
    return _explicit_request(
        command,
        r"(?:(?:quit|exit)(?:\s+(?:the\s+)?(?:program(?:ming)?|application))?"
        r"|stop\s+(?:the\s+)?program(?:ming)?)",
    )


def looks_like_look_here_command(command):
    """Recognize an explicit request to face the person speaking."""
    return _explicit_request(command, r"(?:look (?:over here|here|at me)|face me)")


def looks_like_sleep_command(command):
    """Recognize a direct request to enter sleep mode."""
    return _explicit_request(
        command,
        r"(?:go to sleep|you(?:[' ]?re| are) going to sleep|that was to sleep|no just state)",
    )


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
