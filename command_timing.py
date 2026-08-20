"""Optional per-interaction latency diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time


_active = threading.local()


@dataclass
class CommandTiming:
    wake_detected_at: float
    marks: dict[str, float] = field(default_factory=dict)
    speech_requested_at: float | None = None
    speech_started_at: float | None = None
    speech_finished_at: float | None = None

    def mark(self, name: str, at: float | None = None):
        self.marks[name] = time.monotonic() if at is None else at

    def reset_response_speech(self):
        """Discard wake-only acknowledgement speech before a follow-up command."""
        self.speech_started_at = None
        self.speech_finished_at = None
        self.speech_requested_at = None

    @staticmethod
    def _duration(start, end):
        if start is None or end is None:
            return None
        return max(0.0, end - start)

    @staticmethod
    def _format(value):
        return "n/a" if value is None else f"{value:.3f}s"

    def report(self, outcome="complete"):
        finished = self.marks.get("response_finished", time.monotonic())
        capture_finished = self.marks.get("command_capture_finished")
        speech_ended = self.marks.get("command_speech_ended")
        stt_started = self.marks.get("stt_started")
        stt_finished = self.marks.get("stt_finished")
        command_ready = self.marks.get("command_ready")
        processing_started = self.marks.get("processing_started", command_ready)
        processing_finished = self.marks.get("processing_finished")
        print(f"\n⏱️ COMMAND TIMING | outcome={outcome}")
        rows = (
            (
                "Wake detected → command capture complete",
                self._duration(self.wake_detected_at, capture_finished),
            ),
            (
                "Wake detected → command speech ended",
                self._duration(self.wake_detected_at, speech_ended),
            ),
            (
                "Command speech ended → capture complete",
                self._duration(speech_ended, capture_finished),
            ),
            ("Speech-to-text", self._duration(stt_started, stt_finished)),
            (
                "Command capture complete → speech-to-text complete",
                self._duration(capture_finished, stt_finished),
            ),
            (
                "Command processing",
                self._duration(processing_started, processing_finished),
            ),
            (
                "Speech synthesis/preparation",
                self._duration(self.speech_requested_at, self.speech_started_at),
            ),
            (
                "Command ready → speech started",
                self._duration(command_ready, self.speech_started_at),
            ),
            (
                "Speech playback",
                self._duration(self.speech_started_at, self.speech_finished_at),
            ),
            (
                "Command ready → response complete",
                self._duration(command_ready, finished),
            ),
            (
                "Wake detected → response complete",
                self._duration(self.wake_detected_at, finished),
            ),
        )
        for label, duration in rows:
            print(f"  {label}: {self._format(duration)}")


def set_active_command_timing(timing):
    _active.value = timing


def clear_active_command_timing():
    _active.value = None


def note_speech_started():
    timing = getattr(_active, "value", None)
    if timing is not None and timing.speech_started_at is None:
        timing.speech_started_at = time.monotonic()


def note_speech_requested():
    timing = getattr(_active, "value", None)
    if timing is not None and timing.speech_requested_at is None:
        timing.speech_requested_at = time.monotonic()


def note_speech_finished():
    timing = getattr(_active, "value", None)
    if timing is not None and timing.speech_started_at is not None:
        timing.speech_finished_at = time.monotonic()
