"""Cancelable, cached personality comments for the AI thinking interval."""

import hashlib
import os
from pathlib import Path
import random
import subprocess
import threading
import time

from config import (
    ENABLE_THINKING_COMMENTS,
    SPEAKER_DEVICE,
    THINKING_COMMENTS,
    TTS_LENGTH_SCALE,
    TTS_MODEL_PATH,
    TTS_SENTENCE_SILENCE,
)
from ezra_emotion import set_talk_level
from mouth_sync import build_mouth_envelope
from tts import generate_speech_file


_CACHE_DIR = Path(__file__).parent / ".cache" / "thinking_comments"
_cached_comments = []


def _cache_path(text):
    identity = (
        f"{TTS_MODEL_PATH}|{TTS_LENGTH_SCALE}|"
        f"{TTS_SENTENCE_SILENCE}|{text}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return _CACHE_DIR / f"{digest}.wav"


def prepare_thinking_comments():
    """Prepare persistent WAVs before Ezra begins accepting interactions."""
    global _cached_comments
    _cached_comments = []
    if not ENABLE_THINKING_COMMENTS:
        return

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for text in THINKING_COMMENTS:
        path = _cache_path(text)
        if path.exists() or generate_speech_file(text, path):
            _cached_comments.append((text, path))

    if not _cached_comments:
        print("⚠️ Thinking comments unavailable")


def play_random_comment_until(cancel_event):
    """Play one cached comment; callers decide whether it should be canceled."""
    if not _cached_comments or cancel_event.is_set():
        return

    text, path = random.choice(_cached_comments)
    print(f"💭 Ezra: {text}")
    try:
        envelope, frame_seconds = build_mouth_envelope(os.fspath(path))
    except Exception:
        envelope = None
        frame_seconds = 0.04

    cmd = ["aplay", os.fspath(path)]
    if SPEAKER_DEVICE is not None:
        cmd[1:1] = ["-D", str(SPEAKER_DEVICE)]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        print(f"⚠️ Thinking comment playback failed: {e}")
        return

    started_at = time.monotonic()
    try:
        while proc.poll() is None:
            if cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            if envelope is not None and len(envelope):
                index = min(
                    len(envelope) - 1,
                    int((time.monotonic() - started_at) / frame_seconds),
                )
                set_talk_level(float(envelope[index]))
            time.sleep(0.02)
    finally:
        set_talk_level(0.0)


def start_comment(cancel_event, delay_seconds=0.0):
    started_event = threading.Event()

    def delayed_playback():
        if cancel_event.wait(max(0.0, float(delay_seconds))):
            return
        started_event.set()
        play_random_comment_until(cancel_event)

    thread = threading.Thread(
        target=delayed_playback,
        name="EzraThinkingComment",
        daemon=True,
    )
    thread.comment_started_event = started_event
    thread.start()
    return thread
