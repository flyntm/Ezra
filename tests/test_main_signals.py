import signal
import unittest
from unittest.mock import patch

import service_runtime
import state


class ShutdownSignalTests(unittest.TestCase):
    def tearDown(self):
        state.shutting_down = False

    def test_sigterm_requests_normal_shutdown(self):
        state.shutting_down = False

        with self.assertRaises(KeyboardInterrupt):
            service_runtime.handle_shutdown_signal(signal.SIGTERM, None)

        self.assertTrue(state.shutting_down)

    @patch("service_runtime.signal.signal")
    def test_installs_sigterm_handler(self, register):
        service_runtime.install_shutdown_signal_handlers()

        register.assert_called_once_with(
            signal.SIGTERM,
            service_runtime.handle_shutdown_signal,
        )


if __name__ == "__main__":
    unittest.main()
