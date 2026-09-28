import threading
import unittest
from unittest.mock import patch

from bible_service import SpokenBibleResponse
from narration_script import expand_bible_readings


class NarrationScriptTests(unittest.TestCase):
    @patch('narration_script.get_bible_response')
    def test_range_forms_and_single_verse(self, lookup):
        lookup.return_value = SpokenBibleResponse('Display', tts_text='Acts. [Pause] Passage.')
        for marker, reference in (
            ('[Read Acts 3:1-20]', 'Acts 3:1-20'),
            ('[Read Acts 3:1:20.]', 'Acts 3:1-20'),
            ('[read Acts 3: 1 – 20]', 'Acts 3:1-20'),
            ('[Read John 3:16]', 'John 3:16'),
            ('[Read 1 Corinthians 13:4-7]', '1 Corinthians 13:4-7'),
        ):
            with self.subTest(marker=marker):
                result = expand_bible_readings(f'Before. {marker} After. [Smile]')
                self.assertEqual(result, 'Before.  Acts. [Pause] Passage.  After. [Smile]')
                lookup.assert_called_with(f'Read {reference}')

    @patch('narration_script.get_bible_response')
    def test_invalid_markers_never_request_partial_passages(self, lookup):
        for marker in ('[Read Acts 3:20-1]', '[Read Acts 0:1]',
                       '[Read Acts 3:0]', '[Read Unknown 3:1]', '[Read Acts 3:1-garbage]'):
            self.assertIn("couldn't read", expand_bible_readings(marker))
        lookup.assert_not_called()

    @patch('narration_script.get_bible_response')
    def test_multiple_readings_keep_order_and_cancel_remaining_lookups(self, lookup):
        stop = threading.Event()
        def respond(command):
            stop.set()
            return 'Passage.'
        lookup.side_effect = respond
        self.assertEqual(expand_bible_readings('[Read Acts 3:1] [Read John 3:16]', stop), ' ')
        lookup.assert_called_once_with('Read Acts 3:1')

    @patch('narration_script.get_bible_response', return_value=None)
    def test_disabled_reading_and_plain_text(self, lookup):
        self.assertIn('unavailable', expand_bible_readings('[Read John 3:16]'))
        self.assertEqual(expand_bible_readings('Hello. [Pause]'), 'Hello. [Pause]')

    @patch('narration_script.get_bible_response', side_effect=['First passage.', 'Second passage.'])
    def test_multiple_readings(self, lookup):
        self.assertEqual(expand_bible_readings('[Read Acts 3:1] Then [Read John 3:16]'),
                         ' First passage.  Then  Second passage. ')

    @patch('narration_script.get_bible_response', return_value='Exact passage.')
    def test_real_speech_receives_passage_in_script_order(self, lookup):
        from tests.test_tts_lifecycle import SpeechLifecycleTests

        harness = SpeechLifecycleTests()
        harness.setUp()
        harness.say('Before. [Read Acts 3:1:20.] After.')
        spoken = ' '.join(call.args[0] for call in harness.ns['generate_speech_file'].call_args_list)
        self.assertIn('Before.', spoken)
        self.assertIn('Exact passage.', spoken)
        self.assertIn('After.', spoken)
        self.assertLess(spoken.index('Before.'), spoken.index('Exact passage.'))
        self.assertLess(spoken.index('Exact passage.'), spoken.index('After.'))
        self.assertNotIn('[Read', spoken)


class NarrationDisplayTests(unittest.TestCase):
    def run_reading(self, interrupt=False, fail=False):
        from tests.test_tts_lifecycle import SpeechLifecycleTests
        from unittest.mock import Mock

        harness = SpeechLifecycleTests()
        harness.setUp()
        events = []
        display = Mock()
        display.start.side_effect = lambda: events.append('show')
        display.begin_reading.side_effect = lambda: events.append('begin')
        display.close.side_effect = lambda: events.append('close')
        current = []
        def generate(text, **kwargs):
            current[:] = [text]
            return True
        def playback(stop, *args):
            events.append(current[0])
            if 'Exact passage' in current[0]:
                if fail:
                    raise OSError('audio failed')
                if interrupt:
                    stop.set()
            return False
        harness.ns['generate_speech_file'].side_effect = generate
        harness.ns['_play_speech_file'].side_effect = playback
        harness.ns['speak'] = Mock()  # Stop confirmation only.
        response = SpokenBibleResponse('Acts 3:1 from the NIV. Exact passage.',
                                       verses=((1, 'Exact passage.'),))
        with patch('narration_script.get_bible_response', return_value=response), \
                patch('bible_display.BibleDisplay', return_value=display) as factory, \
                patch('config.ENABLE_BIBLE_DISPLAY', True):
            if fail:
                with self.assertRaises(OSError):
                    harness.say('Before. [Read Acts 3:1] After.')
            else:
                harness.say('Before. [Read Acts 3:1] After.')
        factory.assert_called_once_with('Acts 3:1 from the NIV', 'Exact passage.',
                                        ((1, 'Exact passage.'),))
        display.close.assert_called_once()
        self.assertLess(events.index('Before.'), events.index('show'))
        self.assertLess(events.index('show'), events.index('begin'))
        passage = next(i for i, value in enumerate(events) if 'Exact passage' in value)
        self.assertLess(events.index('begin'), passage)
        self.assertLess(passage, events.index('close'))
        if interrupt or fail:
            self.assertNotIn('After.', events)
        else:
            self.assertLess(events.index('close'), events.index('After.'))
        self.assertFalse(any('[Bible' in event for event in events))

    def test_shows_passage_only_during_reading_then_restores_slide(self):
        self.run_reading()

    def test_interruption_closes_passage_without_remaining_narration(self):
        self.run_reading(interrupt=True)

    def test_playback_failure_closes_passage(self):
        self.run_reading(fail=True)

    @patch('config.ENABLE_BIBLE_DISPLAY', True)
    def test_browser_failure_cleans_up_and_allows_audio(self):
        from narration_script import ScriptBibleDisplay
        with patch('bible_display.BibleDisplay') as factory:
            factory.return_value.start.side_effect = RuntimeError('no browser')
            controller = ScriptBibleDisplay([('Title', 'Text', ())])
            controller.open(0)
            controller.begin_reading()
            controller.close()
            factory.return_value.close.assert_called_once()
            self.assertIsNone(controller.display)


if __name__ == '__main__':
    unittest.main()
