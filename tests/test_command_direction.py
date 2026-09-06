"""Exercise direction qualification without starting audio or robot hardware."""

import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

import config


class CommandDirectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "wake_word.py"
        tree = ast.parse(source.read_text())
        functions = {
            "_mean_signed_doa", "_angular_difference",
            "_circular_mean_degrees", "_qualify_command_doa",
        }
        cls.namespace = {name: getattr(config, name) for name in dir(config)}
        cls.namespace.update(math=math, SAMPLE_RATE=config.WAKE_SAMPLE_RATE)
        # Import only pure functions: importing wake_word itself opens the mic
        # and loads wake models at module scope.
        pure = ast.Module(
            body=[node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name in functions],
            type_ignores=[],
        )
        exec(compile(pure, str(source), "exec"), cls.namespace)
        sample = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "sample"
                    for target in node.targets)
        )
        cls.sample_code = compile(ast.Expression(sample.value), str(source), "eval")
        history = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "active_wake_angles"
                    for target in node.targets)
        )
        cls.history_code = compile(ast.Expression(history.value), str(source), "eval")

    def qualify_blocks(self, count, angle=210.0):
        namespace = dict(self.namespace)
        namespace.update(
            doa=(angle, True),
            new_chunk=SimpleNamespace(size=config.WAKE_BLOCK_SIZE),
        )
        samples = [eval(self.sample_code, namespace) for _ in range(count)]
        return namespace["_qualify_command_doa"](samples)

    def test_half_second_command_has_enough_direction_evidence(self):
        result = self.qualify_blocks(8)
        self.assertAlmostEqual(result["active_seconds"], 0.512)
        self.assertTrue(result["qualified"], result["reason"])
        self.assertAlmostEqual(result["angle"], 30.0)

    def test_brief_sound_still_fails_speech_duration_requirement(self):
        result = self.qualify_blocks(3)
        self.assertAlmostEqual(result["active_seconds"], 0.192)
        self.assertFalse(result["qualified"])

    def test_settled_tail_can_confirm_variable_speech_direction(self):
        speech = [(angle, 0.064) for angle in [190.0, 210.0, 230.0] * 3]
        qualify = self.namespace["_qualify_command_doa"]
        self.assertFalse(qualify(speech)["qualified"])
        result = qualify(speech, speech + [(210.0, 0.064)] * 5)
        self.assertTrue(result["qualified"], result["reason"])
        self.assertAlmostEqual(result["angle"], 30.0)
        self.assertAlmostEqual(result["active_seconds"], 0.576)

    def test_settled_noise_cannot_replace_speech_evidence(self):
        result = self.namespace["_qualify_command_doa"](
            [(210.0, 0.064)], [(286.0, 0.064)] * 20
        )
        self.assertFalse(result["qualified"])

    def test_old_direction_samples_expire_even_without_new_speech(self):
        result = eval(self.history_code, {
            "wake_direction_history": [(10.0, 286.0), (99.0, 210.0)],
            "history_cutoff": 98.9,
        })
        self.assertEqual(result, [210.0])


if __name__ == "__main__":
    unittest.main()
