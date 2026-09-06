"""Track whether Ezra is answering generally or from presentation material."""

import threading
import re


GENERAL = "general"
PRESENTATION = "presentation"
_VALID_MODES = {GENERAL, PRESENTATION}

_mode = GENERAL
_lock = threading.Lock()
_GENERAL_PATTERN = re.compile(
    r"\b(?:switch|change|go|return|set)(?:\s+back)?\s+to\s+"
    r"(?:the\s+)?general\s+mode\b|\benter\s+(?:the\s+)?general\s+mode\b",
    re.IGNORECASE,
)
_PRESENTATION_PATTERN = re.compile(
    r"\b(?:switch|change|go|set)\s+to\s+(?:the\s+)?presentation\s+mode\b"
    r"|\benter\s+(?:the\s+)?presentation\s+mode\b",
    re.IGNORECASE,
)
_STATUS_PATTERN = re.compile(
    r"\b(?:what|which)\s+mode\s+(?:are\s+you|is\s+ezra)\s+in\b"
    r"|\bwhat(?:'s|\s+is)\s+(?:your|the)\s+(?:current\s+)?mode\b",
    re.IGNORECASE,
)


def get_mode():
    """Return the current operating mode."""

    with _lock:
        return _mode


def set_mode(mode):
    """Set and return the current operating mode."""

    normalized = str(mode).strip().lower()
    if normalized not in _VALID_MODES:
        raise ValueError(f"Unknown operating mode: {mode}")

    global _mode
    with _lock:
        _mode = normalized
    print(f"[mode] {normalized}")
    return normalized


def presentation_context_enabled():
    """Return whether study-book and Scripture retrieval is enabled."""

    return get_mode() == PRESENTATION


def requested_mode(command):
    """Return an explicitly requested mode, or None for another command."""

    if _GENERAL_PATTERN.search(str(command)):
        return GENERAL
    if _PRESENTATION_PATTERN.search(str(command)):
        return PRESENTATION
    return None


def status_requested(command):
    """Return whether the user asked which operating mode is active."""

    return bool(_STATUS_PATTERN.search(str(command)))
