import unittest

from wake_noise import WakeNoiseFloor


class WakeNoiseTests(unittest.TestCase):
    def feed(self, tracker, start, level, count=50):
        for index in range(count):
            tracker.observe(start + index * 0.1, level)

    def test_steady_printer_above_old_minimum_is_below_required_level(self):
        tracker = WakeNoiseFloor(0.012)
        self.feed(tracker, 0, 0.025)
        self.assertGreater(tracker.required_rms(), 0.025)

    def test_spoken_rise_above_printer_is_accepted(self):
        tracker = WakeNoiseFloor(0.012)
        self.feed(tracker, 0, 0.025)
        self.feed(tracker, 5, 0.06, count=8)
        self.assertLess(tracker.required_rms(), 0.06)
        self.assertAlmostEqual(tracker.required_rms(), 0.0375)

    def test_quiet_room_and_startup_keep_existing_minimum(self):
        tracker = WakeNoiseFloor(0.012)
        self.assertEqual(tracker.required_rms(), 0.012)
        self.feed(tracker, 0, 0.002)
        self.assertEqual(tracker.required_rms(), 0.012)

    def test_noise_level_recovers_after_printer_stops(self):
        tracker = WakeNoiseFloor(0.012)
        self.feed(tracker, 0, 0.025)
        self.feed(tracker, 5, 0.002)
        self.assertEqual(tracker.required_rms(), 0.012)

    def test_old_noise_is_discarded_after_capture_gap(self):
        tracker = WakeNoiseFloor(0.012)
        self.feed(tracker, 0, 0.1)
        tracker.observe(30, 0.002)
        self.assertEqual(tracker.required_rms(), 0.012)
