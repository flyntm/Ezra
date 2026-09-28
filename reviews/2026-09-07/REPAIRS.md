# Repair sequence results

All five software repair batches from the review are implemented in the working tree. The 13 findings have corresponding code changes. Live robot acceptance remains pending; this is not a claim that physical behavior or wake accuracy has been measured.

## Changes

| Batch | Findings | Result |
| --- | --- | --- |
| Command and lesson correctness | R01, R07, R08, R09 | Quit/poweroff require complete explicit requests. Numeric reference punctuation survives wake-prefix removal. Lesson Four's line-delimited `.json` export is loaded and participates in cache invalidation. Weather matching rejects incidental substrings and explanatory questions. |
| Wake input | R02 | The model consumes fresh queued samples once, in order. A bounded queue signals overruns and resets invalid feature/hit history. Command handoff still uses its separate history buffer. Existing sensitivity and timing settings were retained. |
| Interaction and cancellation | R03, R11, R13 | Browser controls queue work for main; capture closes before narration. Rapid navigation reads only its final destination. Speech calls are serialized. Synthesis observes cancellation and deadlines; stopped workers are reaped and can restart. Render cleanup runs on failures. A streamed-delivery error cannot trigger a repeated full answer. |
| Lifecycle and recovery | R04, R05, R06, R12 | Observed playback/slide progress renews the busy watchdog deadline while stalls still expire it. Local AI starts on demand. Error/service cleanup preserves the slide checkpoint and continues if one cleanup step fails. Voice quit returns status 90, excluded from restart by the updated service unit. |
| PowerPoint compatibility | R10 | Both display and narration follow the presentation's ordered slide relationships. Notes follow their own relationships, independent of numeric filenames. |

The software also wakes a sleeping face before processing keyboard narration, cancels active speech during shutdown, and releases stop-listener retry waits when speech ends.

## Validation completed

- **193 tests pass** in `ezra311-env/bin/python`, including 27 new tests beyond the review baseline. [Full test log](repair-tests.log).
- Tests execute the real wake-loop cleanup with fake devices and verify the stream closes before queued narration starts.
- Real subprocess tests simulate a stalled Piper worker, cancellation, timeout, and a successful subsequent request. They use a small fake synthesizer, without robot hardware.
- Speech orchestration tests cover concurrent callers, cancellation during generation, and executor/temporary-directory cleanup after a render failure.
- Other regression tests cover normalized command dispatch, Scripture references, current lesson loading, watchdog progress versus stalls, recovery during a display-close error, offline server startup, streamed-playback failure, and edited PowerPoint relationships.
- **Native Piper synthesis succeeded twice** with the installed voice model and the same persistent worker. Both outputs were valid mono, 22,050 Hz WAVs (52,770 and 77,602 frames). The temporary recordings were removed; there was no audio playback.
- Python syntax checks and `git diff --check` passed.
- `systemd-analyze --user verify systemd/ezra.service` passed. Validation required running outside the sandbox because its local-socket operation was restricted; it did not install or restart the unit.

The original [review](REVIEW.md), baseline log, and defect-reproduction script describe the pre-repair revision. The old probes intentionally assert the former defects and are **not** acceptance tests for the repaired tree. Use the normal test suite for current validation:

```bash
ezra311-env/bin/python -m unittest discover -s tests
```

## Activation and Pi checks still needed

The application and installed service have not been restarted during this repair. Python changes take effect on restart. The updated quit behavior also requires copying the revised service unit into the user's installed units; merely restarting an older unit does not update its policy.

From the project directory on the Pi, these commands apply the unit update and restart Ezra:

```bash
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 systemd/ezra.service "$HOME/.config/systemd/user/ezra.service"
systemctl --user daemon-reload
systemctl --user restart ezra
```

These activation commands are documented here and were **not executed** as part of the tests.

1. Repeat wake phrases and non-wake speech from front/left/right, both quietly and with background sound. Confirm wake reliability before any sensitivity retuning; the model now receives a different, correct audio timeline.
2. While Ezra waits for a wake word, use Right Arrow and Enter. Confirm only slide narration starts, he does not answer himself, and “Ezra stop” still works. Try rapid arrows and Space/Escape during generation and playback.
3. Let Ezra sleep after left/right head turns, after voice narration, and after keyboard narration. Confirm the head faces front, lids stay closed, and both voice wake and keyboard narration wake him correctly.
4. Start online, disconnect networking, and ask a general question. Confirm local-model startup and an offline answer. Reconnect and verify normal cloud answers resume.
5. Exercise a reading or automatic sequence longer than five minutes. Confirm ongoing speech does not cause a watchdog restart. Verify a controlled service restart restores the current slide.
6. With the updated unit installed, say “quit.” Confirm Ezra stays stopped, then start him with `systemctl --user start ezra`.

No servo calibration, wake thresholds, voice model, trained model files, or presentation content was changed. The working tree has not been committed or pushed.
