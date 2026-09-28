import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np
import config
import presentation_controls as controls
from presentations.lesson_presentation import LessonPresentationSession
from presentations.powerpoint import PowerPointDeck
from service_watchdog import watchdog


class PresentationControlTests(unittest.TestCase):
    def setUp(self):
        self.capture_active = True
        self.spoken = []
        self.slides = Mock(skip_event=threading.Event())
        deck = PowerPointDeck(
            Path("unused.pptx"),
            tuple(f"Slide {i}" for i in range(4)),
            (False,) * 4,
            (False,) * 4,
            (None,) * 4,
        )
        with patch.object(PowerPointDeck, "load", return_value=deck):
            self.session = LessonPresentationSession(
                self.speak, slideshow=self.slides, deck_path="unused.pptx"
            )
        self.session.start(narrate=False)

    def tearDown(self):
        self.session.stop(clear_recovery=False)
        watchdog.remove_health_check("presentation display")

    def speak(self, text, **callbacks):
        self.assertFalse(self.capture_active, "Narration started before capture closed")
        self.spoken.append(text)
        callbacks.get("on_playback_start", lambda: None)()
        callbacks.get("on_playback_complete", lambda: None)()
        return False

    def test_keyboard_waits_for_actual_wake_stream_close_before_narrating(self):
        worker = threading.Thread(target=self.slides.control_handler, args=("next",))
        worker.start()
        worker.join(timeout=1)
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.session.slide_index, 0)
        self.assertTrue(controls.pending())

        # Execute run() itself, replacing hardware/model dependencies. A queued
        # browser request must take its finally path and close the wake stream.
        path = Path(__file__).resolve().parents[1] / "wake_word.py"
        tree = ast.parse(path.read_text())
        run = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"
        )
        stream = Mock()
        stream.close.side_effect = lambda: setattr(self, "capture_active", False)
        ns = dict(vars(config))
        from wake_noise import WakeNoiseFloor

        ns["WakeNoiseFloor"] = WakeNoiseFloor
        ns.update(
            np=np,
            time=time,
            deque=__import__("collections").deque,
            model=Mock(),
            drain_wake_audio=Mock(),
            wake_audio_overrun=threading.Event(),
            audio_ready=threading.Event(),
            buffer_size=16000,
            recent_buffer_size=256000,
            robot_emotions=Mock(),
            open_microphone=Mock(return_value=stream),
            presentation_controls=controls,
            MIC_RELEASE_DELAY=0,
            mic=Mock(),
            set_respeaker_listening_led=Mock(),
            set_respeaker_wake_indicator=Mock(),
        )
        exec(compile(ast.Module(body=[run], type_ignores=[]), str(path), "exec"), ns)
        self.assertEqual(ns["run"](return_audio=True), (None, None))
        self.assertEqual(
            ns["set_respeaker_listening_led"].call_args_list,
            [
                unittest.mock.call(ns["mic"], controls.listening_enabled()),
                unittest.mock.call(ns["mic"], controls.listening_enabled()),
            ],
        )
        stream.abort.assert_called_once_with()
        stream.close.assert_called_once_with()
        controls.process_pending()
        self.assertEqual(self.spoken, ["Slide 1"])

    def test_listening_toggle_does_not_queue_or_navigate_slides(self):
        initial_state, initial_revision = controls.listening_status()

        self.assertEqual(controls.toggle_listening(), not initial_state)
        self.assertEqual(controls.listening_status()[1], initial_revision + 1)
        self.assertEqual(controls.toggle_listening(), initial_state)
        self.assertEqual(controls.listening_status()[1], initial_revision + 2)

        self.assertFalse(controls.pending())
        self.assertEqual(self.session.slide_index, 0)
        self.assertEqual(self.spoken, [])

    def test_rapid_navigation_reads_only_final_destination(self):
        self.capture_active = False
        for _ in range(3):
            self.session.queue_keyboard_control("next")
        controls.process_pending()
        self.assertEqual(self.session.slide_index, 3)
        self.assertEqual(self.spoken, ["Slide 3"])

    def test_previous_keyboard_control_does_not_narrate(self):
        self.capture_active = False
        self.session.slide_index = 1

        self.session.queue_keyboard_control("previous")
        controls.process_pending()

        self.assertEqual(self.session.slide_index, 0)
        self.assertEqual(self.spoken, [])

    def test_skip_discards_queued_narration_and_cancels_active_generation(self):
        self.session.queue_keyboard_control("next")
        self.session.queue_keyboard_control("skip")
        self.assertFalse(controls.pending())
        self.assertTrue(self.slides.skip_event.is_set())
        self.assertEqual(self.spoken, [])

    def test_request_arriving_before_narration_is_not_cleared(self):
        generation = self.session._navigation_generation
        self.session.queue_keyboard_control("next")
        self.assertFalse(controls.begin_narration(self.session, generation))
        self.assertTrue(self.slides.skip_event.is_set())
