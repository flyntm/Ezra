import io
import unittest
from unittest.mock import patch

from command_timing import CommandTiming


class CommandTimingTests(unittest.TestCase):
    def test_report_lists_pipeline_stages_and_total(self):
        timing = CommandTiming(10.0)
        timing.mark("command_capture_finished", 12.0)
        timing.mark("stt_started", 12.0)
        timing.mark("stt_finished", 12.5)
        timing.mark("command_ready", 12.6)
        timing.mark("processing_started", 12.6)
        timing.mark("processing_finished", 13.0)
        timing.speech_requested_at = 13.0
        timing.speech_started_at = 13.2
        timing.speech_finished_at = 14.5
        timing.mark("response_finished", 14.6)

        output = io.StringIO()
        with patch("sys.stdout", output):
            timing.report()

        report = output.getvalue()
        self.assertIn("Wake detected → command capture complete: 2.000s", report)
        self.assertIn("Speech-to-text: 0.500s", report)
        self.assertIn("Speech synthesis/preparation: 0.200s", report)
        self.assertIn("Wake detected → response complete: 4.600s", report)

    def test_unavailable_stages_are_reported_as_na(self):
        timing = CommandTiming(10.0)
        timing.mark("response_finished", 11.0)
        output = io.StringIO()
        with patch("sys.stdout", output):
            timing.report("silent")
        self.assertIn("Speech playback: n/a", output.getvalue())


if __name__ == "__main__":
    unittest.main()
