# Ezra software review — September 7, 2026

**Repair update:** the five software batches are implemented. See [repair results and remaining Pi checks](REPAIRS.md). Findings and probe results below describe the pre-repair revision.

Reviewed revision: `b5847b83075929f3782eccc2a30b518278e61409`.

The review found **13 actionable issues: 3 high priority and 10 medium priority**. The strongest theme is missing coordination between otherwise functional components: microphone capture and narration, normalization and command parsing, and normal shutdown and restart recovery.

This deliverable contains findings and reproducible evidence. Production code, configuration, service installation, and presentation materials were not changed during this review. The earlier sleep-order fix is already in the reviewed revision.

## Evidence and scope

- The configured Python 3.11 environment passes **all 166 existing tests**. The initial system-Python run could not import four test modules because `openai` and `usb` were unavailable there; these were environment errors, not failures in the configured runtime.
- **12 additional offline probes** reproduce the observed defects or isolate the relevant control-flow behavior. R12 is established by the command exit path and the checked-in service policy, without stopping or restarting a service.
- `ezra311-env/bin/python -m pip check`: **No broken requirements found.** This checks installed dependency consistency, not security vulnerabilities or reproducibility on another Pi.
- All **48 first-party Python files** across the project root, `robot`, `presentations`, and `tools` parse successfully (12,606 lines before review artifacts).
- Reviewed the active interaction, capture, transcription, AI, speech, animation, calibration, presentation, Bible, live-information, network, lifecycle, and recovery paths; the associated tests; configuration; and installation/backup helpers. Diagnostic tooling was inspected where it supports those paths.
- Third-party packages, trained model internals, archived implementations, and training experiments were not exhaustively audited. The installed OpenWakeWord implementation was inspected specifically to establish its streaming-input contract.
- No live API requests, microphone capture, playback, servo motion, browser launch, poweroff, or service restart were performed. Device-level effects and acoustic false-wake rates still require Pi validation.

Run the original suite:

```bash
ezra311-env/bin/python -m unittest discover -s tests
```

Run the review evidence:

```bash
ezra311-env/bin/python reviews/2026-09-07/reproduce_findings.py
```

**The review probes assert the current defective behavior. Passing means the finding was reproduced, not that the behavior is correct.** They are deliberately outside the normal test suite. Each repair should add acceptance tests that assert the desired behavior.

Logs: [existing suite](baseline-tests.log), [review probes](reproduction-results.log).

## Findings

### R01 — High: ordinary questions can shut down or exit Ezra

Locations: [command.py:141](/home/flyntm/projects/ezra/command.py:141), [command.py:213](/home/flyntm/projects/ezra/command.py:213).

The quit and poweroff classifiers search for keywords anywhere in the sentence. `How do I quit smoking?` is classified as an application-exit request. `Explain a government shutdown` and `Do not shut down` are classified as poweroff requests. The local-command dispatcher executes these classifications before general AI processing.

**Evidence:** `test_r01` reproduces all three classifications without executing an exit or poweroff.

**Repair:** accept explicit command forms, including the supported polite forms, while rejecting questions, quoted discussion, and negated requests. Add tests through normalization and the local dispatcher, with poweroff mocked. No routine confirmation dialogue is needed for an unambiguous supported command.

### R02 — High: wake detection repeatedly processes overlapping, misordered audio

Locations: [wake_word.py:929](/home/flyntm/projects/ezra/wake_word.py:929), [wake_word.py:1005](/home/flyntm/projects/ezra/wake_word.py:1005).

Each inference converts the entire 16,000-sample circular buffer directly to model input. A fresh callback usually adds only 1,024 samples. Consequently most audio is replayed on successive calls, and after a wrap the underlying array places newer audio before older audio. Waiting for a fresh callback avoids completely identical inputs but does not fix overlap or chronological order.

The installed OpenWakeWord `Model.predict` appends incoming audio to its stateful preprocessor and processes it as new frames. Its implementation also takes the maximum prediction across a long input. Replaying the old window can therefore contaminate both its feature history and Ezra's repeated-hit qualification. The stop listener already uses successive fresh chunks, demonstrating the intended approach within this project.

**Evidence:** `test_r02` runs the real callback and inference-conversion statement with numbered samples. Successive 16,000-sample inputs share more than 14,000 values, and the wrapped input jumps backward in sample order. Installed dependency evidence: `ezra311-env/lib/python3.11/site-packages/openwakeword/model.py`, `predict`, particularly lines 273–303.

**Repair:** provide each fresh audio sample once, in order, using a queue or a synchronized reader position with overrun detection. Keep a separate history buffer for command handoff. Validate with recorded wake/non-wake clips before adjusting thresholds; the current thresholds were tuned against the faulty input path. Actual false-wake and missed-wake rates were not measured in this review.

