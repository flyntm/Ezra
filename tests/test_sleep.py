"""Check sleep poses without opening the microphone or moving hardware."""

import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class SleepTests(unittest.TestCase):
    def test_local_sleep_command_skips_standby_and_follow_up(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text())
        branch = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.If)
                      and isinstance(node.test, ast.Call)
                      and isinstance(node.test.func, ast.Name)
                      and node.test.func.id == "handle_local_command")
        loop = ast.For(target=ast.Name(id="_", ctx=ast.Store()),
                       iter=ast.List(elts=[ast.Constant(0)], ctx=ast.Load()),
                       body=[branch], orelse=[])
        module = ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[]))
        for sleeping in (True, False):
            with self.subTest(sleeping=sleeping):
                ns = dict(handle_local_command=Mock(return_value=True),
                          command="go to sleep", command_timing=None,
                          is_sleeping=lambda: sleeping, set_emotion=Mock(),
                          EMOTION_STANDBY="standby", maybe_playback_diagnostic=Mock(),
                          finish_command_timing=Mock(), ENABLE_FOLLOW_UP_LISTENING=True)
                exec(compile(module, str(source), "exec"), ns)
                self.assertEqual(ns["follow_up_ready"], not sleeping)
                self.assertEqual(ns["set_emotion"].call_count, int(not sleeping))

    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "wake_word.py"
        tree = ast.parse(source.read_text())
        helper = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "enter_sleep")
        self.pose = {}
        self.emotions = Mock()
        # Model an in-flight animation completing while stop waits for it.
        self.emotions.stop.side_effect = lambda **kwargs: self.pose.update(
            eyes="sideways", lids="open")
        self.head = Mock()
        self.head.center.side_effect = lambda: self.pose.update(head="front")
        self.eyes = Mock()
        self.eyes.center.side_effect = lambda: self.pose.update(eyes="front")
        self.lids = Mock()
        self.lids.close_lids.side_effect = lambda: self.pose.update(lids="closed")
        self.ns = dict(robot_emotions=self.emotions, head_tracker=self.head,
                       eyes=self.eyes, eyelids=self.lids, print=Mock())
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), "exec"),
             self.ns)

    def test_finishing_animation_cannot_overwrite_sleep_pose(self):
        self.ns["enter_sleep"]()
        self.assertTrue(self.ns["sleeping"])
        self.assertEqual(self.pose, dict(head="front", eyes="front", lids="closed"))
        self.emotions.stop.assert_called_once_with(clear_mouth=True, relax_servos=False)
        self.emotions.clear_external_gaze.assert_called_once_with()

    def test_neck_failure_still_sets_face_pose(self):
        self.head.center.side_effect = RuntimeError("servo unavailable")
        self.ns["enter_sleep"]()
        self.assertEqual(self.pose, dict(eyes="front", lids="closed"))

    def test_sleep_without_head_tracking(self):
        self.ns["head_tracker"] = None
        self.ns["enter_sleep"]()
        self.assertEqual(self.pose, dict(eyes="front", lids="closed"))

    def test_animation_stop_failure_still_attempts_sleep_pose(self):
        self.emotions.stop.side_effect = RuntimeError("mouth unavailable")
        self.ns["enter_sleep"]()
        self.assertEqual(self.pose, dict(head="front", eyes="front", lids="closed"))
