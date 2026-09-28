"""Pause/resume behavior without audio hardware."""
import ast
import os
from pathlib import Path
import signal
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import speech_playback


class SpeechPauseTests(unittest.TestCase):
    def setUp(self):
        self.stop = threading.Event()
        speech_playback.begin(self.stop)

    def tearDown(self):
        speech_playback.end(self.stop)

    def test_toggle_deduplicates_sources_and_resets_between_speeches(self):
        with patch('speech_playback.time.monotonic', side_effect=[1, 1.05, 2]):
            speech_playback.toggle()
            self.assertTrue(speech_playback.is_paused(self.stop))
            speech_playback.toggle()
            self.assertTrue(speech_playback.is_paused(self.stop))
            speech_playback.toggle()
            self.assertFalse(speech_playback.is_paused(self.stop))
        speech_playback.end(self.stop)
        speech_playback.toggle()
        speech_playback.begin(self.stop)
        self.assertFalse(speech_playback.is_paused(self.stop))

    def playback(self, cancel):
        tree = ast.parse(Path('tts.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == '_play_speech_file')
        proc = Mock(returncode=0)
        paused = Mock(side_effect=[False, True, False, False])
        times = iter(range(20))
        clock = SimpleNamespace(monotonic=lambda: next(times), sleep=Mock())
        def poll():
            if cancel and proc.send_signal.call_count == 1:
                self.stop.set()
            return None
        proc.poll.side_effect = poll if cancel else [None, None, 0]
        state = SimpleNamespace(tts_process=None)
        ns = dict(os=os, signal=signal, subprocess=SimpleNamespace(
            Popen=Mock(return_value=proc), DEVNULL=subprocess.DEVNULL,
            TimeoutExpired=subprocess.TimeoutExpired),
            speech_playback=SimpleNamespace(is_paused=paused),
            SPEAKER_DEVICE=None, set_talk_level=Mock(), state=state, time=clock,
            TTS_MOUTH_SYNC_OFFSET_SECONDS=0, watchdog=Mock())
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'tts.py', 'exec'), ns)
        result = ns['_play_speech_file'](self.stop, [0.5] * 100, 1)
        self.assertEqual(proc.send_signal.call_args_list[0].args, (signal.SIGSTOP,))
        self.assertEqual(proc.send_signal.call_args_list[1].args, (signal.SIGCONT,))
        self.assertIsNone(state.tts_process)
        self.assertEqual(result, cancel)
        return proc

    def test_resume_continues_same_process(self):
        proc = self.playback(False)
        proc.terminate.assert_not_called()

    def test_stop_while_paused_resumes_before_terminating(self):
        proc = self.playback(True)
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()


if __name__ == '__main__':
    unittest.main()
