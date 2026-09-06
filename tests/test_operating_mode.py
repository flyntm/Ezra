import unittest

import operating_mode


class OperatingModeTests(unittest.TestCase):
    def tearDown(self):
        operating_mode.set_mode(operating_mode.GENERAL)

    def test_defaults_to_general(self):
        operating_mode.set_mode(operating_mode.GENERAL)
        self.assertFalse(operating_mode.presentation_context_enabled())

    def test_recognizes_presentation_mode_command(self):
        self.assertEqual(
            operating_mode.requested_mode("switch to presentation mode"),
            operating_mode.PRESENTATION,
        )

    def test_recognizes_general_mode_command(self):
        self.assertEqual(
            operating_mode.requested_mode("return to general mode"),
            operating_mode.GENERAL,
        )

    def test_does_not_claim_an_unrelated_command(self):
        self.assertIsNone(operating_mode.requested_mode("start the presentation"))

    def test_recognizes_mode_status_question(self):
        self.assertTrue(operating_mode.status_requested("what mode are you in?"))
        self.assertTrue(operating_mode.status_requested("what's your current mode?"))
        self.assertFalse(operating_mode.status_requested("what time is it?"))


if __name__ == "__main__":
    unittest.main()
