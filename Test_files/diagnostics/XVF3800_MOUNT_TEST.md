# XVF3800 mount and cover test

This guided test records a consistent six-condition session from the ReSpeaker
XVF3800 and samples its direction-of-arrival, speech flag, and beam energy.
For servo trials it automatically cycles Ezra's calibrated eye, eyelid, and
head servos, then restores their neutral pose. Stop the normal Ezra program
before running this test so two processes do not control the PCA9685 at once.

Place the phone at the marked distance and use one unchanged playback file and
volume for every configuration. Define 0 degrees as the installed microphone's
forward direction and 90 degrees as its right side. Do not move the robot or test
surface during a session.

Run from the Ezra project directory:

```bash
python Test_files/diagnostics/xvf3800_mount_test.py uncovered_baseline --distance 1.0
python Test_files/diagnostics/xvf3800_mount_test.py foam_mount_v1 --distance 1.0
```

The program automatically tries the XVF3800's 16 kHz and 48 kHz USB modes,
preferring the 16 kHz mode used by Ezra. Use `--rate` only when deliberately
testing a particular firmware mode.

To identify the input-device name or number:

```bash
python Test_files/diagnostics/xvf3800_mount_test.py dummy --list-devices
```

Then pass a device number if the default `ReSpeaker` name does not match:

```bash
python Test_files/diagnostics/xvf3800_mount_test.py uncovered_baseline --device 2
```

Use `--trial quiet` (or another displayed trial name) to repeat just one test.
Each session is stored under `artifacts/xvf3800_tests/` with WAV recordings,
raw control samples, `session.json`, and a spreadsheet-friendly `summary.csv`.
The program also refreshes `artifacts/xvf3800_tests/all_results.csv`, combining
every saved configuration and trial into one table. It uses a UTF-8 Excel-friendly
encoding and has separate columns for each XVF3800 beam-energy value.

At the end of a run whose configuration name has already been used, the program
asks whether to overwrite its earlier session, discard the new run, or keep both.
Keeping both is the default and adds the next suffix, for example `foam_mount_2`.

The first two USB recording channels are captured as supplied by the board's
current firmware routing. Record the routing configuration in your test notes
if you change it between sessions.
