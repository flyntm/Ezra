import unittest
from unittest.mock import patch

from live_info import get_live_info_response


class LiveInfoOfflineTests(unittest.TestCase):
    @patch("live_info.internet_access_allowed", return_value=False)
    @patch("live_info.get_weather_summary")
    def test_offline_mode_returns_message_without_web_lookup(
        self, weather_summary, _allowed
    ):
        response = get_live_info_response("what is the weather today")

        self.assertEqual(
            response,
            "Sorry, I'm not connected to the internet, so I can't answer that.",
        )
        weather_summary.assert_not_called()

    @patch("live_info.internet_access_allowed", return_value=False)
    def test_non_live_query_is_not_claimed_in_offline_mode(self, _allowed):
        self.assertIsNone(get_live_info_response("tell me a joke"))


if __name__ == "__main__":
    unittest.main()
