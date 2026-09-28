"""Coordinate immediate listener state and queued browser navigation.

HTTP handlers may toggle wake listening immediately, but only the main thread
executes navigation or starts speech after closing its microphone stream.
"""

from collections import deque
import threading

_lock = threading.RLock()
_requests = deque()
_listening_enabled = True
_listening_revision = 0


def listening_status():
    with _lock:
        return _listening_enabled, _listening_revision


def listening_enabled():
    with _lock:
        return _listening_enabled


def toggle_listening():
    global _listening_enabled, _listening_revision
    with _lock:
        _listening_enabled = not _listening_enabled
        _listening_revision += 1
        enabled = _listening_enabled
    print(f"🎤 Wake-word listening {'ON' if enabled else 'OFF'}")
    return enabled


def submit(session, action):
    with _lock:
        if not session.active:
            return
        session._navigation_changed()
        skip = getattr(session.slideshow, "skip_event", None)
        if skip is not None:
            skip.set()
        if action == "skip":
            discard(session)
        else:
            _requests.append((session, action))


def discard(session):
    with _lock:
        retained = [request for request in _requests if request[0] is not session]
        _requests.clear()
        _requests.extend(retained)


def pending():
    with _lock:
        return bool(_requests)


def begin_narration(session, generation):
    with _lock:
        if generation != session._navigation_generation or any(
            owner is session for owner, _ in _requests
        ):
            return False
        skip = getattr(session.slideshow, "skip_event", None)
        if skip is not None:
            skip.clear()
        return True


def process_pending():
    """Called only by main, after wake/follow-up capture has closed."""
    with _lock:
        requests = list(_requests)
        _requests.clear()
    for index, (session, action) in enumerate(requests):
        if session.active:
            # Apply every navigation step, reading only the final destination.
            narrate = not any(owner is session for owner, _ in requests[index + 1 :])
            session.handle_keyboard_control(action, narrate=narrate)
