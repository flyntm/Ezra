import unittest
from unittest.mock import patch

from bible_display import BibleDisplay, render_passage_html, split_passage_response


class BibleDisplayTests(unittest.TestCase):
    def test_splits_web_passage_from_spoken_response(self):
        result = split_passage_response(
            "1 Peter 2:1-3 from the World English Bible. Passage text."
        )

        self.assertEqual(
            result,
            (
                "1 Peter 2:1-3 from the World English Bible",
                "Passage text.",
                (),
            ),
        )

    def test_does_not_display_clarification_prompts(self):
        self.assertIsNone(
            split_passage_response("Do you mean First Peter or Second Peter?")
        )

    def test_html_escapes_passage_content(self):
        rendered = render_passage_html("John 3:16", "Love < sacrifice")

        self.assertIn("John 3:16", rendered)
        self.assertIn("Love &lt; sacrifice", rendered)
        self.assertNotIn("Love < sacrifice", rendered)

    def test_renders_verse_numbers_as_superscript(self):
        rendered = render_passage_html(
            "1 Peter 2:1-2 from the World English Bible",
            "First verse. Second verse.",
            ((1, "First verse."), (2, "Second verse.")),
        )

        self.assertIn("<sup>1</sup>First verse.", rendered)
        self.assertIn("<sup>2</sup>Second verse.", rendered)

    def test_display_progress_tracks_reading_and_finishes_at_bottom(self):
        display = BibleDisplay("Psalm 1", "word " * 260)

        with patch("bible_display.time.monotonic", side_effect=[10.0, 60.0]):
            display.begin_reading()
            self.assertAlmostEqual(display.reading_progress(), 0.5)

        display.finish_reading()
        self.assertEqual(display.reading_progress(), 1.0)

    def test_rendered_page_polls_for_scroll_progress(self):
        rendered = render_passage_html("Psalm 1", "Long passage")

        self.assertIn("fetch('/state'", rendered)
        self.assertIn("readingY-innerHeight*readingPosition", rendered)
        self.assertIn("fetch('/pause'", rendered)
        self.assertIn("event.key==='ArrowUp'||event.key==='ArrowDown'", rendered)
        self.assertIn("state.scrolls", rendered)
        self.assertNotIn("centerPassageStart", rendered)
        self.assertIn("if(readingY<=innerHeight*readingPosition)", rendered)

    def test_voice_scroll_requests_are_queued_as_viewport_steps(self):
        display = BibleDisplay("Psalm 1", "Long passage")

        display.queue_scroll("down")
        display.queue_scroll("up")

        self.assertEqual(display.take_scroll_requests(), [1, -1])
        self.assertEqual(display.take_scroll_requests(), [])

    def test_display_only_mode_does_not_enable_speech_following(self):
        display = BibleDisplay("Psalm 1", "Long passage", read_along=False)

        self.assertFalse(display.read_along)
        display.begin_reading()
        self.assertEqual(display.reading_session, 1)

    def test_stopped_reading_freezes_until_reading_starts_again(self):
        display = BibleDisplay("Psalm 1", "word " * 260)
        with patch("bible_display.time.monotonic", return_value=10.0) as clock:
            display.begin_reading()
            clock.return_value = 35.0
            display.stop_reading()
            clock.return_value = 200.0
            self.assertEqual(display.reading_progress(), 0.25)
            display.stop_reading()
            self.assertEqual(display.reading_progress(), 0.25)
            display.begin_reading()
            self.assertEqual(display.reading_progress(), 0.0)

    def test_ending_completed_reading_keeps_bottom_position(self):
        display = BibleDisplay("Psalm 1", "word " * 260)
        display.begin_reading()
        display.finish_reading()
        display.stop_reading()
        self.assertEqual(display.reading_progress(), 1.0)

    def test_ending_before_playback_keeps_top_position(self):
        display = BibleDisplay("Psalm 1", "word " * 260)
        display.stop_reading()
        self.assertEqual(display.reading_progress(), 0.0)

    def test_pausing_reading_freezes_scroll_until_resumed(self):
        display = BibleDisplay("Psalm 1", "word " * 260)
        with patch(
            "bible_display.time.monotonic", side_effect=[10.0, 35.0, 200.0, 200.0]
        ):
            display.begin_reading()
            display.toggle_reading()
            self.assertEqual(display.reading_progress(), 0.25)
            display.toggle_reading()
            self.assertEqual(display.reading_progress(), 0.25)


if __name__ == "__main__":
    unittest.main()
