"""Checks for the generated Ezra command reference."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from build_command_reference import (  # noqa: E402
    OUTPUT_PATH,
    _table,
    render_reference,
)


class CommandReferenceTests(unittest.TestCase):
    def test_command_reference_is_current(self):
        self.assertEqual(OUTPUT_PATH.read_text(encoding="utf-8"), render_reference())

    def test_alternate_commands_use_indented_rendered_lines(self):
        table = _table(
            ("Command", "What it does"),
            (("Next slide / Forward / Continue", "Moves onward.",),),
        )

        self.assertIn("| Next slide", table)
        self.assertIn("|     Forward", table)
        self.assertIn("|     Continue", table)

    def test_description_rendered_lines_are_at_most_seventy_characters(self):
        description = "A moderately long description " * 8
        rendered = _table(("Command", "What it does"), (("Test", description),))

        description_cells = [line.split("|")[2].strip() for line in rendered.splitlines()[2:]]
        self.assertTrue(all(len(cell) <= 70 for cell in description_cells))

    def test_narration_heading_is_compact_plain_markdown(self):
        heading = next(line for line in render_reference().splitlines()
                       if line.startswith("| Command"))
        self.assertIn("Narrates?", heading)
        self.assertIn("Presentation keys", heading)
        self.assertNotIn("<br>", heading)

    def test_presentation_keyboard_controls_are_listed(self):
        reference = render_reference()
        self.assertIn("Right / Down", reference)
        self.assertIn("Left / Up", reference)
        self.assertIn("Space / Escape", reference)
        self.assertIn("Enter", reference)
        self.assertIn("Number + Enter", reference)

    def test_pi_recovery_shortcuts_are_listed(self):
        reference = render_reference()
        self.assertIn("Ctrl+Alt+R", reference)
        self.assertIn("Ctrl+Alt+P", reference)
        reveal_line = next(
            line for line in reference.splitlines() if line.startswith("| Reveal the answer")
        )
        self.assertEqual(reveal_line.split("|")[4].strip(), "")


if __name__ == "__main__":
    unittest.main()
