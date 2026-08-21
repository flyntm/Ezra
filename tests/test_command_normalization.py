import unittest

from command_normalization import is_unclear_single_word
from presentations.lesson_presentation import is_rehearsal_request


class RehearsalCommandTests(unittest.TestCase):
    def test_single_rehearsal_words_are_rejected_as_unclear(self):
        for command in ("rehearse", "preview", "test"):
            with self.subTest(command=command):
                self.assertTrue(is_unclear_single_word(command))
                self.assertFalse(is_rehearsal_request(command))

    def test_rehearsal_phrases_require_presentation_context(self):
        for command in (
            "rehearse the presentation",
            "preview the presentation",
            "test the presentation",
        ):
            with self.subTest(command=command):
                self.assertFalse(is_unclear_single_word(command))
                self.assertTrue(is_rehearsal_request(command))

    def test_arbitrary_single_word_remains_unclear(self):
        self.assertTrue(is_unclear_single_word("pfft"))


if __name__ == "__main__":
    unittest.main()
