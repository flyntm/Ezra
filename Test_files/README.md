# Ezra test and development utilities

This directory contains standalone programs used to test, calibrate, benchmark,
train, or diagnose parts of Ezra. These programs are not required when running
the Ezra application normally with `main.py`.

- `benchmarks/` contains performance comparison programs.
- `diagnostics/` contains ReSpeaker and enclosure test programs.
- `training/` contains the wake-word audio recording utility. Its recordings
  remain in the project-level `training/` directory.
- `wake_tests/` contains experimental wake-word listeners.
- The remaining programs are standalone microphone, audio, head-tracking, and
  mouth-display tests.

The project-level `tests/` directory is intentionally separate. It contains the
automated regression suite used to verify the Ezra application after changes.
