"""Maintain Ezra's shared internet-connectivity state."""

from __future__ import annotations

import socket
import threading
import time

import state
from config import (
    INTERNET_CHECK_ENDPOINTS,
    INTERNET_CHECK_INTERVAL_SECONDS,
    INTERNET_CHECK_TIMEOUT_SECONDS,
    OFFLINE_TEST_MODE,
)


_monitor_lock = threading.Lock()
_monitor_stop = None
_monitor_thread = None


def check_internet_connection(connector=socket.create_connection):
    """Check connectivity once, update state, and return the result."""

    connected = False
    last_error = ""

    if OFFLINE_TEST_MODE:
        last_error = "offline test mode enabled"

    for endpoint in (() if OFFLINE_TEST_MODE else INTERNET_CHECK_ENDPOINTS):
        connection = None
        try:
            connection = connector(
                endpoint,
                timeout=INTERNET_CHECK_TIMEOUT_SECONDS,
            )
            connected = True
            last_error = ""
            break
        except OSError as exc:
            last_error = str(exc)
        finally:
            if connection is not None:
                connection.close()

    previous = state.internet_connected if state.internet_status_known else None
    state.internet_connected = connected
    state.internet_status_known = True
    state.internet_last_checked_at = time.time()
    state.internet_last_error = last_error

    if previous is None or previous != connected:
        label = "online" if connected else "offline"
        print(f"🌐 Internet status: {label}")

    return connected


def internet_access_allowed():
    """Return whether Ezra may attempt an external network request."""

    if OFFLINE_TEST_MODE:
        return False
    if state.internet_status_known:
        return state.internet_connected
    return True


def _monitor(stop_event):
    # The initial check is performed synchronously during startup so its status
    # is always reported before Ezra announces that it is ready.
    while not stop_event.wait(INTERNET_CHECK_INTERVAL_SECONDS):
        check_internet_connection()


def start_connectivity_monitor():
    """Check once now, then start one daemon monitor for later checks."""

    global _monitor_stop, _monitor_thread

    with _monitor_lock:
        if _monitor_thread is not None and _monitor_thread.is_alive():
            return _monitor_thread

        check_internet_connection()
        _monitor_stop = threading.Event()
        _monitor_thread = threading.Thread(
            target=_monitor,
            args=(_monitor_stop,),
            name="ezra-connectivity",
            daemon=True,
        )
        _monitor_thread.start()
        return _monitor_thread


def stop_connectivity_monitor():
    """Stop the monitor without delaying Ezra's shutdown."""

    global _monitor_stop, _monitor_thread

    with _monitor_lock:
        stop_event = _monitor_stop
        thread = _monitor_thread
        _monitor_stop = None
        _monitor_thread = None

    if stop_event is not None:
        stop_event.set()
    if thread is not None:
        thread.join(timeout=INTERNET_CHECK_TIMEOUT_SECONDS + 0.5)
