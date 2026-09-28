"""Tests for targeted ReSpeaker USB recovery."""

from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import unittest

import numpy as np

import respeaker_io


class ReSpeakerRecoveryTests(unittest.TestCase):
    def setUp(self):
        respeaker_io._last_reset_at = float("-inf")

    def test_reset_runs_only_the_installed_targeted_helper(self):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch("respeaker_io.subprocess.run", return_value=completed) as run,
            patch("respeaker_io.time.sleep") as sleep,
        ):
            self.assertTrue(respeaker_io.reset_respeaker_usb())

        run.assert_called_once_with(
            ("sudo", "-n", "/usr/local/sbin/ezra-reset-respeaker"),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        sleep.assert_called_once_with(3)

    def test_missing_device_is_retried_after_recovery(self):
        device = object()
        respeaker = object()
        fake_xvf_host = SimpleNamespace(ReSpeaker=Mock(return_value=respeaker))
        with (
            patch.dict(sys.modules, {"xvf_host": fake_xvf_host}),
            patch("respeaker_io.usb.core.find", side_effect=(None, device)),
            patch("respeaker_io.reset_respeaker_usb", return_value=True) as reset,
        ):
            result = respeaker_io.create_respeaker_or_raise(recover=True)

        self.assertIs(result, respeaker)
        reset.assert_called_once_with()
        fake_xvf_host.ReSpeaker.assert_called_once_with(device)

    def test_reset_is_rate_limited(self):
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch("respeaker_io.subprocess.run", return_value=completed) as run,
            patch("respeaker_io.time.sleep"),
            patch("respeaker_io.time.monotonic", side_effect=(100.0, 110.0)),
        ):
            self.assertTrue(respeaker_io.reset_respeaker_usb())
            self.assertFalse(respeaker_io.reset_respeaker_usb())

        run.assert_called_once()

    def test_model_calibrated_channel_is_selected_from_native_stereo(self):
        stereo = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)

        selected = respeaker_io.select_respeaker_recognition_channel(stereo)

        np.testing.assert_array_equal(
            selected,
            np.array([[1.0], [3.0]], dtype=np.float32),
        )

    def test_listening_led_uses_direction_of_arrival_effect(self):
        mic = Mock()

        respeaker_io.set_respeaker_listening_led(mic, True)

        mic.write.assert_called_once_with("LED_EFFECT", [4])

    def test_listening_led_turns_ring_off_when_disabled(self):
        mic = Mock()

        respeaker_io.set_respeaker_listening_led(mic, False)

        mic.write.assert_called_once_with("LED_EFFECT", [0])

    def test_wake_indicator_lights_three_blue_leds_at_front(self):
        mic = Mock()

        respeaker_io.set_respeaker_wake_indicator(mic, 0.0)

        ring_colors = mic.write.call_args_list[0].args[1]
        self.assertEqual(ring_colors.count(0x0000FF), 3)
        self.assertEqual(ring_colors.count(0), 9)
        self.assertEqual(ring_colors[0], 0x0000FF)
        self.assertEqual(ring_colors[1], 0x0000FF)
        self.assertEqual(ring_colors[-1], 0x0000FF)
        mic.write.assert_has_calls(
            [
                unittest.mock.call("LED_RING_COLOR", ring_colors),
                unittest.mock.call("LED_EFFECT", [5]),
            ]
        )

    def test_wake_indicator_wraps_at_ring_boundary(self):
        mic = Mock()

        respeaker_io.set_respeaker_wake_indicator(mic, -30.0)

        ring_colors = mic.write.call_args_list[0].args[1]
        self.assertEqual(ring_colors[11], 0x0000FF)
        self.assertEqual(ring_colors[10], 0x0000FF)
        self.assertEqual(ring_colors[0], 0x0000FF)


if __name__ == "__main__":
    unittest.main()
