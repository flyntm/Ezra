import unittest
from unittest.mock import patch

from service_watchdog import ServiceWatchdog


class ServiceWatchdogTests(unittest.TestCase):
    def watchdog(self, now=100.0):
        with patch.dict(
            "service_watchdog.os.environ",
            {"NOTIFY_SOCKET": "/run/test", "WATCHDOG_USEC": "30000000"},
            clear=True,
        ):
            return ServiceWatchdog(clock=lambda: now)

    def test_idle_requires_recent_microphone_activity(self):
        current = [100.0]
        with patch.dict(
            "service_watchdog.os.environ",
            {"NOTIFY_SOCKET": "/run/test", "WATCHDOG_USEC": "30000000"},
            clear=True,
        ):
            watchdog = ServiceWatchdog(clock=lambda: current[0])
        watchdog.idle()
        current[0] = 111.0

        self.assertEqual(
            watchdog.healthy(),
            (False, "microphone callbacks stopped"),
        )

        watchdog.audio_activity()
        self.assertEqual(watchdog.healthy(), (True, "healthy"))

    def test_busy_phase_has_a_deadline(self):
        current = [100.0]
        with patch.dict(
            "service_watchdog.os.environ",
            {"NOTIFY_SOCKET": "/run/test", "WATCHDOG_USEC": "30000000"},
            clear=True,
        ):
            watchdog = ServiceWatchdog(clock=lambda: current[0])
        watchdog.busy(timeout_seconds=20)
        current[0] = 121.0

        self.assertEqual(
            watchdog.healthy(),
            (False, "command processing timed out"),
        )

    def test_registered_subsystem_can_withhold_heartbeat(self):
        watchdog = self.watchdog()
        watchdog.register_health_check("presentation display", lambda: False)

        self.assertEqual(
            watchdog.healthy(),
            (False, "presentation display failed"),
        )


if __name__ == "__main__":
    unittest.main()
