import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path
import zipfile

from presentations import acts_lesson_one
from presentations.acts_lesson_one import (
    ActsLessonOneSession,
    DECK_PATH,
    handle_active_command,
    is_rehearsal_request,
    is_start_request,
    _parse_slide_number,
    requested_start_slide,
)
from presentations.powerpoint import PowerPointDeck
from presentations.browser_slideshow import render_pptx_html
from presentations.common import (
    INTRODUCTION,
    INTRODUCTION_OFFLINE_NOTICE,
    is_name_origin_request,
    present_introduction,
    present_name_origin,
)


class FakeSlideshow:
    def __init__(self):
        self.actions = []

    def start(self):
        self.actions.append("start")

    def next(self):
        self.actions.append("next")

    def previous(self):
        self.actions.append("previous")

    def go_to(self, slide_index):
        self.actions.append(("go_to", slide_index))

    def close(self):
        self.actions.append("close")

    def reveal(self):
        self.actions.append("reveal")


class PowerPointDeckTests(unittest.TestCase):
    def test_lesson_deck_has_speaker_notes_for_every_slide(self):
        deck = PowerPointDeck.load(DECK_PATH)
        self.assertEqual(deck.slide_count, 17)
        self.assertTrue(all(note.strip() for note in deck.notes))
        self.assertIn("Welcome to Lesson One", deck.notes[0])

    def test_slide_without_notes_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "minimal.pptx"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr("ppt/slides/slide1.xml", "<slide />")
            deck = PowerPointDeck.load(path)
        self.assertEqual(deck.notes, ("",))

    def test_note_markers_are_parsed_and_never_spoken(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "markers.pptx"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "ppt/slides/slide1.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/'
                    'presentationml/2006/main" />',
                )
                package.writestr(
                    "ppt/notesSlides/notesSlide1.xml",
                    '<p:notes xmlns:p="http://schemas.openxmlformats.org/'
                    'presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/'
                    'drawingml/2006/main">'
                    '<a:p><a:r><a:t>This is the script. NEXT SLIDE is ordinary '
                    'text.</a:t></a:r></a:p>'
                    '<a:p><a:r><a:t>[NEXT SLIDE]</a:t></a:r></a:p>'
                    '<a:p><a:r><a:t>[Sources]</a:t></a:r></a:p>'
                    '<a:p><a:r><a:t>- Acts 1:8</a:t></a:r></a:p>'
                    '</p:notes>',
                )
            deck = PowerPointDeck.load(path)

        self.assertEqual(
            deck.notes,
            ("This is the script. NEXT SLIDE is ordinary text.",),
        )
        self.assertEqual(deck.auto_advance, (True,))

    def test_title_case_next_slide_marker_is_also_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "title-case-marker.pptx"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "ppt/slides/slide1.xml",
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/'
                    'presentationml/2006/main" />',
                )
                package.writestr(
                    "ppt/notesSlides/notesSlide1.xml",
                    '<p:notes xmlns:p="http://schemas.openxmlformats.org/'
                    'presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/'
                    'drawingml/2006/main">'
                    '<a:p><a:r><a:t>Speak this. [Next Slide]</a:t></a:r></a:p>'
                    '</p:notes>',
                )
            deck = PowerPointDeck.load(path)

        self.assertEqual(deck.notes, ("Speak this.",))
        self.assertEqual(deck.auto_advance, (True,))

    def test_browser_conversion_contains_slides_and_reveal_content(self):
        rendered = render_pptx_html(DECK_PATH)
        self.assertEqual(rendered.count('<section class="slide"'), 17)
        self.assertIn("Overview — What Is Acts?", rendered)
        self.assertIn("event.key==='Escape'||event.key===' '", rendered)
        self.assertIn("fetch('/skip'", rendered)


