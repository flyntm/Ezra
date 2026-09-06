"""Exercise follow-up control flow without opening the robot's hardware."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

import config
from command_normalization import (
    is_follow_up_cancel, is_unclear_single_word, is_wake_word_only, strip_wake_word,
)


class FollowUpTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text())
        self.controls = Mock()
        self.controls.listen.return_value = object()
        self.controls.transcribe.return_value = "Why?"
        self.ns = {name: getattr(config, name) for name in dir(config)}
        self.ns.update(
            ENABLE_HEAD_TRACKING=False,
            is_follow_up_cancel=is_follow_up_cancel,
            is_unclear_single_word=is_unclear_single_word,
            is_wake_word_only=is_wake_word_only,
            strip_wake_word=strip_wake_word,
            get_last_command_doa=lambda: None,
        )
        for name in ("listen", "transcribe", "set_emotion", "reset_idle_timer"):
            self.ns[name] = getattr(self.controls, name)
        helper = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "listen_for_follow_up")
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), "exec"), self.ns)

        # Run the real main-loop input branch, stopping before command processing.
        main = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "main")
        loop = next(node for node in ast.walk(main) if isinstance(node, ast.While))
        end = next(i for i, node in enumerate(loop.body)
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "command_timing"
                           for target in node.targets))
        branch = ast.parse("def next_input():\n    while not state.shutting_down:\n        pass\n")
        branch.body[0].body[0].body = loop.body[:end] + [
            ast.parse("return wake_text, wake_audio, following_up").body[0]
        ]
        branch.body[0].body.insert(0, ast.parse("follow_up_ready = initially_ready").body[0])
        ast.fix_missing_locations(branch)
        exec(compile(branch, str(source), "exec"), self.ns)
        self.ns.update(state=SimpleNamespace(shutting_down=False), watchdog=Mock(),
                       operating_mode=SimpleNamespace(
                           PRESENTATION="presentation", get_mode=Mock(return_value="general")),
                       initially_ready=True, wait_for_wake_word_with_audio=Mock(
                           return_value=("ezra next question", "wake audio")))

    def test_question_bypasses_wake_detection_and_lights_listening_leds(self):
        self.assertEqual(self.ns["next_input"](), ("why", None, True))
        self.ns["wait_for_wake_word_with_audio"].assert_not_called()
        self.controls.listen.assert_called_once_with(wake_text="", command_timeout=5.0)
        self.assertEqual(self.controls.mock_calls[0], call.set_emotion(config.EMOTION_LISTENING))
        self.assertEqual(self.controls.set_emotion.call_args, call(config.EMOTION_THINKING))

    def test_silence_returns_to_standby_and_wake_detection(self):
        self.controls.listen.return_value = None
        self.assertEqual(self.ns["next_input"](), ("ezra next question", "wake audio", False))
        self.controls.transcribe.assert_not_called()
        self.assertEqual(self.controls.set_emotion.call_args, call(config.EMOTION_STANDBY))

    def test_cancel_and_noise_close_window(self):
        for text in ("That's all.", "never mind", "stop", "pfft", ""):
            with self.subTest(text=text):
                self.controls.transcribe.return_value = text
                self.assertIsNone(self.ns["listen_for_follow_up"](timeout=8.0))
                self.assertEqual(self.controls.set_emotion.call_args, call(config.EMOTION_STANDBY))

    def test_fresh_interaction_requires_wake_word(self):
        self.ns["initially_ready"] = False
        self.assertEqual(self.ns["next_input"](), ("ezra next question", "wake audio", False))
        self.controls.listen.assert_not_called()

    def test_presentation_mode_requires_wake_word_even_after_answer(self):
        self.ns["operating_mode"].get_mode.return_value = "presentation"
        self.assertEqual(self.ns["next_input"](), ("ezra next question", "wake audio", False))
        self.controls.listen.assert_not_called()

    def test_return_to_general_mode_allows_follow_up(self):
        self.ns["operating_mode"].get_mode.return_value = "presentation"
        self.ns["next_input"]()
        self.ns["operating_mode"].get_mode.return_value = "general"
        self.assertEqual(self.ns["next_input"](), ("why", None, True))
        self.controls.listen.assert_called_once()

    def test_configured_window_is_passed_to_listener(self):
        self.ns["FOLLOW_UP_LISTEN_SECONDS"] = 12.0
        self.ns["next_input"]()
        self.controls.listen.assert_called_once_with(wake_text="", command_timeout=12.0)

    def test_each_follow_up_gets_a_new_window(self):
        for question in ("Tell me more", "Why?"):
            self.controls.transcribe.return_value = question
            self.assertTrue(self.ns["next_input"]()[2])
        self.assertEqual(self.controls.listen.call_count, 2)
        self.ns["wait_for_wake_word_with_audio"].assert_not_called()

    def test_listening_mouth_pattern_has_exactly_two_lit_leds(self):
        source = Path(__file__).resolve().parents[1] / "robot" / "robot_emotions.py"
        tree = ast.parse(source.read_text())
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "_mouth_listening")
        ns = {"MOUTH_LED_MODE_LISTENING": config.MOUTH_LED_MODE_LISTENING}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), ns)
        mouth = Mock()
        ns["_mouth_listening"](mouth)
        pattern = mouth._show_mouth_pattern.call_args.args[0]
        self.assertEqual(sum(sum(row) for row in pattern), 2)


if __name__ == "__main__":
    unittest.main()
