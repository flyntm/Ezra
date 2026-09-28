"""Exercise normalized command dispatch without loading robot hardware."""

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import command_phrases
from command_normalization import is_cancel_command, strip_wake_word
from bible_service import parse_bible_reference
from live_info import _is_weather_query


class CommandRoutingTests(unittest.TestCase):
    def test_sleep_request_enters_sleep_without_shutdown(self):
        for text in (
            "Ezra, go to sleep",
            "Hey Ezra, you're going to sleep.",
            "That was to sleep.",
            "No, just state.",
            "Please go to sleep",
            "Could you please go to sleep now?",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.dispatch(text))
                self.ns["enter_sleep"].assert_called_once_with()
                self.assertFalse(self.ns["state"].shutting_down)
                self.ns["request_system_poweroff"].assert_not_called()
                self.ns["handle_presentation_command"].assert_not_called()

    def test_sleep_questions_and_negations_are_not_commands(self):
        for text in (
            "Don't go to sleep",
            "Why do people go to sleep?",
            "Explain go to sleep",
            "How can I go to sleep?",
        ):
            with self.subTest(text=text):
                self.assertFalse(self.dispatch(text))
                self.ns["enter_sleep"].assert_not_called()

    def test_look_request_routes_locally_and_reports_missing_direction(self):
        tracker = Mock()
        with patch.dict(
            "sys.modules",
            {
                "robot.head_tracking": SimpleNamespace(head_tracker=tracker),
            },
        ), patch("config.ENABLE_HEAD_TRACKING", True), patch(
            "config.ENABLE_INTERACTION_DIAGNOSTIC", False
        ):
            tracker.face_command_speaker.return_value = True
            self.assertTrue(self.dispatch("Ezra, look over here!"))
            tracker.face_command_speaker.assert_called_once_with()
            self.ns["speak"].assert_not_called()
            self.ns["handle_presentation_command"].assert_not_called()
            tracker.face_command_speaker.return_value = False
            self.assertTrue(self.dispatch("look at me"))
            self.assertIn("again", self.ns["speak"].call_args.args[0])

    def test_look_request_accepts_polite_forms_but_not_quoted_or_negated_text(self):
        for text in (
            "look over here",
            "Ezra look here",
            "face me",
            "Could you please look at me?",
            "Please look over here",
        ):
            self.assertTrue(command_phrases.looks_like_look_here_command(text), text)
        for text in (
            "Don't look over here",
            "Explain look over here",
            "Why did he say look at me?",
            "look over here means what",
        ):
            self.assertFalse(command_phrases.looks_like_look_here_command(text), text)

    def dispatch(self, text, **overrides):
        source = Path(__file__).resolve().parents[1] / "command.py"
        tree = ast.parse(source.read_text())
        helper = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "handle_local_command"
        )
        self.ns = dict(vars(command_phrases))
        self.ns.update(
            state=SimpleNamespace(shutting_down=False),
            speak=Mock(),
            operating_mode=SimpleNamespace(
                status_requested=lambda _: False, requested_mode=lambda _: None
            ),
            GOODBYE_TEXT="Goodbye!",
            SHUTDOWN_SLEEP_SETTLE_SECONDS=0,
            time=Mock(),
            datetime=datetime,
            is_cancel_command=is_cancel_command,
        )
        for name in (
            "handle_presentation_command",
            "is_rehearsal_request",
            "is_presentation_request",
            "looks_like_volume_command",
            "is_introduction_request",
            "is_name_origin_request",
        ):
            self.ns[name] = Mock(return_value=False)
        for name in ("get_bible_response", "get_live_info_response"):
            self.ns[name] = Mock(return_value=None)
        self.ns.update(
            ENABLE_BIBLE_DISPLAY=True,
            scroll_active_bible_display=Mock(return_value=False),
            split_passage_response=Mock(return_value=None),
            show_bible_passage=Mock(),
        )
        for name in ("enter_sleep", "reset_idle_timer", "wake_up"):
            self.ns[name] = Mock()
        self.ns["request_system_poweroff"] = Mock(return_value=True)
        self.ns.update(overrides)
        exec(
            compile(ast.Module(body=[helper], type_ignores=[]), str(source), "exec"),
            self.ns,
        )
        return self.ns["handle_local_command"](strip_wake_word(text))

    def test_display_bible_request_shows_text_without_speaking_it(self):
        for verb in ("show", "display", "displaying", "just playing"):
            with self.subTest(verb=verb):
                response = "John 3:16 from the World English Bible. Verse text."
                split_response = Mock(return_value=("John 3:16", "Verse text.", ()))
                show_passage = Mock()

                self.assertTrue(
                    self.dispatch(
                        f"{verb} John 3:16",
                        get_bible_response=Mock(return_value=response),
                        split_passage_response=split_response,
                        show_bible_passage=show_passage,
                    )
                )

                show_passage.assert_called_once_with(
                    "John 3:16", "Verse text.", (), read_along=False
                )
                self.assertEqual(
                    self.ns["speak"].call_args.args[0], "Displaying John 3:16."
                )

    def test_scroll_voice_command_targets_active_bible_display(self):
        for phrase, direction in (
            ("scroll up", "up"),
            ("scroll down", "down"),
            ("roll up", "up"),
            ("roll down", "down"),
            ("show up", "up"),
            ("show down", "down"),
        ):
            with self.subTest(phrase=phrase):
                scroll = Mock(return_value=True)
                self.assertTrue(
                    self.dispatch(
                        phrase,
                        scroll_active_bible_display=scroll,
                    )
                )
                scroll.assert_called_once_with(direction)
                self.ns["speak"].assert_not_called()

    def test_show_scroll_alias_falls_through_without_active_bible_display(self):
        scroll = Mock(return_value=False)

        self.assertFalse(self.dispatch("show up", scroll_active_bible_display=scroll))

        scroll.assert_called_once_with("up")
        self.ns["handle_presentation_command"].assert_called_once()

    def test_questions_and_negations_never_exit_or_power_off(self):
        for text in (
            "Ezra how do I quit smoking?",
            "Explain a government shutdown",
            "Do not shut down",
            "Why did the program exit?",
            "Tell me what power off means",
            "Please don't quit",
        ):
            with self.subTest(text=text):
                self.assertFalse(self.dispatch(text))
                self.assertFalse(self.ns["state"].shutting_down)
                self.ns["request_system_poweroff"].assert_not_called()
                self.ns["enter_sleep"].assert_not_called()

    def test_trailing_cancel_or_chancel_discards_the_utterance_silently(self):
        for text in (
            "cancel",
            "I'm going to get confused and say the words cancel",
            "I'm going to get confused and say the words chancel",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.dispatch(text))

                self.ns["speak"].assert_not_called()
                self.ns["reset_idle_timer"].assert_called_once_with()
                self.ns["handle_presentation_command"].assert_not_called()

    def test_explicit_exit_and_poweroff_remain_available(self):
        for text in (
            "Ezra quit",
            "Exit program",
            "Please stop the program",
            "Could you please exit the application?",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.dispatch(text))
                self.assertTrue(self.ns["state"].shutting_down)
                self.assertTrue(self.ns["state"].exit_requested)
                self.ns["request_system_poweroff"].assert_not_called()
        for text in (
            "Shutdown",
            "Ezra please shut down the Pi",
            "Power off",
            "Could you please power off the system now?",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.dispatch(text))
                self.ns["request_system_poweroff"].assert_called_once_with()

    def test_scripture_separators_survive_voice_normalization(self):
        for text, end in (
            ("Ezra, read John 3:16.", None),
            ("Hey Ezra read John 3:16-18", 18),
        ):
            reference = parse_bible_reference(strip_wake_word(text))
            self.assertEqual(
                (reference.chapter, reference.verse_start, reference.verse_end),
                (3, 16, end),
            )
        self.assertEqual(
            strip_wake_word("Ezra, what is 3.14 divided by 1/2?"),
            "what is 3.14 divided by 1/2",
        )

    def test_weather_does_not_claim_explanations_or_substrings(self):
        for text in (
            "explain how your brain works",
            "what is training",
            "why does it rain",
            "how does snow form",
            "what is body temperature",
        ):
            self.assertFalse(_is_weather_query(text), text)
        for text in (
            "what is the weather today",
            "weather in Dallas",
            "how is the weather today",
            "will it rain tomorrow",
            "is it snowing outside",
            "what is the temperature",
        ):
            self.assertTrue(_is_weather_query(text), text)
