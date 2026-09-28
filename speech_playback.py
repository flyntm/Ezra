"""Shared pause state for browser, terminal, and Pi keyboard controls."""

import threading
import time

_lock = threading.Lock()
_active_stop = None
_paused = False
_last_toggle = float('-inf')


def begin(stop_event):
    global _active_stop, _paused, _last_toggle
    with _lock:
        _active_stop = stop_event
        _paused = False
        _last_toggle = float('-inf')


def end(stop_event):
    global _active_stop, _paused
    with _lock:
        if _active_stop is stop_event:
            _active_stop = None
            _paused = False


def toggle():
    """Ignore idle presses and duplicate delivery through multiple listeners."""
    global _paused, _last_toggle
    with _lock:
        now = time.monotonic()
        if (_active_stop is None or _active_stop.is_set()
                or now - _last_toggle < 0.25):
            return
        _paused = not _paused
        _last_toggle = now


def is_paused(stop_event):
    with _lock:
        return _active_stop is stop_event and _paused and not stop_event.is_set()
