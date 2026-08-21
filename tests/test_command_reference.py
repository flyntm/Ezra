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
        heading = render_reference().splitlines()[9]
        self.assertIn("Narrates?", heading)
        self.assertNotIn("<br>", heading)


if __name__ == "__main__":
    unittest.main()
