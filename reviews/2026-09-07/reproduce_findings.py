"""Offline evidence for the review, asserting the observed defects.

These are diagnostic probes, not acceptance tests: a passing probe confirms
the reviewed defect still exists. No robot modules with hardware startup are
imported. Audio, speech, processes, and network calls are replaced by fakes.
Run from the project root with ezra311-env/bin/python followed by this path.
"""

import ast
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import config
import ezra_brain
import lesson_context
import live_info
import operating_mode
import presentation_recovery
from bible_service import parse_bible_reference
from command_normalization import strip_wake_word
from presentations import lesson_presentation
from presentations.lesson_presentation import LessonPresentationSession
from presentations.powerpoint import PowerPointDeck
from presentations.browser_slideshow import render_pptx_html
from service_watchdog import ServiceWatchdog
from persistent_piper import _PiperWorker


def extract(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), "exec"),
         namespace)
    return namespace


class ReviewProbes(unittest.TestCase):
    def setUp(self):
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def session(self, speak):
        path = lesson_presentation.discover_presentation()
        deck = PowerPointDeck.load(path)
        deck = replace(deck, notes=("First narration.", "Second narration."),
                       auto_advance=(False, False), reveal_slides=(False, False),
                       question_numbers=(None, None))
        with patch.object(PowerPointDeck, "load", return_value=deck):
            session = LessonPresentationSession(speak, slideshow=Mock(), deck_path=path)
        session.start(narrate=False)
        self.addCleanup(lesson_presentation.watchdog.remove_health_check,
                        "presentation display")
        return session

    def test_r01_questions_are_classified_as_shutdown_commands(self):
        tree = ast.parse((ROOT / "command.py").read_text())
        names = {"POWEROFF_PATTERN", "QUIT_PROGRAM_PATTERN"}
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id in names
                               for t in node.targets)]
        ns = {"re": re}
        exec(compile(ast.Module(body=assignments, type_ignores=[]), "command.py", "exec"), ns)
        extract("command.py", {"looks_like_quit_command", "looks_like_poweroff_command"}, ns)
        self.assertTrue(ns["looks_like_quit_command"]("How do I quit smoking?"))
        self.assertTrue(ns["looks_like_poweroff_command"]("Explain a government shutdown"))
        self.assertTrue(ns["looks_like_poweroff_command"]("Do not shut down"))

    def test_r02_wake_model_input_replays_and_scrambles_samples(self):
        ns = dict(np=np, watchdog=Mock(), time=Mock(),
                  select_respeaker_recognition_channel=lambda x: x.copy(),
                  buffer_size=16000, recent_buffer_size=256000,
                  audio_buffer=np.zeros(16000, dtype=np.float32),
                  recent_audio_buffer=np.zeros(256000, dtype=np.float32),
                  audio_buffer_idx=0, recent_buffer_idx=0,
                  audio_buffer_len=0, recent_buffer_len=0, audio_ready=Mock())
        extract("wake_word.py", {"audio_callback"}, ns)
        tree = ast.parse((ROOT / "wake_word.py").read_text())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        conversion = next(n for n in ast.walk(run) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "audio_int16"
                                  for t in n.targets))
        convert = compile(ast.Module(body=[conversion], type_ignores=[]), "wake_word.py", "exec")
        snapshots = []
        for block in range(17):
            values = np.arange(block * 1024 + 1, (block + 1) * 1024 + 1,
                               dtype=np.float32) / 32767
            ns["audio_callback"](values[:, None], 1024, None, None)
            exec(convert, ns)
            snapshots.append(ns["audio_int16"].copy())
        self.assertEqual(len(snapshots[-1]), 16000)  # only 1,024 new samples
        self.assertGreater(len(np.intersect1d(snapshots[-2], snapshots[-1])), 14000)
        self.assertTrue(np.any(np.diff(snapshots[-1].astype(int)) < 0))

    def test_r03_keyboard_narration_runs_while_main_listener_is_active(self):
        listener_active = threading.Event()
        listener_active.set()
        observed = []
        main_thread = threading.get_ident()

        def speak(text, **callbacks):
            observed.append((listener_active.is_set(), threading.get_ident() != main_thread))
            callbacks["on_playback_complete"]()
            return False

        session = self.session(speak)
        worker = threading.Thread(target=session.handle_keyboard_control, args=("next",))
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, [(True, True)])

    def test_r04_active_narration_does_not_refresh_busy_watchdog(self):
        now = [0.0]
        watchdog = ServiceWatchdog(clock=lambda: now[0])
        watchdog.busy()
        observed = []

        def speak(text, **callbacks):
            callbacks["on_playback_start"]()
            now[0] += 160
            observed.append(watchdog.healthy())
            callbacks["on_playback_complete"]()
            return False

        with patch.object(lesson_presentation, "watchdog", watchdog):
            session = self.session(speak)
            session.deck = replace(session.deck, auto_advance=(True, False))
            session.narrate_current()
        self.assertEqual(observed[0], (True, "healthy"))
        self.assertEqual(observed[1], (False, "command processing timed out"))

    def test_r05_online_start_then_offline_request_never_starts_local_server(self):
        tree = ast.parse((ROOT / "main.py").read_text())
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        startup = next(n for n in main.body if isinstance(n, ast.If)
                       and isinstance(n.test, ast.UnaryOp)
                       and isinstance(n.test.operand, ast.Call)
                       and getattr(n.test.operand.func, "id", "") == "internet_access_allowed")
        start = Mock()
        exec(compile(ast.Module(body=[startup], type_ignores=[]), "main.py", "exec"),
             dict(internet_access_allowed=lambda: True, start_local_ai_server=start))
        with patch.dict("os.environ", {"EZRA_AI_PROVIDER": "openai"}), patch.object(
            ezra_brain, "internet_access_allowed", return_value=False
        ), patch.object(ezra_brain, "presentation_context_enabled", return_value=False), patch.object(
            ezra_brain.requests, "post", side_effect=ezra_brain.requests.ConnectionError("server not started")
        ), patch.object(ezra_brain, "conversation_history", []), patch(
            "local_ai_server.start_local_ai_server", start
        ):
            with self.assertRaises(ezra_brain.InternetUnavailableError):
                ezra_brain.ask_ezra("What is a servo?")
        start.assert_not_called()

    def test_r06_error_cleanup_deletes_saved_presentation(self):
        session = self.session(Mock())
        with tempfile.TemporaryDirectory() as directory, patch.object(
            presentation_recovery, "STATE_PATH", Path(directory) / "presentation.json"
        ), patch.object(lesson_presentation, "_session", session), patch.object(
            operating_mode, "_mode", operating_mode.PRESENTATION
        ):
            presentation_recovery.save(session.deck.path, 2)
            self.assertIsNotNone(presentation_recovery.load())
            fake_robot = SimpleNamespace(robot_emotions=Mock())
            ns = dict(state=SimpleNamespace(shutting_down=False),
                      close_bible_display=Mock(),
                      stop_presentation=lesson_presentation.stop_presentation,
                      stop_local_ai_server=Mock(), ENABLE_HEAD_TRACKING=False)
            extract("main.py", {"shutdown_robot"}, ns)
            with patch.dict(sys.modules, {"robot": fake_robot}):
                ns["shutdown_robot"]()
            self.assertIsNone(presentation_recovery.load())

    def test_r07_normalization_corrupts_scripture_reference(self):
        reference = parse_bible_reference(strip_wake_word("Ezra read John 3:16"))
        self.assertEqual(reference.chapter, 316)
        self.assertIsNone(reference.verse_start)
        reference = parse_bible_reference(strip_wake_word("Ezra read John 3:16-18"))
        self.assertEqual(reference.chapter, 31618)

    def test_r08_current_lesson_file_is_excluded_from_retrieval(self):
        current = ROOT / "presentations" / "acts-Lesson_Four.json"
        records = [json.loads(line) for line in current.read_text().splitlines() if line.strip()]
        self.assertEqual(len(records), 61)
        loaded = lesson_context._jsonl_chunks(ROOT / "presentations")
        self.assertTrue(loaded)
        self.assertFalse(any(chunk.label == current.stem for chunk in loaded))
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / current.name).write_bytes(current.read_bytes())
            self.assertEqual(lesson_context._jsonl_chunks(directory), [])

    def test_r09_brain_and_training_questions_are_routed_to_weather(self):
        with patch.object(live_info, "internet_access_allowed", return_value=True), patch.object(
            live_info, "get_weather_summary", return_value="Current weather."
        ) as weather:
            for question in ("Explain how your brain works", "What is training?"):
                self.assertEqual(live_info.get_live_info_response(question.lower()), "Current weather.")
        self.assertEqual(weather.call_count, 2)

    def test_r10_reordered_pptx_still_uses_filename_order_and_note_numbers(self):
        p = "http://schemas.openxmlformats.org/presentationml/2006/main"
        a = "http://schemas.openxmlformats.org/drawingml/2006/main"
        r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        rel = "http://schemas.openxmlformats.org/package/2006/relationships"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reordered.pptx"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId id="257" r:id="second"/><p:sldId id="256" r:id="first"/></p:sldIdLst><p:sldSz cx="1600" cy="900"/></p:presentation>')
                z.writestr("ppt/_rels/presentation.xml.rels", f'<Relationships xmlns="{rel}"><Relationship Id="first" Type="{r}/slide" Target="slides/slide1.xml"/><Relationship Id="second" Type="{r}/slide" Target="slides/slide2.xml"/></Relationships>')
                for number in (1, 2):
                    z.writestr(f"ppt/slides/slide{number}.xml", f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="1" name="Slide {number}"/></p:nvSpPr><p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="800" cy="200"/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>Slide {number}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>')
                    z.writestr(f"ppt/notesSlides/notesSlide{number}.xml", f'<p:notes xmlns:p="{p}" xmlns:a="{a}"><a:p><a:r><a:t>Note {number}</a:t></a:r></a:p></p:notes>')
                    # Slide 1 is related to notesSlide2, and vice versa.
                    z.writestr(f"ppt/slides/_rels/slide{number}.xml.rels", f'<Relationships xmlns="{rel}"><Relationship Id="note" Type="{r}/notesSlide" Target="../notesSlides/notesSlide{3-number}.xml"/></Relationships>')
            deck = PowerPointDeck.load(path)
            self.assertEqual(deck.notes, ("Note 1", "Note 2"))
            rendered = render_pptx_html(path)
            self.assertLess(rendered.index('data-name="Slide 1"'), rendered.index('data-name="Slide 2"'))

    def test_r11_synthesis_wait_cannot_observe_speech_cancellation(self):
        reading = threading.Event()
        release = threading.Event()
        speech_cancel = threading.Event()

        class BlockedOutput:
            def readline(self):
                reading.set()
                release.wait(timeout=2)
                return ""

        worker = _PiperWorker("unused", "unused", 1, 1)
        worker.process = Mock()
        worker.process.poll.return_value = None
        worker.process.stdout = BlockedOutput()
        worker.process.stdin = io.StringIO()
        thread = threading.Thread(target=worker._synthesize_once,
                                  args=("Example", "/tmp/ezra-unused-probe.wav"))
        try:
            thread.start()
            self.assertTrue(reading.wait(timeout=1))
            speech_cancel.set()
            thread.join(timeout=0.05)
            self.assertTrue(thread.is_alive())
        finally:
            release.set()
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_r13_remainder_playback_error_retries_already_spoken_answer(self):
        events = [SimpleNamespace(type="response.output_text.delta",
                                  delta='{"emotion":"neutral","response":"First. Second."}')]

        class Stream:
            def __enter__(self):
                return iter(events)

            def __exit__(self, *args):
                return False

        client = Mock()
        client.responses.stream.return_value = Stream()
        delivered = []

        def speak(text):
            if delivered:
                raise OSError("remainder temporary file unavailable")
            delivered.append(text)
            return False

        with patch.dict("os.environ", {"EZRA_AI_PROVIDER": "openai"}), patch.object(
            ezra_brain, "internet_access_allowed", return_value=True
        ), patch.object(ezra_brain, "_get_openai_client", return_value=client), patch.object(
            ezra_brain, "_ask_openai", return_value='{"emotion":"neutral","response":"First. Second."}'
        ) as fallback, patch.object(ezra_brain, "presentation_context_enabled", return_value=False), patch.object(
            ezra_brain, "conversation_history", []
        ):
            result = ezra_brain.ask_ezra("Question", on_sentence=speak)
        self.assertEqual(delivered, ["First."])
        fallback.assert_called_once()
        self.assertFalse(result.get("streamed", False))
        self.assertEqual(result["response"], "First. Second.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
