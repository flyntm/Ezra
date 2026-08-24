"""Checks for Ezra's local voice commands."""

import unittest

from command_phrases import GOOD_NIGHT_RESPONSE, looks_like_good_night_command


class GoodNightCommandTests(unittest.TestCase):
    def test_good_night_command_patterns(self):
        self.assertTrue(
            looks_like_good_night_command("say good night to everyone")
        )
        self.assertTrue(looks_like_good_night_command("say good night"))
        self.assertTrue(looks_like_good_night_command("Ezra, say good night"))
        self.assertTrue(
            looks_like_good_night_command("say Ezra say goodnight to everyone")
        )
        self.assertTrue(looks_like_good_night_command("goodnight to everyone"))
        self.assertFalse(looks_like_good_night_command("good night, Ezra"))
        self.assertFalse(
            looks_like_good_night_command("Why did Paul say good night?")
        )

    def test_good_night_response_includes_smile_gesture(self):
        self.assertEqual(
            GOOD_NIGHT_RESPONSE,
            "[Humor]Good night to everyone. "
            "Thank you for letting me participate. Tonight, you almost made me feel "
            "human.[/Humor] [Smile]",
        )


if __name__ == "__main__":
    unittest.main()
