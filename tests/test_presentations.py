import tempfile
import unittest
from pathlib import Path
import zipfile

from presentations.acts_lesson_one import (
    ActsLessonOneSession,
    DECK_PATH,
    handle_active_command,
    is_rehearsal_request,
    is_start_request,
)
from presentations.powerpoint import PowerPointDeck
from presentations.browser_slideshow import render_pptx_html
from presentations.common import is_name_origin_request, present_name_origin


class FakeSlideshow:
    def __init__(self):
        self.actions = []

    def start(self):
        self.actions.append("start")

    def next(self):
        self.actions.append("next")

    def previous(self):
        self.actions.append("previous")

    def close(self):
        self.actions.append("close")

    def reveal(self):
        self.actions.append("reveal")


class PowerPointDeckTests(unittest.TestCase):
    def test_prototype_has_two_slides_and_notes(self):
        deck = PowerPointDeck.load(DECK_PATH)
        self.assertEqual(deck.slide_count, 2)
        self.assertIn("continuing His work", deck.notes[0])
        self.assertIn("orderly account", deck.notes[1])

    def test_slide_without_notes_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "minimal.pptx"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr("ppt/slides/slide1.xml", "<slide />")
            deck = PowerPointDeck.load(path)
        self.assertEqual(deck.notes, ("",))

    def test_browser_conversion_contains_slides_and_reveal_content(self):
        rendered = render_pptx_html(DECK_PATH)
        self.assertEqual(rendered.count('<section class="slide"'), 2)
        self.assertIn("What Is Acts?", rendered)
        self.assertIn('class="shape reveal"', rendered)


class ActsSessionTests(unittest.TestCase):
    def setUp(self):
        self.spoken = []
        self.slides = FakeSlideshow()
        self.session = ActsLessonOneSession(
            lambda text: self.spoken.append(text) or False,
            self.slides,
        )

    def test_navigation_stays_synchronized_with_scripts(self):
        self.session.start()
        self.session.next()
        self.session.reveal()
        self.session.previous()
        self.session.stop()
        self.assertEqual(
            self.slides.actions,
            ["start", "next", "reveal", "previous", "close"],
        )
        self.assertEqual(len(self.spoken), 4)
        self.assertIn("first question", self.spoken[1])
        self.assertIn("orderly account", self.spoken[2])

    def test_command_patterns(self):
        self.assertTrue(is_start_request("start the Acts presentation"))
        self.assertTrue(is_rehearsal_request("rehearse the presentation"))
        self.assertFalse(is_start_request("what is an act?"))

    def test_stop_presentation_is_claimed_when_inactive(self):
        spoken = []
        self.assertTrue(
            handle_active_command(
                "stop the presentation",
                lambda text: spoken.append(text),
            )
        )
        self.assertEqual(spoken, ["There is no active presentation."])


class CommonPresentationTests(unittest.TestCase):
    def test_name_origin_command_patterns(self):
        self.assertTrue(
            is_name_origin_request("Ezra, tell us where your name comes from")
        )
        self.assertTrue(is_name_origin_request("How did you get your name?"))
        self.assertTrue(is_name_origin_request("Why are you named Ezra?"))
        self.assertFalse(is_name_origin_request("What is your name?"))

    def test_name_origin_is_delivered_as_one_naturally_paced_section(self):
        spoken = []
        interrupted = present_name_origin(
            lambda text, **_kwargs: spoken.append(text) or False,
        )
        self.assertFalse(interrupted)
        self.assertEqual(len(spoken), 1)
        self.assertIn("Bible. He was a priest", spoken[0])
        self.assertIn("presentations", spoken[0])
        self.assertIn("Raspberry Pi", spoken[0])


if __name__ == "__main__":
    unittest.main()