class ActsSessionTests(unittest.TestCase):
    def setUp(self):
        self.spoken = []
        self.slides = FakeSlideshow()

        def speak(text, **callbacks):
            self.spoken.append(text)
            callbacks.get("on_playback_start", lambda: None)()
            callbacks.get("on_playback_complete", lambda: None)()
            return False

        self.session = ActsLessonOneSession(
            speak,
            self.slides,
        )
        self.session.deck = replace(
            self.session.deck,
            auto_advance=(False,) * self.session.deck.slide_count,
        )

    def test_navigation_stays_synchronized_with_scripts(self):
        self.session.start()
        self.session.next()
        self.session.next()
        self.session.next()
        self.session.previous()
        self.session.stop()
        self.assertEqual(
            self.slides.actions,
            [
                "start",
                ("go_to", 1),
                ("go_to", 2),
                ("go_to", 3),
                "reveal",
                ("go_to", 2),
                "close",
            ],
        )
        self.assertEqual(len(self.spoken), 4)
        self.assertIn("three decades", self.spoken[1])
        self.assertIn("investigated the events carefully", self.spoken[2])
        self.assertIn("carefully investigated", self.spoken[3])
        self.assertNotIn("[Sources]", " ".join(self.spoken))

    def test_next_slide_reveals_answer_before_reading_its_script(self):
        self.session.start()
        self.session.go_to(3)
        spoken_before_next = len(self.spoken)
        self.session.next()
        self.assertEqual(self.slides.actions[-2:], [("go_to", 3), "reveal"])
        self.assertTrue(self.session.answer_revealed)
        self.assertEqual(len(self.spoken), spoken_before_next + 1)
        self.assertIn("carefully investigated", self.spoken[-1])

    def test_previous_slide_reveals_answer_without_reading_its_script(self):
        self.session.start()
        self.session.go_to(5)
        spoken_before_previous = len(self.spoken)
        self.session.previous()
        self.assertEqual(self.slides.actions[-2:], [("go_to", 3), "reveal"])
        self.assertTrue(self.session.answer_revealed)
        self.assertEqual(len(self.spoken), spoken_before_previous)

    def test_command_patterns(self):
        self.assertTrue(is_start_request("start the Acts presentation"))
        self.assertTrue(is_start_request("start the presentation"))
        self.assertTrue(is_start_request("start presentation"))
        self.assertTrue(is_rehearsal_request("rehearse the presentation"))
        self.assertFalse(is_start_request("what is an act?"))

    def test_presentation_can_start_on_a_numbered_slide(self):
        self.assertEqual(requested_start_slide("start the presentation"), 1)
        self.assertEqual(
            requested_start_slide("start the presentation on slide 5"),
            5,
        )
        self.assertEqual(
            requested_start_slide("start presentation on slide number five"),
            5,
        )
        self.assertEqual(
            requested_start_slide("start the presentation with slide 5"),
            5,
        )
        self.assertEqual(
            requested_start_slide("start the presentation from slide one hundred"),
            100,
        )

    def test_start_on_slide_displays_and_reads_requested_slide(self):
        self.session.start(slide_number=5)
        self.assertEqual(self.slides.actions[:2], ["start", ("go_to", 4)])
        self.assertEqual(self.session.slide_index, 4)
        self.assertIn("Question two", self.spoken[-1])

    def test_marker_advances_only_after_playback_completion(self):
        self.session.deck = replace(
            self.session.deck,
            auto_advance=(True,) + self.session.deck.auto_advance[1:],
        )
        self.session.start()
        self.assertEqual(self.session.slide_index, 1)
        self.assertEqual(self.slides.actions, ["start", ("go_to", 1)])
        self.assertEqual(len(self.spoken), 2)
        self.assertIn("three decades", self.spoken[-1])

    def test_marker_does_not_advance_without_playback_completion(self):
        session = ActsLessonOneSession(
            lambda text, **callbacks: callbacks["on_playback_start"]() or False,
            self.slides,
        )
        session.deck = replace(
            session.deck,
            auto_advance=(True,) + session.deck.auto_advance[1:],
        )
        session.start()
        self.assertEqual(session.slide_index, 0)
        self.assertEqual(self.slides.actions, ["start"])

    def test_speech_interruption_keeps_presentation_active(self):
        def interrupted_speak(text, **callbacks):
            callbacks.get("on_playback_start", lambda: None)()
            return True

        session = ActsLessonOneSession(interrupted_speak, self.slides)
        session.deck = replace(
            session.deck,
            auto_advance=(True,) + session.deck.auto_advance[1:],
        )
        self.assertTrue(session.start())
        self.assertTrue(session.active)
        self.assertEqual(session.slide_index, 0)
        self.assertEqual(self.slides.actions, ["start"])

    def test_stop_presentation_is_claimed_when_inactive(self):
        spoken = []
        self.assertTrue(
            handle_active_command(
                "stop the presentation",
                lambda text: spoken.append(text),
            )
        )
        self.assertEqual(spoken, ["There is no active presentation."])

    def test_jump_to_slide_does_not_read_script(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        spoken_before_jump = list(self.spoken)
        self.assertTrue(handle_active_command("go to slide 2", self.session.speak))
        self.assertEqual(self.slides.actions[-1], ("go_to", 1))
        self.assertEqual(self.spoken, spoken_before_jump)
        self.assertEqual(self.session.slide_index, 1)

    def test_jump_to_slide_and_explain_reads_script(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        self.assertTrue(
            handle_active_command("go to slide 2 and explain", self.session.speak)
        )
        self.assertEqual(self.session.slide_index, 1)
        self.assertIn("three decades", self.spoken[-1])

    def test_previous_and_explain_reads_previous_slide_script(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        handle_active_command("go to slide 3", self.session.speak)
        spoken_before_previous = len(self.spoken)
        self.assertTrue(
            handle_active_command("previous and explain", self.session.speak)
        )
        self.assertEqual(self.session.slide_index, 1)
        self.assertEqual(len(self.spoken), spoken_before_previous + 1)

    def test_jump_to_answer_slide_displays_answers_without_reading(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        spoken_before_jump = list(self.spoken)
        self.assertTrue(handle_active_command("go to slide 4", self.session.speak))
        self.assertEqual(self.slides.actions[-2:], [("go_to", 3), "reveal"])
        self.assertEqual(self.session.slide_index, 3)
        self.assertTrue(self.session.answer_revealed)
        self.assertEqual(self.spoken, spoken_before_jump)

    def test_slide_number_words_are_supported_through_one_hundred(self):
        self.assertEqual(_parse_slide_number("four"), 4)
        self.assertEqual(_parse_slide_number("fourth"), 4)
        self.assertEqual(_parse_slide_number("forty two"), 42)
        self.assertEqual(_parse_slide_number("ninety-ninth"), 99)
        self.assertEqual(_parse_slide_number("one hundred"), 100)
        self.assertIsNone(_parse_slide_number("one hundred one"))

    def test_show_numbered_slide_phrasing_is_claimed(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        self.assertTrue(handle_active_command("show the 4th slide", self.session.speak))
        self.assertEqual(self.session.slide_index, 3)
        self.assertFalse(handle_active_command("fourth slide please", self.session.speak))

    def test_show_fifth_slide_restores_presentation_from_bible_display(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)

        with patch(
            "presentations.acts_lesson_one.close_bible_display"
        ) as close_display:
            handled = handle_active_command(
                "show the fifth slide",
                self.session.speak,
            )

        self.assertTrue(handled)
        self.assertEqual(self.session.slide_index, 4)
        close_display.assert_called_once_with()

    def test_spoken_ordinal_jump_and_current_slide_narration(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        self.assertTrue(handle_active_command("go to slide number two", self.session.speak))
        self.assertEqual(len(self.spoken), 1)
        self.assertTrue(
            handle_active_command(
                "please tell us about this slide",
                self.session.speak,
            )
        )
        self.assertEqual(len(self.spoken), 2)
        self.assertIn("three decades", self.spoken[-1])

    def test_question_jump_uses_label_instead_of_slide_number(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        spoken_before_jump = list(self.spoken)
        self.assertTrue(handle_active_command("show question 4", self.session.speak))
        self.assertEqual(self.slides.actions[-1], ("go_to", 8))
        self.assertEqual(self.session.slide_index, 8)
        self.assertEqual(self.spoken, spoken_before_jump)

    def test_question_jump_accepts_spoken_number_word(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        self.assertTrue(handle_active_command("show question seven", self.session.speak))
        self.assertEqual(self.slides.actions[-1], ("go_to", 13))
        self.assertEqual(self.session.slide_index, 13)

    def test_question_jump_and_explain_reads_script(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        spoken_before_jump = len(self.spoken)
        self.assertTrue(
            handle_active_command("show question four and explain", self.session.speak)
        )
        self.assertEqual(self.session.slide_index, 8)
        self.assertEqual(len(self.spoken), spoken_before_jump + 1)

    def test_plural_answers_reveals_answer(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        handle_active_command("go to slide 3", self.session.speak)
        self.assertTrue(handle_active_command("show us the answers", self.session.speak))
        self.assertEqual(self.slides.actions[-2:], [("go_to", 3), "reveal"])
        self.assertEqual(self.slides.actions[-1], "reveal")
        self.assertEqual(self.session.slide_index, 3)
        self.assertIn("carefully investigated", self.spoken[-1])

    def test_answers_please_advances_reveals_and_reads(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        handle_active_command("go to slide three", self.session.speak)
        self.assertTrue(handle_active_command("the answers please", self.session.speak))
        self.assertEqual(self.slides.actions[-2:], [("go_to", 3), "reveal"])
        self.assertEqual(self.session.slide_index, 3)
        self.assertIn("carefully investigated", self.spoken[-1])

    def test_answer_narration_uses_keyboard_skip_enabled_speech_path(self):
        calls = []

        def speak(text, **options):
            calls.append((text, options))
            options.get("on_playback_start", lambda: None)()
            options.get("on_playback_complete", lambda: None)()
            return False

        session = ActsLessonOneSession(speak, self.slides)
        session.deck = replace(
            session.deck,
            auto_advance=(False,) * session.deck.slide_count,
        )
        session.start()
        session.go_to(3)
        session.reveal()
        self.assertTrue(calls[-1][1]["allow_keyboard_skip"])
        self.assertIn("on_playback_complete", calls[-1][1])

    def test_display_answers_reveals_without_reading_script(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        handle_active_command("go to slide number third", self.session.speak)
        spoken_before_reveal = list(self.spoken)
        self.assertTrue(handle_active_command("display the answers", self.session.speak))
        self.assertEqual(self.slides.actions[-2:], [("go_to", 3), "reveal"])
        self.assertEqual(self.slides.actions[-1], "reveal")
        self.assertEqual(self.session.slide_index, 3)
        self.assertEqual(self.spoken, spoken_before_reveal)

    def test_display_answers_and_explain_reads_script(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        handle_active_command("go to slide three", self.session.speak)
        spoken_before_reveal = len(self.spoken)
        self.assertTrue(
            handle_active_command("display the answers and explain", self.session.speak)
        )
        self.assertEqual(self.session.slide_index, 3)
        self.assertEqual(len(self.spoken), spoken_before_reveal + 1)

    def test_out_of_range_slide_reports_deck_size(self):
        self.session.start()
        acts_lesson_one._session = self.session
        self.addCleanup(setattr, acts_lesson_one, "_session", None)
        self.assertTrue(handle_active_command("go to slide 18", self.session.speak))
        self.assertEqual(self.spoken[-1], "This presentation has 17 slides.")
        self.assertEqual(self.session.slide_index, 0)


class CommonPresentationTests(unittest.TestCase):
    def test_offline_introduction_adds_notice_after_unchanged_script(self):
        spoken = []
        interrupted = present_introduction(
            lambda text, **_kwargs: spoken.append(text) or False,
            offline=True,
        )
        self.assertFalse(interrupted)
        self.assertEqual(
            spoken,
            [f"{INTRODUCTION} {INTRODUCTION_OFFLINE_NOTICE}"],
        )

    def test_online_introduction_does_not_add_offline_notice(self):
        spoken = []
        present_introduction(
            lambda text, **_kwargs: spoken.append(text) or False,
            offline=False,
        )
        self.assertEqual(spoken, [INTRODUCTION])
        self.assertNotIn(INTRODUCTION_OFFLINE_NOTICE, spoken)

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
        self.assertIn("Bible; he was a priest", spoken[0])
        self.assertIn("smart guy. — Since", spoken[0])
        self.assertIn("presentations", spoken[0])
        self.assertIn("Raspberry Pi", spoken[0])


if __name__ == "__main__":
    unittest.main()
