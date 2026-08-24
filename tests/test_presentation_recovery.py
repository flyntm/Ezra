import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import presentation_recovery


class PresentationRecoveryTests(unittest.TestCase):
    def test_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            deck = directory / "lesson.pptx"
            deck.touch()
            state_path = directory / "presentation.json"
            with patch.object(presentation_recovery, "STATE_PATH", state_path):
                presentation_recovery.save(deck, 7, revealed=True)
                self.assertEqual(
                    presentation_recovery.load(),
                    {
                        "deck_path": str(deck.resolve()),
                        "slide_number": 7,
                        "revealed": True,
                    },
                )
                presentation_recovery.clear()
                self.assertIsNone(presentation_recovery.load())

    def test_missing_deck_is_not_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "presentation.json"
            with patch.object(presentation_recovery, "STATE_PATH", state_path):
                presentation_recovery.save(Path(directory) / "missing.pptx", 2)
                self.assertIsNone(presentation_recovery.load())


if __name__ == "__main__":
    unittest.main()
