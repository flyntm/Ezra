import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from bible_service import (
    BiblePassage,
    BibleReference,
    BibleService,
    get_bible_response,
    parse_bible_reference,
)
from tools.build_web_bible import ChapterParser


class BibleReferenceTests(unittest.TestCase):
    def test_numeric_single_verse(self):
        self.assertEqual(
            parse_bible_reference("Please read John 3:16"),
            BibleReference("JHN", "John", 3, 16, None),
        )

    def test_spoken_chapter_and_verse_range(self):
        self.assertEqual(
            parse_bible_reference(
                "read first Corinthians chapter thirteen verses four through seven"
            ),
            BibleReference("1CO", "1 Corinthians", 13, 4, 7),
        )

    def test_chapter_reference(self):
        self.assertEqual(
            parse_bible_reference("Psalm twenty three"),
            BibleReference("PSA", "Psalms", 23),
        )

    def test_non_reference_is_not_claimed(self):
        self.assertIsNone(parse_bible_reference("Who was the apostle John?"))

    def test_ambiguous_peter_passage_asks_for_book_number(self):
        response = get_bible_response(
            "can you read peter chapter 2 verses 1 through 10"
        )

        self.assertEqual(response, "Do you mean First Peter or Second Peter?")

    @patch("bible_service._last_reference", None)
    def test_bookless_follow_up_asks_which_book(self):
        response = get_bible_response(
            "can you repeat chapter 2 verses 1 through 10"
        )

        self.assertEqual(
            response,
            "Which book of the Bible would you like me to read?",
        )


class WebBibleImporterTests(unittest.TestCase):
    def test_strips_verse_labels_and_footnotes(self):
        parser = ChapterParser()
        parser.feed(
            '<div class="main"><span class="verse" id="V16">16&#160;</span>'
            'For God so loved the world'
            '<a class="notemark" href="#note">[1]<span>footnote text</span></a>.'
            '</div>'
        )
        parser.close()

        self.assertEqual(parser.verses, [(16, "For God so loved the world.")])


class BibleServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        self.addCleanup(temporary.close)
        self.database = Path(temporary.name)
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE verses (book_id TEXT, book_name TEXT, "
                "chapter INTEGER, verse INTEGER, text TEXT)"
            )
            connection.executemany(
                "INSERT INTO verses VALUES (?, ?, ?, ?, ?)",
                [
                    ("JHN", "John", 3, 16, "WEB verse sixteen."),
                    ("JHN", "John", 3, 17, "WEB verse seventeen."),
                ],
            )

    @patch("bible_service.internet_access_allowed", return_value=True)
    def test_online_niv_passage(self, _allowed):
        session = Mock()
        list_response = Mock()
        list_response.raise_for_status.return_value = None
        list_response.json.return_value = {
            "data": [
                {"id": "niv-id", "abbreviation": "NIV", "name": "NIV"}
            ]
        }
        passage_response = Mock()
        passage_response.raise_for_status.return_value = None
        passage_response.json.return_value = {
            "data": {
                "reference": "John 3:16",
                "content": (
                    '<p class="p"><span data-number="16" '
                    'data-sid="JHN 3:16" class="v">16</span>'
                    "NIV test text.</p>"
                ),
                "copyright": "NIV attribution",
            }
        }
        session.get.side_effect = [list_response, passage_response]
        service = BibleService(session=session, database_path=self.database)

        with patch.dict("os.environ", {"API_BIBLE_KEY": "secret"}):
            passage, error = service.get_passage(
                BibleReference("JHN", "John", 3, 16)
            )

        self.assertIsNone(error)
        self.assertTrue(passage.online)
        self.assertEqual(passage.translation_abbreviation, "NIV")
        self.assertEqual(passage.text, "NIV test text.")
        self.assertEqual(passage.verses, (("16", "NIV test text."),))
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"]["include-verse-numbers"],
            "true",
        )
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"]["include-verse-spans"],
            "true",
        )

    @patch("bible_service.internet_access_allowed", return_value=True)
    def test_network_failure_falls_back_to_web(self, _allowed):
        session = Mock()
        session.get.side_effect = requests.ConnectionError("offline")
        service = BibleService(session=session, database_path=self.database)

        with patch.dict("os.environ", {"API_BIBLE_KEY": "secret"}):
            passage, error = service.get_passage(
                BibleReference("JHN", "John", 3, 16, 17)
            )

        self.assertIsInstance(error, requests.ConnectionError)
        self.assertFalse(passage.online)
        self.assertEqual(
            passage.text,
            "WEB verse sixteen. WEB verse seventeen.",
        )

    @patch("bible_service.internet_access_allowed", return_value=False)
    def test_offline_mode_uses_web_without_network_request(self, _allowed):
        session = Mock()
        service = BibleService(session=session, database_path=self.database)

        passage, error = service.get_passage(
            BibleReference("JHN", "John", 3, 16)
        )

        self.assertFalse(passage.online)
        self.assertIn("offline test mode", str(error))
        session.get.assert_not_called()

    def test_missing_key_uses_web(self):
        service = BibleService(session=Mock(), database_path=self.database)
        with patch.dict("os.environ", {}, clear=True):
            passage, error = service.get_passage(
                BibleReference("JHN", "John", 3, 16)
            )
        self.assertFalse(passage.online)
        self.assertIsInstance(error, RuntimeError)

    def test_spoken_response_identifies_fallback_translation(self):
        service = Mock()
        service.get_passage.return_value = (
            BiblePassage(
                "John 3:16",
                "Fallback text.",
                "World English Bible",
                "WEB",
                False,
            ),
            requests.Timeout("offline"),
        )
        response = get_bible_response("read John 3:16", service=service)
        self.assertEqual(
            response,
            "John 3:16 from the World English Bible. Fallback text.",
        )
        self.assertEqual(
            response.tts_text,
            "John 3:16 from the World English Bible. [Pause] Fallback text.",
        )

    @patch(
        "bible_service._last_reference",
        BibleReference("1PE", "1 Peter", 1),
    )
    def test_bookless_follow_up_reuses_last_bible_book(self):
        service = Mock()
        service.get_passage.return_value = (
            BiblePassage(
                "1 Peter 2:1-10",
                "Passage text.",
                "World English Bible",
                "WEB",
                False,
            ),
            requests.Timeout("offline"),
        )

        response = get_bible_response(
            "can you repeat chapter 2 verses 1 through 10",
            service=service,
        )

        requested_reference = service.get_passage.call_args.args[0]
        self.assertEqual(
            requested_reference,
            BibleReference("1PE", "1 Peter", 2, 1, 10),
        )
        self.assertTrue(response.startswith("1 Peter 2:1-10"))


if __name__ == "__main__":
    unittest.main()
