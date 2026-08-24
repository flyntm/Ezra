"""Health-aware systemd watchdog support for Ezra."""

from __future__ import annotations

from contextlib import contextmanager
import os
import socket
import threading
import time


DEFAULT_BUSY_TIMEOUT_SECONDS = 300.0
IDLE_AUDIO_TIMEOUT_SECONDS = 10.0


def _notify(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
        notifier.connect(address)
        notifier.sendall(message.encode())
    return True


class ServiceWatchdog:
    """Send heartbeats only while Ezra's current phase is healthy."""

    def __init__(self, interval_seconds=None, clock=time.monotonic):
        watchdog_usec = int(os.environ.get("WATCHDOG_USEC", "0") or 0)
        self.enabled = bool(os.environ.get("NOTIFY_SOCKET") and watchdog_usec)
        watchdog_seconds = watchdog_usec / 1_000_000 if watchdog_usec else 30.0
        self.interval_seconds = interval_seconds or max(1.0, watchdog_seconds / 3)
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        now = clock()
        self._phase = "startup"
        self._deadline = now + DEFAULT_BUSY_TIMEOUT_SECONDS
        self._last_audio = now
        self._health_checks = {}

    def start(self):
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="EzraSystemdWatchdog", daemon=True
        )
        self._thread.start()

    def ready(self):
        _notify("READY=1\nSTATUS=Ezra ready")
        self.idle()

    def idle(self):
        with self._lock:
            self._phase = "idle"
            self._last_audio = self._clock()

    def audio_activity(self):
        with self._lock:
            self._last_audio = self._clock()

    def busy(self, timeout_seconds=DEFAULT_BUSY_TIMEOUT_SECONDS):
        with self._lock:
            self._phase = "busy"
            self._deadline = self._clock() + timeout_seconds

    def register_health_check(self, name, check):
        with self._lock:
            self._health_checks[name] = check

    def remove_health_check(self, name):
        with self._lock:
            self._health_checks.pop(name, None)

    def healthy(self):
        with self._lock:
            phase = self._phase
            deadline = self._deadline
            last_audio = self._last_audio
            checks = tuple(self._health_checks.items())
        now = self._clock()
        if phase == "startup" and now > deadline:
            return False, "startup timed out"
        if phase == "busy" and now > deadline:
            return False, "command processing timed out"
        if phase == "idle" and now - last_audio > IDLE_AUDIO_TIMEOUT_SECONDS:
            return False, "microphone callbacks stopped"
        for name, check in checks:
            try:
                if not check():
                    return False, f"{name} failed"
            except Exception as exc:
                return False, f"{name} check raised {exc}"
        return True, "healthy"

    def _run(self):
        while not self._stop.wait(self.interval_seconds):
            healthy, reason = self.healthy()
            if healthy:
                try:
                    _notify("WATCHDOG=1")
                except OSError as exc:
                    print(f"⚠️ Watchdog notification failed: {exc}")
            else:
                print(f"❌ Watchdog heartbeat withheld: {reason}")
                try:
                    _notify(f"STATUS=Unhealthy: {reason}")
                except OSError:
                    pass

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._thread = None


watchdog = ServiceWatchdog()


@contextmanager
def watchdog_busy(timeout_seconds=DEFAULT_BUSY_TIMEOUT_SECONDS):
    watchdog.busy(timeout_seconds)
    try:
        yield
    finally:
        watchdog.idle()
