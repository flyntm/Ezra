"""Check response completion without importing main's hardware dependencies."""

import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, call

import config


class ResponseEmotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text())
        # Execute the actual response-completion block with speech and face
        # controls replaced, avoiding service startup and physical movement.
        loop = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.While) and any(
                isinstance(statement, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "response"
                        for target in statement.targets)
                for statement in node.body
            )
        )
        start = next(i for i, node in enumerate(loop.body)
                     if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "response"
                             for target in node.targets))
        end = next(i for i in range(start, len(loop.body))
                   if isinstance(loop.body[i], ast.Expr)
                   and isinstance(loop.body[i].value, ast.Call)
                   and isinstance(loop.body[i].value.func, ast.Name)
                   and loop.body[i].value.func.id == "maybe_playback_diagnostic")
        emotion_map = next(node for node in tree.body
                           if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == "EMOTION_MAP"
                                   for target in node.targets))
        cls.code = compile(ast.Module(
            body=[emotion_map, *loop.body[start:end]], type_ignores=[]
        ), str(source), "exec")

    def complete(self, speech_interrupted=False, **result):
        controls = Mock()
        controls.speak.return_value = speech_interrupted
        namespace = {
            "result": {"response": "An answer.", **result},
            "set_emotion": controls.set_emotion,
            "set_temporary_emotion": controls.set_temporary_emotion,
            "speak": controls.speak,
            "EMOTION_STANDBY": config.EMOTION_STANDBY,
            "POST_RESPONSE_SMILE_EMOTIONS": config.POST_RESPONSE_SMILE_EMOTIONS,
            "POST_RESPONSE_SMILE_SECONDS": config.POST_RESPONSE_SMILE_SECONDS,
        }
        exec(self.code, namespace)
        return controls

    def test_streamed_thinking_answer_returns_to_standby(self):
        controls = self.complete(streamed=True, emotion="thinking")
        self.assertEqual(controls.mock_calls, [call.set_emotion(config.EMOTION_STANDBY)])

    def test_nonstreamed_answer_returns_to_standby_after_speech(self):
        controls = self.complete(streamed=False, emotion="thinking")
        self.assertEqual(controls.mock_calls, [
            call.set_emotion("thinking"), call.speak("An answer."),
            call.set_emotion(config.EMOTION_STANDBY),
        ])

    def test_upbeat_answer_keeps_temporary_smile_with_standby_fallback(self):
        controls = self.complete(streamed=True, emotion="curious")
        self.assertEqual(controls.mock_calls, [
            call.set_emotion(config.EMOTION_STANDBY),
            call.set_temporary_emotion("happy", config.POST_RESPONSE_SMILE_SECONDS,
                                      fallback_emotion=config.EMOTION_STANDBY),
        ])

    def test_interrupted_answer_returns_to_standby_without_smile(self):
        controls = self.complete(streamed=True, emotion="happy", interrupted=True)
        self.assertEqual(controls.mock_calls, [call.set_emotion(config.EMOTION_STANDBY)])

    def test_nonstreamed_interruption_returns_to_standby_without_smile(self):
        controls = self.complete(streamed=False, emotion="happy", speech_interrupted=True)
        self.assertEqual(controls.mock_calls, [
            call.set_emotion("happy"), call.speak("An answer."),
            call.set_emotion(config.EMOTION_STANDBY),
        ])


if __name__ == "__main__":
    unittest.main()
