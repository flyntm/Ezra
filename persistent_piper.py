"""Long-running native Piper workers keyed by synthesis settings."""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import threading
import select
import time


class SynthesisCancelled(Exception):
    pass


def _check_wait(deadline, cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise SynthesisCancelled()
    if time.monotonic() >= deadline:
        raise TimeoutError("Piper synthesis timed out")


def run_once(command, text, timeout_seconds=30.0, cancel_event=None):
    """Run fallback synthesis with the same deadline/cancel contract."""
    deadline = time.monotonic() + timeout_seconds
    _check_wait(deadline, cancel_event)
    process = subprocess.Popen(command, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               text=True)
    try:
        pending_input = text
        while True:
            _check_wait(deadline, cancel_event)
            try:
                process.communicate(input=pending_input, timeout=0.05)
                return process.returncode == 0
            except subprocess.TimeoutExpired:
                pending_input = None
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


class _PiperWorker:
    def __init__(self, executable, model, length_scale, sentence_silence):
        self.executable = os.path.expanduser(executable)
        self.model = os.path.expanduser(model)
        self.length_scale = float(length_scale)
        self.sentence_silence = float(sentence_silence)
        self.lock = threading.Lock()
        self.process = None

    def _start(self):
        self.stop()
        self.process = subprocess.Popen(
            [
                self.executable,
                "--model",
                self.model,
                "--length_scale",
                str(self.length_scale),
                "--sentence_silence",
                str(self.sentence_silence),
                "--json-input",
                "--quiet",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def _synthesize_once(self, text, output_file, deadline=None, cancel_event=None):
        deadline = time.monotonic() + 30.0 if deadline is None else deadline
        _check_wait(deadline, cancel_event)
        if self.process is None or self.process.poll() is not None:
            self._start()
        if self.process.stdin is None or self.process.stdout is None:
            return False

        destination = Path(output_file).resolve()
        request = json.dumps(
            {"text": str(text), "output_file": os.fspath(destination)}
        )
        input_fd = self.process.stdin.fileno()
        os.set_blocking(input_fd, False)
        pending = memoryview((request + "\n").encode())
        while pending:
            _check_wait(deadline, cancel_event)
            if select.select([], [input_fd], [], 0.05)[1]:
                try:
                    pending = pending[os.write(input_fd, pending):]
                except BlockingIOError:
                    continue

        # Piper prints the completed output path after the WAV is finalized.
        output_fd = self.process.stdout.fileno()
        os.set_blocking(output_fd, False)
        output = bytearray()
        while b"\n" not in output:
            _check_wait(deadline, cancel_event)
            if select.select([output_fd], [], [], 0.05)[0]:
                try:
                    chunk = os.read(output_fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    return False
                output.extend(chunk)
        completed_path = output.decode().strip()
        return (
            bool(completed_path)
            and Path(completed_path).resolve() == destination
            and destination.exists()
            and destination.stat().st_size > 44
        )

    def synthesize(self, text, output_file, timeout_seconds=30.0, cancel_event=None):
        deadline = time.monotonic() + timeout_seconds
        while not self.lock.acquire(timeout=0.05):
            _check_wait(deadline, cancel_event)
        try:
            for _ in range(2):
                try:
                    if self._synthesize_once(text, output_file, deadline, cancel_event):
                        return True
                except (TimeoutError, SynthesisCancelled):
                    self.stop()
                    raise
                except (OSError, ValueError):
                    pass
                self.stop()
            return False
        finally:
            self.lock.release()

    def stop(self):
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)
        finally:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()


class PersistentPiper:
    def __init__(self, executable, model):
        self.executable = executable
        self.model = model
        self._workers = {}
        self._workers_lock = threading.Lock()
        atexit.register(self.stop)

    def synthesize(self, text, output_file, length_scale, sentence_silence,
                   timeout_seconds=30.0, cancel_event=None):
        key = (float(length_scale), float(sentence_silence))
        with self._workers_lock:
            worker = self._workers.get(key)
            if worker is None:
                worker = _PiperWorker(
                    self.executable,
                    self.model,
                    *key,
                )
                self._workers[key] = worker
        return worker.synthesize(text, output_file, timeout_seconds, cancel_event)

    def stop(self):
        with self._workers_lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()