### R03 — High: browser controls can narrate while the main loop is still listening

Locations: [presentations/browser_slideshow.py:277](/home/flyntm/projects/ezra/presentations/browser_slideshow.py:277), [presentations/lesson_presentation.py:256](/home/flyntm/projects/ezra/presentations/lesson_presentation.py:256), [main.py:314](/home/flyntm/projects/ezra/main.py:314), [tts.py:976](/home/flyntm/projects/ezra/tts.py:976).

After a slide finishes, the main thread returns to wake-word capture. A browser arrow key or Enter starts narration on another thread without handing off microphone ownership or notifying the main loop. The narration lock serializes slide narration only; ordinary answers and the main listener do not acquire it.

This permits wake capture during Ezra's own speech, competing microphone opens for the stop listener, and overlapping `speak()` calls. Overlapping speech also shares `temp.wav`, the stop model, facial state, and `state.tts_process`. Browser activity does not reset the main idle timer, so the sleep transition can occur during keyboard-driven narration.

**Evidence:** `test_r03` executes the real browser-control handler and session narration with a fake speaker, confirming it calls speech on the worker thread while a main-listener activity flag remains set. The lack of a handoff is established by tracing the main and TTS paths. ALSA conflicts and physical motion effects were not exercised.

**Repair:** route keyboard and voice actions through a shared interaction controller. Suspend and close wake capture before any narration, serialize speech sessions, and make activity/cancellation state visible to sleep and shutdown. A lock around the WAV writer alone is insufficient because it would leave microphone capture active.

### R04 — Medium: healthy long narration expires the five-minute watchdog deadline

Locations: [main.py:315](/home/flyntm/projects/ezra/main.py:315), [service_watchdog.py:67](/home/flyntm/projects/ezra/service_watchdog.py:67), [presentations/lesson_presentation.py:314](/home/flyntm/projects/ezra/presentations/lesson_presentation.py:314).

One fixed 300-second busy deadline covers the entire command, including generation, playback, and any automatically advancing slide narration. Progress through speech chunks or slides never refreshes it. A valid reading or automatic sequence lasting over five minutes is marked unhealthy even while speech is progressing. Under the checked-in service policy, heartbeats are then withheld and systemd can restart Ezra.

**Evidence:** `test_r04` advances a fake clock during two successful automatic narrations. At 320 seconds the real watchdog reports `command processing timed out`. No five-minute sleep or service restart is used. The current deck's individual notes are short; this finding applies to sufficiently long readings or automatic sequences, not every slide.

**Repair:** track bounded progress separately for capture, AI, synthesis, and playback. Renew an activity lease on verified progress while retaining a stall deadline; simply disabling the watchdog or resetting it from an unconditional timer would conceal hangs.

### R05 — Medium: losing connectivity after an online startup leaves offline AI unavailable

Locations: [main.py:259](/home/flyntm/projects/ezra/main.py:259), [ezra_brain.py:227](/home/flyntm/projects/ezra/ezra_brain.py:227), [ezra_brain.py:325](/home/flyntm/projects/ezra/ezra_brain.py:325).

Ezra starts the local model server only when the startup connectivity check says offline. If it starts online and later loses connectivity, the brain posts to the loopback server without ensuring it has started. With no independently running local server, the connection fails and Ezra says it cannot answer. Selecting the local provider while starting online has the same lifecycle gap.

**Evidence:** `test_r05` executes the online startup branch and an offline request with a simulated absent loopback server. No call starts the server, and the request raises `InternetUnavailableError`.

**Repair:** ensure local-server readiness on demand whenever the selected path needs local inference, including retries after a local process exit. Bound the startup wait and include it in watchdog phase handling.

### R06 — Medium: exception cleanup deletes the presentation state needed for recovery

Locations: [main.py:233](/home/flyntm/projects/ezra/main.py:233), [main.py:673](/home/flyntm/projects/ezra/main.py:673), [presentations/lesson_presentation.py:493](/home/flyntm/projects/ezra/presentations/lesson_presentation.py:493).

A main-loop exception enters the same cleanup path as an intentional exit. `shutdown_robot()` calls `stop_presentation()`, which calls `session.stop()` with `clear_recovery=True`. The saved slide is removed before the supervised process restarts. A transient follow-up microphone error is one path to this cleanup. Hard watchdog termination may preserve the file because it bypasses Python cleanup, so recovery behavior differs by failure mode.

**Evidence:** `test_r06` writes recovery state in a temporary directory and executes the real shutdown helper and session stop. The recovery record disappears.

**Repair:** distinguish deliberate presentation completion from process cleanup. Close the display while preserving its saved position on recoverable errors/restarts, and clear it only for an explicit presentation-end policy. Make individual shutdown steps independent so a display-close error does not prevent head and face cleanup.

### R07 — Medium: normalization destroys Scripture references before parsing

