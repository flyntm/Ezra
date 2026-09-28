"""Shared Piper-only pronunciation substitutions."""

import re

from config import TTS_PRONUNCIATION_OVERRIDES


def apply_pronunciation_overrides(text):
    """Apply whole-word, case-insensitive respellings for Piper input."""
    spoken_text = str(text)

    for written, pronunciation in TTS_PRONUNCIATION_OVERRIDES.items():
        pattern = rf"(?<!\w){re.escape(written)}(?!\w)"
        spoken_text = re.sub(
            pattern,
            lambda _match, replacement=pronunciation: replacement,
            spoken_text,
            flags=re.IGNORECASE,
        )

    return spoken_text
