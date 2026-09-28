import ast
from pathlib import Path
import queue
import threading
import unittest
from unittest.mock import Mock

import numpy as np


class WakeAudioTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "wake_word.py"
        tree = ast.parse(path.read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"audio_callback", "drain_wake_audio"}]
        self.ns = dict(np=np, queue=queue, watchdog=Mock(),
                       select_respeaker_recognition_channel=lambda a: a[:, :1].copy(),
                       buffer_size=16000, recent_buffer_size=256000,
                       audio_buffer=np.zeros(16000, dtype=np.float32),
                       recent_audio_buffer=np.zeros(256000, dtype=np.float32),
                       audio_buffer_idx=0, recent_buffer_idx=0,
                       audio_buffer_len=0, recent_buffer_len=0,
                       audio_ready=threading.Event(), wake_audio_overrun=threading.Event(),
                       wake_audio_queue=queue.Queue(maxsize=64))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), self.ns)

    def test_samples_consumed_once_in_order_across_ring_wraps(self):
        expected = np.arange(40 * 1024, dtype=np.float32)
        captured = []
        for start in range(0, expected.size, 1024):
            block = np.column_stack((expected[start:start + 1024], np.zeros(1024)))
            self.ns["audio_callback"](block, 1024, None, None)
            block[:] = -1  # PortAudio can reuse callback storage.
            if start % (3 * 1024) == 0:
                captured.append(self.ns["drain_wake_audio"]())
        captured.append(self.ns["drain_wake_audio"]())
        np.testing.assert_array_equal(np.concatenate(captured), expected)
        self.assertEqual(self.ns["drain_wake_audio"]().size, 0)

    def test_overrun_signals_gap_without_blocking_callback(self):
        self.ns["wake_audio_queue"] = queue.Queue(maxsize=1)
        for _ in range(2):
            self.ns["audio_callback"](np.ones((1024, 2)), 1024, None, None)
        self.assertTrue(self.ns["wake_audio_overrun"].is_set())
