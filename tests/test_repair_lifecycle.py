import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import presentation_recovery
import service_runtime
from service_watchdog import ServiceWatchdog
from presentations.lesson_presentation import LessonPresentationSession


class RepairLifecycleTests(unittest.TestCase):
    def test_busy_deadline_tracks_progress_but_still_detects_stalls(self):
        now = [0.0]
        watchdog = ServiceWatchdog(clock=lambda: now[0])
        watchdog.busy()
        for moment in (200.0, 400.0, 600.0):
            now[0] = moment
            self.assertTrue(watchdog.healthy()[0])
            watchdog.progress()
        now[0] = 901.0
        self.assertEqual(watchdog.healthy(), (False, "command processing timed out"))

    def test_idle_progress_does_not_hide_lost_audio_callbacks(self):
        now = [0.0]
        watchdog = ServiceWatchdog(clock=lambda: now[0])
        watchdog.idle()
        now[0] = 11.0
        watchdog.progress()
        self.assertEqual(watchdog.healthy(), (False, "microphone callbacks stopped"))

    def test_process_cleanup_preserves_recovery_despite_display_error(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text())
        shutdown = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "shutdown_robot")
        session = object.__new__(LessonPresentationSession)
        session.active = True
        session.slideshow = Mock()
        session._navigation_generation = 0
        ns = dict(state=SimpleNamespace(shutting_down=False, exit_requested=False),
                  cancel_speech=Mock(), wait_for_speech=Mock(return_value=True),
                  close_bible_display=Mock(side_effect=OSError("browser unavailable")),
                  stop_presentation=session.stop, stop_local_ai_server=Mock(),
                  ENABLE_HEAD_TRACKING=False)
        face = Mock()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            presentation_recovery, "STATE_PATH", Path(directory) / "presentation.json"
        ), patch.dict("sys.modules", {"robot": SimpleNamespace(robot_emotions=face)}):
            deck = Path(directory) / "lesson.pptx"
            deck.touch()
            presentation_recovery.save(deck, 3)
            exec(compile(ast.Module(body=[shutdown], type_ignores=[]), str(source), "exec"), ns)
            ns["shutdown_robot"]()
            self.assertEqual(presentation_recovery.load()["slide_number"], 3)
            ns["stop_local_ai_server"].assert_called_once_with()
            face.stop.assert_called_once_with(clear_mouth=True, relax_servos=False)

    def test_intentional_exit_status_matches_service_restart_exception(self):
        with patch.object(service_runtime.state, "exit_requested", True):
            status = service_runtime.exit_status()
        path = Path(__file__).resolve().parents[1] / "systemd" / "ezra.service"
        self.assertIn(f"RestartPreventExitStatus={status}", path.read_text())
        self.assertIn(f"SuccessExitStatus={status}", path.read_text())
        with patch.object(service_runtime.state, "exit_requested", False):
            self.assertEqual(service_runtime.exit_status(), 0)
