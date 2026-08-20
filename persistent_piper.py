"""Long-running native Piper workers keyed by synthesis settings."""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import threading


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

    def _synthesize_once(self, text, output_file):
        if self.process is None or self.process.poll() is not None:
            self._start()
        if self.process.stdin is None or self.process.stdout is None:
            return False

        destination = Path(output_file).resolve()
        request = json.dumps(
            {"text": str(text), "output_file": os.fspath(destination)}
        )
        self.process.stdin.write(request + "\n")
        self.process.stdin.flush()

        # Piper prints the completed output path after the WAV is finalized.
        completed_path = self.process.stdout.readline().strip()
        return (
            bool(completed_path)
            and Path(completed_path).resolve() == destination
            and destination.exists()
            and destination.stat().st_size > 44
        )

    def synthesize(self, text, output_file):
        with self.lock:
            try:
                if self._synthesize_once(text, output_file):
                    return True
            except (BrokenPipeError, OSError, ValueError):
                pass

            # A worker may have exited between poll() and the request. Restart
            # it once before allowing the caller to use the one-shot fallback.
            self.stop()
            try:
                return self._synthesize_once(text, output_file)
            except (BrokenPipeError, OSError, ValueError):
                self.stop()
                return False

    def stop(self):
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)


class PersistentPiper:
    def __init__(self, executable, model):
        self.executable = executable
        self.model = model
        self._workers = {}
        self._workers_lock = threading.Lock()
        atexit.register(self.stop)

    def synthesize(self, text, output_file, length_scale, sentence_silence):
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
        return worker.synthesize(text, output_file)

    def stop(self):
        with self._workers_lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()
