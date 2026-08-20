import unittest
from unittest.mock import patch

import state
from network_status import check_internet_connection, internet_access_allowed


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class NetworkStatusTests(unittest.TestCase):
    @patch("network_status.OFFLINE_TEST_MODE", False)
    def test_success_sets_connected_flag(self):
        connection = FakeConnection()

        with patch("network_status.time.time", return_value=123.0):
            result = check_internet_connection(
                connector=lambda endpoint, timeout: connection
            )

        self.assertTrue(result)
        self.assertTrue(state.internet_connected)
        self.assertTrue(state.internet_status_known)
        self.assertEqual(state.internet_last_checked_at, 123.0)
        self.assertEqual(state.internet_last_error, "")
        self.assertTrue(connection.closed)
        self.assertTrue(internet_access_allowed())

    @patch("network_status.OFFLINE_TEST_MODE", False)
    def test_failure_sets_offline_flag(self):
        def fail(_endpoint, timeout):
            raise OSError(f"offline after {timeout} seconds")

        result = check_internet_connection(connector=fail)

        self.assertFalse(result)
        self.assertFalse(state.internet_connected)
        self.assertTrue(state.internet_status_known)
        self.assertIn("offline", state.internet_last_error)
        self.assertFalse(internet_access_allowed())

    @patch("network_status.OFFLINE_TEST_MODE", True)
    def test_offline_mode_skips_real_connectivity_probe(self):
        connector = unittest.mock.Mock()

        result = check_internet_connection(connector=connector)

        self.assertFalse(result)
        self.assertFalse(internet_access_allowed())
        self.assertEqual(state.internet_last_error, "offline test mode enabled")
        connector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
