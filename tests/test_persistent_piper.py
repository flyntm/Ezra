from pathlib import Path
import sys
import tempfile
import threading
import unittest

from persistent_piper import _PiperWorker, SynthesisCancelled, run_once


class PiperLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        directory = Path(self.directory.name)
        executable = directory / "fake-piper"
        executable.write_text(f"#!{sys.executable}\n" + '''
import json, sys, time, wave
for line in sys.stdin:
    request = json.loads(line)
    if request['text'] == 'stall':
        time.sleep(60)
    with wave.open(request['output_file'], 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes(b'\\0' * 100)
    print(request['output_file'], flush=True)
''')
        executable.chmod(0o700)
        self.worker = _PiperWorker(str(executable), "unused", 1, 1)
        self.addCleanup(self.worker.stop)
        self.output = directory / "speech.wav"

    def test_stalled_worker_times_out_and_next_request_recovers(self):
        with self.assertRaises(TimeoutError):
            self.worker.synthesize("stall", self.output, timeout_seconds=0.2)
        self.assertIsNone(self.worker.process)
        self.assertTrue(self.worker.synthesize("hello", self.output, timeout_seconds=2))

    def test_cancel_reaps_worker_and_next_request_recovers(self):
        cancel = threading.Event()
        timer = threading.Timer(0.15, cancel.set)
        timer.start()
        try:
            with self.assertRaises(SynthesisCancelled):
                self.worker.synthesize("stall", self.output, timeout_seconds=2,
                                       cancel_event=cancel)
        finally:
            timer.cancel()
            timer.join()
        self.assertIsNone(self.worker.process)
        self.assertTrue(self.worker.synthesize("hello", self.output, timeout_seconds=2))

    def test_fallback_process_is_bounded(self):
        with self.assertRaises(TimeoutError):
            run_once([sys.executable, "-c", "import time; time.sleep(60)"], "hello", 0.15)

    def test_cancel_before_fallback_does_not_start_process(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(SynthesisCancelled):
            run_once(["does-not-exist"], "hello", cancel_event=cancel)
