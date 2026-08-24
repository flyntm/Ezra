"""Persist the active presentation position across service restarts."""

import json
import os
from pathlib import Path


STATE_PATH = Path(__file__).resolve().parent / ".runtime" / "presentation.json"


def save(deck_path, slide_number, revealed=False):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({
            "deck_path": str(Path(deck_path).resolve()),
            "slide_number": int(slide_number),
            "revealed": bool(revealed),
        }),
        encoding="utf-8",
    )
    os.replace(temporary, STATE_PATH)


def load():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not Path(state["deck_path"]).is_file():
            return None
        state["slide_number"] = int(state["slide_number"])
        state["revealed"] = bool(state.get("revealed", False))
        return state
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def clear():
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
