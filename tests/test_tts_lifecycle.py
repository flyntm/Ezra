"""Run real speech orchestration with all hardware boundaries replaced."""

import ast
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
import config
import speech_playback
from tts_pronunciation import apply_pronunciation_overrides
from tools import pronunciation_check


class SpeechLifecycleTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "tts.py"
        names = {
            "_serialized_speech",
            "speak",
            "_split_tts_text",
            "_split_emphasis_segments",
            "_split_clause_pause_segments",
            "_split_explicit_pause_segments",
            "_split_script_action_segments",
            "_append_smile_response",
            "_wait_after_bible_reading",
        }
        tree = ast.parse(path.read_text())
        nodes = [
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
        ]
        self.ns = dict(vars(config))
        self.ns.update(
            speech_playback=speech_playback,
            os=os,
            Path=Path,
            re=re,
            random=random,
            threading=threading,
            time=time,
            tempfile=tempfile,
            np=np,
            wraps=wraps,
            ThreadPoolExecutor=ThreadPoolExecutor,
            _speech_lock=threading.RLock(),
            _active_speech_stop_event=None,
            state=SimpleNamespace(shutting_down=False, mid_response_stop_ready=False),
            TTS_START_DELAY=0,
        )
        for name in (
            "note_speech_requested",
            "note_speech_started",
            "note_speech_finished",
            "set_talk_level",
            "set_emotion",
            "_flush_stop_model",
        ):
            self.ns[name] = Mock()
        self.ns["generate_speech_file"] = Mock(return_value=True)
        self.ns["build_mouth_envelope"] = Mock(return_value=(np.ones(1), 0.04))
        self.ns["_play_speech_file"] = Mock(return_value=False)
        exec(
            compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), self.ns
        )
        self.speak = self.ns["speak"]

    def test_bible_reading_waits_before_returning_to_slide(self):
        stop_event = Mock()

        self.ns["_wait_after_bible_reading"](stop_event)

        stop_event.wait.assert_called_once_with(5.0)

    def say(self, text):
        return self.speak(text, allow_mid_response_stop=False, allow_escape_stop=False)

    def test_pronunciation_override_leaves_gaza_and_keeps_isaiah_spelling(self):
        spoken = apply_pronunciation_overrides(
            "Gaza, Isaiah, and the Gazan Isaiah studied."
        )

        self.assertEqual(
            spoken,
            "Gaza, eyezayuh, and the Gazan eyezayuh studied.",
        )

    def test_pronunciation_check_replays_custom_isaiah_three_times(self):
        piper = Mock()
        piper.synthesize.return_value = True
        with patch.object(
            pronunciation_check, "PersistentPiper", return_value=piper
        ), patch.object(pronunciation_check, "_play_audio") as play_audio, patch.object(
            sys, "argv", ["pronunciation_check.py", "Isaiah"]
        ):
            self.assertEqual(pronunciation_check.main(), 0)

        synthesis = piper.synthesize.call_args
        self.assertEqual(synthesis.args[0], "eyezayuh")
        self.assertEqual(play_audio.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in play_audio.call_args_list],
            [synthesis.args[1]] * 3,
        )
        piper.stop.assert_called_once_with()

    def test_cancel_during_synthesis_skips_playback_and_reports_interruption(self):
        def generate(*args, cancel_event=None, **kwargs):
            cancel_event.set()
            return False

        self.ns["generate_speech_file"].side_effect = generate
        self.ns["speak"] = confirmation = Mock()  # Only the recursive confirmation.
        self.assertTrue(self.say("Hello."))
        self.ns["_play_speech_file"].assert_not_called()
        confirmation.assert_called_once_with("Stopped.", allow_mid_response_stop=False)
        self.assertIsNone(self.ns["_active_speech_stop_event"])

    def test_render_failure_cleans_executor_and_temporary_directory(self):
        directories = []

        def temporary(**kwargs):
            result = tempfile.TemporaryDirectory(**kwargs)
            directories.append(Path(result.name))
            return result

        self.ns["tempfile"] = SimpleNamespace(TemporaryDirectory=temporary)
        self.ns["_render_speech_unit"] = Mock(side_effect=OSError("render failed"))
        with self.assertRaisesRegex(OSError, "render failed"):
            self.say("A sentence about a robot. " * 35)
        self.assertTrue(directories)
        self.assertTrue(all(not p.exists() for p in directories))
        self.assertFalse(
            any(t.name.startswith("ezra-tts") for t in threading.enumerate())
        )
        self.assertIsNone(self.ns["_active_speech_stop_event"])

    def test_playback_end_freezes_display_before_stop_confirmation(self):
        from bible_display import BibleDisplay
        from unittest.mock import patch

        display = BibleDisplay("Psalm 1", "word " * 260)
        complete = Mock()
        with patch("bible_display.time.monotonic", return_value=10.0) as clock:

            def playback(stop_event, *args):
                clock.return_value = 35.0
                stop_event.set()
                return True

            def confirmation(*args, **kwargs):
                clock.return_value = 200.0
                self.assertEqual(display.reading_progress(), 0.25)

            self.ns["_play_speech_file"].side_effect = playback
            self.ns["speak"] = Mock(side_effect=confirmation)
            self.assertTrue(
                self.speak(
                    "Hello.",
                    allow_mid_response_stop=False,
                    allow_escape_stop=False,
                    on_playback_start=display.begin_reading,
                    on_playback_complete=complete,
                    on_playback_end=display.stop_reading,
                )
            )
        complete.assert_not_called()
        self.ns["speak"].assert_called_once()

    def test_playback_error_still_notifies_display(self):
        ended = Mock()
        self.ns["_play_speech_file"].side_effect = OSError("playback failed")
        with self.assertRaisesRegex(OSError, "playback failed"):
            self.speak(
                "Hello.",
                allow_mid_response_stop=False,
                allow_escape_stop=False,
                on_playback_end=ended,
            )
        ended.assert_called_once_with()
        self.assertIsNone(self.ns["_active_speech_stop_event"])

    def test_two_speech_callers_cannot_play_at_the_same_time(self):
        first_started = threading.Event()
        release = threading.Event()
        played = []
        errors = []

        def playback(*args):
            played.append(threading.current_thread().name)
            first_started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test did not release playback")
            return False

        def say():
            try:
                self.say("Hello.")
            except Exception as exc:
                errors.append(exc)

        self.ns["_play_speech_file"].side_effect = playback
        first = threading.Thread(target=say, name="first")
        second = threading.Thread(target=say, name="second")
        try:
            first.start()
            self.assertTrue(first_started.wait(timeout=1))
            second.start()
            second.join(timeout=0.05)
            self.assertEqual(played, ["first"])
        finally:
            release.set()
            first.join(timeout=2)
            if second.ident is not None:
                second.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(played, ["first", "second"])
