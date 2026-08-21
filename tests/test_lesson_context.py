import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import ezra_brain
from lesson_context import ContextChunk, augment_question, retrieve_context


class LessonContextTests(unittest.TestCase):
    def setUp(self):
        import lesson_context

        lesson_context._material_cache = None
        lesson_context._material_signature = None
        lesson_context._pending_context = []
        lesson_context._pending_question = None
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_reads_every_jsonl_file_and_labels_it_study_book(self):
        for name, text in (("one.jsonl", "Matthias became an apostle."),
                           ("two.jsonl", "Prayer guided the believers.")):
            (self.directory / name).write_text(
                json.dumps({"text": text, "metadata": {"title": name}}) + "\n",
                encoding="utf-8",
            )

        chunks = retrieve_context(
            "How did prayer guide the believers?",
            directory=self.directory,
            database_path=self.directory / "missing.sqlite3",
        )

        self.assertEqual(chunks[0].source, "study book")
        self.assertIn("Prayer guided", chunks[0].text)

    def test_explicit_bible_reference_retrieves_scripture(self):
        database = self.directory / "bible.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE verses (book_id TEXT, book_name TEXT, "
                "chapter INTEGER, verse INTEGER, text TEXT)"
            )
            connection.execute(
                "INSERT INTO verses VALUES ('ACT', 'Acts', 1, 8, "
                "'You will receive power and be my witnesses.')"
            )

        chunks = retrieve_context(
            "What does Acts 1:8 say?",
            directory=self.directory,
            database_path=database,
        )

        self.assertEqual(chunks[0].source, "Scripture")
        self.assertEqual(chunks[0].label, "Acts 1:8")

    def test_powerpoint_files_are_not_answer_sources(self):
        (self.directory / "lesson.pptx").write_bytes(
            b"distinctive speaker note answer"
        )

        chunks = retrieve_context(
            "What is the distinctive speaker note answer?",
            directory=self.directory,
            database_path=self.directory / "missing.sqlite3",
        )

        self.assertEqual(chunks, [])

    def test_augmented_prompt_requires_source_identification(self):
        with patch(
            "lesson_context.retrieve_context",
            return_value=[ContextChunk("study book", "Lesson", "A note.")],
        ):
            prompt = augment_question("What is this?")

        self.assertIn("study book or Scripture", prompt)
        self.assertIn("your own explanation", prompt)
        self.assertIn("[Source: study book; Lesson]", prompt)

    def test_first_answer_uses_top_result_and_saves_the_rest(self):
        chunks = [
            ContextChunk("study book", "Best", "Most relevant."),
            ContextChunk("Scripture", "Acts 1:8", "Additional detail."),
        ]
        with patch("lesson_context.retrieve_context", return_value=chunks):
            prompt = augment_question("Why?")

        self.assertIn("Most relevant.", prompt)
        self.assertNotIn("Additional detail.", prompt)
        self.assertIn('"There is more."', prompt)

    def test_tell_us_more_continues_original_question(self):
        import lesson_context

        lesson_context._pending_question = "Why was Matthias selected?"
        lesson_context._pending_context = [
            ContextChunk("Scripture", "Acts 1:24", "The next reason.")
        ]

        prompt = augment_question("Ezra, tell us more")

        self.assertIn("Why was Matthias selected?", prompt)
        self.assertIn("The next reason.", prompt)
        self.assertIn("Do not say there is more", prompt)
        self.assertEqual(lesson_context._pending_context, [])

    def test_own_explanation_request_bypasses_retrieval(self):
        with patch("lesson_context.retrieve_context") as retrieve:
            prompt = augment_question(
                "Give us your own broader explanation of spiritual gifts."
            )

        retrieve.assert_not_called()
        self.assertIn("broader, non-scriptural response", prompt)
        self.assertIn('begin naturally with "My own explanation is"', prompt)


class BrainRetrievalTests(unittest.TestCase):
    def setUp(self):
        ezra_brain.conversation_history = []

    def test_brain_uses_augmented_question_but_stores_original(self):
        with patch("ezra_brain.augment_question", return_value="QUESTION + SOURCES"), \
             patch.dict("os.environ", {"EZRA_AI_PROVIDER": "local"}), \
             patch(
                 "ezra_brain._ask_local",
                 return_value='{"emotion":"neutral","response":"Answer."}',
             ) as ask_local:
            ezra_brain.ask_ezra("QUESTION")

        self.assertEqual(ask_local.call_args.args[0][-1]["content"], "QUESTION + SOURCES")
        self.assertEqual(ezra_brain.conversation_history[0]["content"], "QUESTION")


if __name__ == "__main__":
    unittest.main()
