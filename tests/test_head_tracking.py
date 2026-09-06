import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import operating_mode
import robot
from presentations.presenter import audience_look_targets


class PresentationHeadTrackingTests(unittest.TestCase):
    def setUp(self):
        # Load the controller with hardware dependencies replaced so these
        # checks cannot move the physical robot.
        spec = importlib.util.spec_from_file_location(
            "head_tracking_under_test",
            Path(__file__).resolve().parents[1] / "robot" / "head_tracking.py",
        )
        module = importlib.util.module_from_spec(spec)
        calibration = Mock()
        calibration.load_cal.return_value = {
            "head": {"left": 60, "center": 90, "right": 120}
        }
        with patch.object(robot, "calibration", calibration, create=True), patch.object(
            robot, "servos", Mock(), create=True
        ):
            spec.loader.exec_module(module)
        self.tracker = module.HeadTracker()
        self.tracker._current_yaw = 20.0
        self.move = Mock(return_value=True)
        self.tracker._move_smooth = self.move
        self.mode = patch("operating_mode.get_mode", return_value=operating_mode.PRESENTATION)
        self.get_mode = self.mode.start()
        self.addCleanup(self.mode.stop)

    def test_speaker_turns_hold_current_position_during_presentation(self):
        for source in ("speaker", "wake word", "command", "follow-up command"):
            with self.subTest(source=source):
                self.assertFalse(self.tracker.turn_toward_bearing(30, source=source))
                self.assertEqual(self.tracker.current_yaw, 20.0)
        self.assertFalse(self.tracker.turn_toward_wake([210.0] * 20))
        self.move.assert_not_called()

    def test_speaking_audience_motion_remains_enabled(self):
        target = audience_look_targets(self.tracker, bearings=(50.0,))[0]
        self.assertTrue(target())
        self.move.assert_called_once_with(
            50.0, step_delay_seconds=None, stop_event=None
        )

    def test_speaker_tracking_resumes_in_general_mode(self):
        self.get_mode.return_value = operating_mode.GENERAL
        self.assertTrue(self.tracker.turn_toward_bearing(30, source="command"))
        self.move.assert_called_once_with(
            50.0, step_delay_seconds=None, stop_event=None
        )


if __name__ == "__main__":
    unittest.main()