Locations: [command_normalization.py:57](/home/flyntm/projects/ezra/command_normalization.py:57), [main.py:439](/home/flyntm/projects/ezra/main.py:439).

`strip_wake_word()` deletes every punctuation character. `Ezra read John 3:16` becomes `read john 316`; the Bible parser then requests chapter 316. `John 3:16-18` becomes chapter 31618. The direct Bible-parser tests pass because they bypass this normalization stage.

**Evidence:** `test_r07` passes both examples through the real normalizer and reference parser and obtains the wrong chapter numbers.

**Repair:** preserve punctuation that encodes reference structure and numeric meaning. Separate wake-prefix removal from command-specific matching. Add end-to-end normalization/parser tests for colons, ranges, number words, and an ordinary question containing a reference.

### R08 — Medium: the deployed Lesson Four study material is never loaded

Locations: [lesson_context.py:74](/home/flyntm/projects/ezra/lesson_context.py:74), [lesson_context.py:115](/home/flyntm/projects/ezra/lesson_context.py:115), [acts-Lesson_Four.json](/home/flyntm/projects/ezra/presentations/acts-Lesson_Four.json).

Both discovery and cache invalidation consider only `*.jsonl`. The current Lesson Four material is 61 valid line-delimited JSON records stored as `acts-Lesson_Four.json`. It is silently excluded while Lessons One, Two, and Three are loaded. Presentation-mode answers therefore cannot draw on that current lesson file.

**Evidence:** `test_r08` parses all 61 records, verifies the real loader omits their source, and isolates the file in a temporary directory where the loader returns no chunks.

**Repair:** normalize the deployed filename or explicitly support and validate this input format. Add a preflight check that the current lesson's expected source is loaded. Speaker notes are intentionally excluded from answer retrieval by an existing test; that exclusion is not treated as a defect here.

### R09 — Medium: unrelated questions are diverted to weather

Location: [live_info.py:49](/home/flyntm/projects/ezra/live_info.py:49).

Weather classification uses substring membership. `brain` and `training` both contain `rain`, so questions such as `Explain how your brain works` and `What is training?` request current weather instead of reaching the brain. Broader intent distinctions also need care: merely mentioning rain is not necessarily a request for live local weather.

**Evidence:** `test_r09` passes those questions through `get_live_info_response()` with only the network response mocked. Both produce the weather response.

**Repair:** use word boundaries and explicit weather intent, with negative examples for ordinary vocabulary and explanatory questions. Apply the same intent review to news and volume classification.

### R10 — Medium: PowerPoint order and notes are inferred from filenames

Locations: [presentations/powerpoint.py:45](/home/flyntm/projects/ezra/presentations/powerpoint.py:45), [presentations/powerpoint.py:80](/home/flyntm/projects/ezra/presentations/powerpoint.py:80), [presentations/browser_slideshow.py:142](/home/flyntm/projects/ezra/presentations/browser_slideshow.py:142).

The deck loader and renderer sort `slideN.xml` numerically instead of following the presentation's slide relationships. Note lookup assumes `slideN.xml` belongs to `notesSlideN.xml`, ignoring each slide's note relationship. Editing/reordering a deck can preserve these part names while changing its logical order and note associations. Ezra can then show an old order or read the wrong note for a slide.

**Evidence:** `test_r10` builds a minimal package whose relationship order is slide 2 then slide 1 and whose note relationships differ from the filename convention. The renderer still displays slide 1 first; the loader continues to use matching numeric note filenames. The current Lesson Four deck's slide relationship order is numeric, so the reordering problem is latent in that deployed deck.

**Repair:** resolve the ordered slide relationships once, use that order for both narration and rendering, and resolve notes through each slide's relationship file. Cover reordered slides, missing notes, and nonmatching part numbers.

### R11 — Medium: a stalled Piper worker cannot observe a speech cancellation

Locations: [persistent_piper.py:57](/home/flyntm/projects/ezra/persistent_piper.py:57), [tts.py:1144](/home/flyntm/projects/ezra/tts.py:1144), [tts.py:1270](/home/flyntm/projects/ezra/tts.py:1270).

Persistent synthesis blocks on `stdout.readline()` without a timeout. The one-shot fallback also has no subprocess timeout. If Piper stays alive but stops producing output, cancellation from Escape or the stop phrase cannot release the synthesis wait. Waiting on a render future and `shutdown(wait=True)` can likewise block the caller. The fallback is reached only if the existing call returns or raises. A supervised main-thread hang eventually meets the watchdog; a manual run can remain stuck.

**Evidence:** `test_r11` gives the real worker a blocking fake stdout. A simulated speech-cancel event does not release the wait; only explicitly releasing the fake pipe does. No Piper process is launched.

