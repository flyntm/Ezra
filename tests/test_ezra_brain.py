import os
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

import ezra_brain


class EzraBrainTests(unittest.TestCase):
    def setUp(self):
        ezra_brain.conversation_history = []

    def test_local_provider_uses_loopback_chat_api(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"emotion":"curious","response":"A servo moves a robot part."}'
                    }
                }
            ]
        }

        with patch.dict(os.environ, {"EZRA_AI_PROVIDER": "local"}), patch(
            "ezra_brain.requests.post", return_value=response
        ) as post:
            result = ezra_brain.ask_ezra("What does a servo do?")

        self.assertEqual(
            result,
            {"emotion": "curious", "response": "A servo moves a robot part."},
        )
        request = post.call_args
        self.assertEqual(
            request.args[0],
            "http://127.0.0.1:8081/v1/chat/completions",
        )
        self.assertTrue(
            request.kwargs["json"]["messages"][-1]["content"].endswith(
                "/no_think"
            )
        )

    def test_plain_text_response_gets_safe_defaults(self):
        result = ezra_brain._parse_brain_response("A short local answer.")

        self.assertEqual(
            result,
            {"emotion": "neutral", "response": "A short local answer."},
        )

    def test_markdown_wrapped_json_is_supported(self):
        result = ezra_brain._parse_brain_response(
            '```json\n{"emotion":"happy","response":"Hello!"}\n```'
        )

        self.assertEqual(result, {"emotion": "happy", "response": "Hello!"})

    def test_streaming_json_delivers_complete_sentences(self):
        deltas = (
            '{"emotion":"happy","res',
            'ponse":"First sentence. Sec',
            'ond sentence!"}',
        )

        class FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return iter(
                    SimpleNamespace(
                        type="response.output_text.delta",
                        delta=delta,
                    )
                    for delta in deltas
                )

        client = Mock()
        client.responses.stream.return_value = FakeStream()
        spoken = []
        with patch(
            "ezra_brain.internet_access_allowed", return_value=True
        ), patch("ezra_brain._get_openai_client", return_value=client):
            result = ezra_brain.ask_ezra(
                "Test streaming",
                on_sentence=lambda sentence: spoken.append(sentence) or False,
            )

        self.assertEqual(spoken, ["First sentence.", "Second sentence!"])
        self.assertEqual(result["response"], "First sentence. Second sentence!")
        self.assertEqual(result["emotion"], "happy")
        self.assertTrue(result["streamed"])

    def test_streaming_json_decodes_escaped_text(self):
        extractor = ezra_brain._StreamingResponseText()
        decoded = extractor.feed(
            '{"emotion":"neutral","response":"He said \\"hello\\". Line\\n2."}'
        )
        self.assertEqual(decoded, 'He said "hello". Line\n2.')

    def test_streaming_batches_first_sentence_then_remainder(self):
        events = [
            SimpleNamespace(
                type="response.output_text.delta",
                delta=(
                    '{"emotion":"neutral","response":"First. Second. Third."}'
                ),
            )
        ]

        class FakeStream:
            def __enter__(self):
                return iter(events)

            def __exit__(self, *_args):
                return False

        client = Mock()
        client.responses.stream.return_value = FakeStream()
        spoken = []
        with patch(
            "ezra_brain.internet_access_allowed", return_value=True
        ), patch("ezra_brain._get_openai_client", return_value=client):
            ezra_brain.ask_ezra(
                "Test batching",
                on_sentence=lambda text: spoken.append(text) or False,
            )

        self.assertEqual(spoken, ["First.", "Second. Third."])

    def test_invalid_provider_is_rejected(self):
        with patch.dict(os.environ, {"EZRA_AI_PROVIDER": "unknown"}):
            with self.assertRaisesRegex(ValueError, "Unsupported AI provider"):
                ezra_brain.ask_ezra("Hello")

    @patch("ezra_brain.internet_access_allowed", return_value=False)
    def test_offline_mode_uses_local_ai_instead_of_openai(self, _allowed):
        with patch.dict(os.environ, {"EZRA_AI_PROVIDER": "openai"}), patch(
            "ezra_brain._get_openai_client"
        ) as get_client, patch(
            "ezra_brain._ask_local",
            return_value='{"emotion":"happy","response":"Hello from the Pi."}',
        ) as ask_local:
            result = ezra_brain.ask_ezra("Hello")

        get_client.assert_not_called()
        ask_local.assert_called_once()
        self.assertEqual(result["response"], "Hello from the Pi.")

    @patch("ezra_brain.internet_access_allowed", return_value=False)
    def test_offline_mode_reports_unavailable_when_local_ai_is_down(self, _allowed):
        with patch.dict(os.environ, {"EZRA_AI_PROVIDER": "openai"}), patch(
            "ezra_brain._ask_local",
            side_effect=ezra_brain.requests.ConnectionError("local server down"),
        ):
            with self.assertRaisesRegex(
                ezra_brain.InternetUnavailableError,
                "local AI",
            ):
                ezra_brain.ask_ezra("Hello")


if __name__ == "__main__":
    unittest.main()