**Repair:** give synthesis a deadline and cancellation mechanism that can terminate and reap a stalled worker. Ensure render executors, pipes, and temporary directories are cleaned in `finally` paths. Test a silent-but-live worker, a broken pipe, cancellation during render, and a successful subsequent utterance.

### R12 — Medium: “quit” restarts Ezra when run under the supplied service

Locations: [command.py:213](/home/flyntm/projects/ezra/command.py:213), [systemd/ezra.service:12](/home/flyntm/projects/ezra/systemd/ezra.service:12).

The voice quit path sets `state.shutting_down` and allows a normal process exit. The unit has `Restart=always` and `RestartSec=5`, so that exit causes Ezra to start again. The documented command promises to exit the application. An explicit `systemctl --user stop ezra` behaves differently because it stops the unit itself.

**Evidence:** direct trace of the quit branch, main cleanup, and the checked-in unit; no service action was executed. Applicability depends on running that service policy rather than a manual process.

**Repair:** distinguish intentional voice exit from application failure, using a deliberate unit-stop action or a dedicated exit status with a matching restart policy. Preserve automatic restart for unexpected failures.

### R13 — Medium: a streamed-playback failure can repeat an answer already spoken

Locations: [ezra_brain.py:215](/home/flyntm/projects/ezra/ezra_brain.py:215), [ezra_brain.py:315](/home/flyntm/projects/ezra/ezra_brain.py:315), [main.py:569](/home/flyntm/projects/ezra/main.py:569).

The streaming helper invokes the remainder's playback callback outside its stream-error handler. If that callback fails after the first sentence has been handed to speech—for example, a temporary-file error while preparing the remainder—the exception reaches `ask_ezra()`. Its blanket fallback asks the model again and returns a non-streamed response, which main speaks in full. The fallback comment says it is safe only before delivery, but that condition is not enforced for the later callback.

**Evidence:** `test_r13` delivers `First.`, raises a simulated file error for the remainder, and observes a fallback request returning `First. Second.` with no streamed flag.

**Repair:** separate generation errors from playback errors and explicitly record whether delivery has begun. Permit full-response fallback only before delivery; otherwise retain a partial result and cleanly finish/cancel the speech thread. Test both first-sentence and remainder failures.

## Repair sequence and acceptance checks

1. **Command and lesson correctness:** R01, R07, R08, R09. Small, isolated changes with full dispatch tests. Verify negative shutdown examples, supported explicit commands, Scripture ranges, and retrieval from Lesson Four.
2. **Wake input correctness:** R02. Add deterministic sample-order/once-only tests and recorded-audio evaluation. Compare quiet-room, music, near/far speaker, and consecutive wake trials before retaining or retuning thresholds.
3. **Interaction ownership and cancellation:** R03, R11, R13. Establish one owner for capture/playback and route browser controls through it. Exercise keyboard navigation during listening, speaking, sleep, and shutdown; cancel during synthesis and playback; verify no orphan thread, process, or reused speech file.
4. **Lifecycle and recovery:** R04, R05, R06, R12. Use fake-clock and fault-injection tests, then supervised Pi checks for a long reading, online-to-offline transition, microphone failure, restart restoration, and intentional quit.
5. **Deck compatibility:** R10. Add relationship-based fixtures and compare an edited/reordered copy against PowerPoint's displayed order and notes.

Each batch should remain independently reviewable, run its relevant tests and the existing suite, and identify any physical acceptance checks still outstanding.

## Maintenance observations

- The repository tracks **9,950 virtual-environment files**. `.gitignore` excludes `ezra-env/`, while the actual environment is `ezra311-env/`. This increases backup/review noise and couples the tree to a local Python installation. Treat cleanup as a separate change that preserves a working recovery path; do not remove the active environment while repairing runtime bugs.
- Several key modules open hardware or load models at import time. Existing tests work around that by extracting functions with AST. This is useful for safe testing, but it helped leave integration gaps such as normalization versus Bible parsing and browser versus main-loop ownership. Introduce explicit startup boundaries as those areas are repaired.
- Installed-package consistency passes, but the runtime also depends on native Piper, llama.cpp/model assets, the ReSpeaker SDK, desktop audio/display tools, and paths outside this repository. A reproducible setup inventory and restoration exercise would improve maintainability. This review did not assess what the user's separate backup contains.
- Some configuration values and comments describe older paths. Remove obsolete settings only after mapping active consumers; avoid changing calibrated timing or servo limits as general cleanup.

## Sleep behavior follow-up

The reviewed `enter_sleep()` stops face animation before centering the head/eyes and closing the lids. The existing four sleep tests pass. This supports the corrected ordering but does not establish why the observed robot failed to face front. R03 exposes another route by which sleep and active narration can overlap. After that coordination repair, physically check sleep from both left and right head positions, after voice narration, and after keyboard narration, followed by a wake-up.
