#!/usr/bin/env python3
"""Guided, repeatable enclosure testing for the ReSpeaker XVF3800 on a Pi."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from respeaker_io import create_respeaker_or_raise


DEFAULT_DEVICE = "ReSpeaker"
DEFAULT_RATE = 16000
CONTROL_SAMPLE_SECONDS = 0.05


@dataclass(frozen=True)
class Trial:
    name: str
    kind: str
    angle: int | None
    servos: bool
    duration: float
    instructions: str


TRIALS = (
    Trial("quiet", "silence", None, False, 10, "Keep the room quiet; servos stationary."),
    Trial("servos", "silence", None, True, 15, "The eye, eyelid, and head servos will move automatically."),
    Trial("speech_0", "speech", 0, False, 12, "Phone at 0 degrees; servos stationary. Play the reference recording."),
    Trial("speech_90", "speech", 90, False, 12, "Phone at 90 degrees; servos stationary. Play the reference recording."),
    Trial("speech_0_servos", "speech", 0, True, 12, "Phone at 0 degrees. Play the recording while the servos move."),
    Trial("speech_90_servos", "speech", 90, True, 12, "Phone at 90 degrees. Play the recording while the servos move."),
)


class ServoMotion:
    """Run a repeatable, calibrated whole-face motion cycle."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def initialize(self) -> None:
        from robot import eyelids, eyes, servos
        from robot.head_tracking import head_tracker

        if not servos.init():
            raise RuntimeError("Could not initialize Ezra's PCA9685 servo controller")
        eyes.init()
        eyelids.init()
        eyes.center()
        eyelids.open_lids()
        head_tracker.center()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="XVF3800ServoNoiseTest",
            daemon=True,
        )
        self._thread.start()

    def _pause(self, seconds: float) -> bool:
        return self._stop.wait(seconds)

    def _run(self) -> None:
        from robot import eyelids, eyes
        from robot.head_tracking import head_tracker

        try:
            while not self._stop.is_set():
                head_tracker.turn_toward_bearing(20, source="servo test", announce=False)
                eyes.gaze_smooth(120, 70, steps=12, duration=0.18)
                eyelids.wide_open_lids()
                if self._pause(0.35):
                    break

                head_tracker.turn_toward_bearing(-40, source="servo test", announce=False)
                eyes.gaze_smooth(60, 110, steps=12, duration=0.18)
                eyelids.close_lids()
                if self._pause(0.25):
                    break

                eyelids.open_lids()
                eyes.gaze_smooth(90, 86, steps=12, duration=0.18)
                head_tracker.turn_toward_bearing(20, source="servo test", announce=False)
                if self._pause(0.35):
                    break
        finally:
            self.neutral()

    def neutral(self) -> None:
        from robot import eyelids, eyes
        from robot.head_tracking import head_tracker

        eyes.center()
        eyelids.open_lids()
        head_tracker.center()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self.neutral()


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return value.strip("._-") or "unnamed"


def existing_configuration_sessions(results_root: Path, configuration: str) -> list[Path]:
    matches = []
    for session_path in sorted(results_root.glob("*/session.json")):
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if session.get("metadata", {}).get("configuration") == configuration:
            matches.append(session_path.parent)
    return matches


def numbered_configuration_name(results_root: Path, configuration: str) -> str:
    used = set()
    for session_path in results_root.glob("*/session.json"):
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = session.get("metadata", {}).get("configuration")
        if isinstance(name, str):
            used.add(name)

    number = 2
    while f"{configuration}_{number}" in used:
        number += 1
    return f"{configuration}_{number}"


def finalize_duplicate_configuration(
    results_root: Path,
    output_dir: Path,
    configuration: str,
    existing: list[Path],
) -> Path | None:
    """Resolve a duplicate after capture; return final directory or None."""
    if not existing:
        write_all_results(results_root)
        return output_dir

    numbered = numbered_configuration_name(results_root, configuration)
    print(f"\nTest complete, but {configuration!r} already exists ({len(existing)} session(s)).")
    print(f"  [K] Keep both and name this test {numbered!r} (default)")
    print("  [O] Overwrite the previous test and its recordings")
    print("  [C] Cancel and discard this new test")
    try:
        choice = input("Choose K, O, or C: ").strip().lower()
    except EOFError:
        choice = "k"

    if choice in {"", "k", "keep", "n", "new"}:
        session_path = output_dir / "session.json"
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session["metadata"]["configuration"] = numbered
        session_path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
        timestamp = output_dir.name[:15]
        renamed_dir = output_dir.parent / f"{timestamp}_{safe_name(numbered)}"
        output_dir.rename(renamed_dir)
        write_all_results(results_root)
        return renamed_dir
    if choice in {"c", "cancel", "q", "quit"}:
        shutil.rmtree(output_dir)
        write_all_results(results_root)
        print("Discarded the new test; the previous test was not changed.")
        return None
    if choice not in {"o", "overwrite"}:
        print(f"Unrecognized choice; keeping both as {numbered!r}.")
        return finalize_duplicate_configuration(
            results_root, output_dir, configuration, existing
        )

    root = results_root.resolve()
    for session_dir in existing:
        target = session_dir.resolve()
        if target.parent != root or not (target / "session.json").is_file():
            raise RuntimeError(f"Refusing to remove unexpected session path: {target}")
        shutil.rmtree(target)
        print(f"Removed previous test session: {target.name}")
    write_all_results(results_root)
    return output_dir


def resolve_input_device(fragment: str | int) -> tuple[int, dict]:
    import sounddevice as sd

    devices = sd.query_devices()
    if isinstance(fragment, int) or str(fragment).isdigit():
        index = int(fragment)
        info = dict(devices[index])
        if info["max_input_channels"] < 1:
            raise RuntimeError(f"Audio device {index} has no input channels")
        return index, info

    matches = [
        (index, dict(info))
        for index, info in enumerate(devices)
        if str(fragment).lower() in info["name"].lower()
        and info["max_input_channels"] > 0
    ]
    if not matches:
        names = "\n".join(
            f"  {i}: {d['name']}" for i, d in enumerate(devices) if d["max_input_channels"]
        )
        raise RuntimeError(f"No input device contains {fragment!r}. Available inputs:\n{names}")
    if len(matches) > 1:
        print(f"Multiple devices match {fragment!r}; using {matches[0][0]}: {matches[0][1]['name']}")
    return matches[0]


def resolve_sample_rate(
    device_index: int,
    channels: int,
    requested_rate: int | None,
    device_info: dict,
) -> int:
    """Select a rate accepted by the board's currently loaded USB firmware."""
    import sounddevice as sd

    if requested_rate is not None:
        candidates = [requested_rate]
    else:
        candidates = [DEFAULT_RATE, 48000, round(float(device_info["default_samplerate"]))]

    errors = []
    for rate in dict.fromkeys(candidates):
        try:
            sd.check_input_settings(
                device=device_index,
                channels=channels,
                samplerate=rate,
            )
            return rate
        except sd.PortAudioError as exc:
            errors.append(f"{rate} Hz: {exc}")

    details = "; ".join(errors)
    if requested_rate is not None:
        hint = "Omit --rate to auto-detect the XVF3800 USB firmware rate."
    else:
        hint = "Check that the selected device is the ReSpeaker XVF3800."
    raise RuntimeError(f"No supported recording rate was found ({details}). {hint}")


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def audio_metrics(audio: np.ndarray) -> dict[str, float | int]:
    mono = np.mean(np.asarray(audio, dtype=np.float64), axis=1)
    absolute = np.abs(mono)
    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    peak = float(np.max(absolute)) if mono.size else 0.0
    return {
        "rms_dbfs": round(dbfs(rms), 2),
        "peak_dbfs": round(dbfs(peak), 2),
        "clipped_samples": int(np.count_nonzero(absolute >= 0.999)),
    }


def circular_mean_degrees(values: list[float]) -> float | None:
    if not values:
        return None
    radians = np.radians(values)
    return float(np.degrees(np.arctan2(np.sin(radians).mean(), np.cos(radians).mean())) % 360)


def summarize_control(samples: list[dict]) -> dict:
    speech_samples = [s for s in samples if s.get("speech")]
    angles = [float(s["doa_degrees"]) for s in speech_samples]
    result = {
        "control_samples": len(samples),
        "speech_fraction": round(len(speech_samples) / len(samples), 3) if samples else 0.0,
        "mean_doa_degrees": None,
        "mean_speech_energy": None,
    }
    mean_angle = circular_mean_degrees(angles)
    if mean_angle is not None:
        result["mean_doa_degrees"] = round(mean_angle, 1)
    energies = [s["speech_energy"] for s in samples if s.get("speech_energy")]
    if energies:
        width = max(len(row) for row in energies)
        result["mean_speech_energy"] = [
            round(float(np.mean([row[i] for row in energies if i < len(row)])), 2)
            for i in range(width)
        ]
    return result


def collect_control(mic, stop: threading.Event, samples: list[dict], started: float) -> None:
    while not stop.is_set():
        sample = {"seconds": round(time.monotonic() - started, 3)}
        try:
            doa = mic.read("DOA_VALUE")
            if len(doa) >= 2:
                sample.update(doa_degrees=float(doa[0]), speech=bool(doa[1]))
            energy = mic.read("AEC_SPENERGY_VALUES")
            sample["speech_energy"] = [float(value) for value in energy]
        except Exception as exc:
            sample["error"] = str(exc)
        samples.append(sample)
        stop.wait(CONTROL_SAMPLE_SECONDS)


def countdown() -> None:
    for number in (3, 2, 1):
        print(f"  Recording in {number}...", flush=True)
        time.sleep(1)


def record_audio_bounded(
    device_index: int,
    sample_rate: int,
    channels: int,
    duration: float,
) -> tuple[np.ndarray, bool]:
    """Record exactly one trial without relying on sd.wait() indefinitely."""

    import sounddevice as sd

    target_frames = round(duration * sample_rate)
    audio = np.empty((target_frames, channels), dtype=np.float32)
    written = 0
    finished = threading.Event()
    callback_error: list[BaseException] = []

    def callback(indata, frames, time_info, status):
        nonlocal written
        try:
            count = min(frames, target_frames - written)
            if count > 0:
                audio[written : written + count] = indata[:count]
                written += count
            if written >= target_frames:
                raise sd.CallbackStop
        except sd.CallbackStop:
            raise
        except BaseException as exc:
            callback_error.append(exc)
            raise sd.CallbackAbort

    stream = sd.InputStream(
        device=device_index,
        samplerate=sample_rate,
        channels=channels,
        dtype="float32",
        callback=callback,
        finished_callback=finished.set,
    )
    stream.start()
    deadline = time.monotonic() + duration + 2.0
    last_reported_second = -1
    stalled = False
    try:
        while not finished.wait(0.1):
            elapsed = duration - max(0.0, (target_frames - written) / sample_rate)
            elapsed_second = min(int(elapsed), int(duration))
            if elapsed_second != last_reported_second:
                print(
                    f"  Recording: {elapsed_second:g}/{duration:g} seconds",
                    flush=True,
                )
                last_reported_second = elapsed_second
            if time.monotonic() >= deadline:
                stalled = True
                print(
                    f"  ⚠️ Audio stream stalled after capturing "
                    f"{written / sample_rate:.1f} of {duration:g} seconds",
                    flush=True,
                )
                break
    finally:
        if stream.active:
            stream.abort()
        stream.close()

    if callback_error:
        raise RuntimeError(f"Audio callback failed: {callback_error[0]}")
    complete = not stalled and written == target_frames
    if complete:
        print(f"  Recording: {duration:g}/{duration:g} seconds", flush=True)
    elif not stalled:
        print(
            f"  ⚠️ Audio stream ended after {written / sample_rate:.1f} "
            f"of {duration:g} seconds",
            flush=True,
        )
    return audio[:written], complete


def record_trial(
    trial: Trial,
    output_dir: Path,
    device_index: int,
    sample_rate: int,
    channels: int,
    mic,
    servo_motion: ServoMotion,
) -> dict:
    import soundfile as sf

    print(f"\n[{trial.name}] {trial.instructions}")
    input("Press Enter when positioned and ready...")
    countdown()

    control_samples: list[dict] = []
    stop = threading.Event()
    started = time.monotonic()
    thread = threading.Thread(
        target=collect_control,
        args=(mic, stop, control_samples, started),
        daemon=True,
    )
    thread.start()
    if trial.servos:
        print("  SERVOS MOVING", flush=True)
        servo_motion.start()
    print(f"  RECORDING for {trial.duration:g} seconds", flush=True)
    try:
        audio, capture_complete = record_audio_bounded(
            device_index,
            sample_rate,
            channels,
            trial.duration,
        )
    finally:
        if trial.servos:
            servo_motion.stop()
        stop.set()
        thread.join(timeout=1)

    wav_path = output_dir / f"{trial.name}.wav"
    sf.write(wav_path, audio, sample_rate, subtype="PCM_24")
    result = {
        **asdict(trial),
        "wav_file": wav_path.name,
        "capture_complete": capture_complete,
        "captured_seconds": round(len(audio) / sample_rate, 3),
        **audio_metrics(audio),
        **summarize_control(control_samples),
    }
    (output_dir / f"{trial.name}_control.json").write_text(
        json.dumps(control_samples, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"  Saved {wav_path.name}: RMS {result['rms_dbfs']} dBFS, "
        f"peak {result['peak_dbfs']} dBFS, speech {result['speech_fraction']:.0%}"
        f"{' (INCOMPLETE)' if not capture_complete else ''}"
    )
    return result


def add_comparisons(results: list[dict]) -> None:
    by_name = {result["name"]: result for result in results}
    quiet = by_name.get("quiet")
    for result in results:
        result["above_quiet_db"] = ""
        if quiet and result["name"] != "quiet":
            result["above_quiet_db"] = round(result["rms_dbfs"] - quiet["rms_dbfs"], 2)


def write_summary(output_dir: Path, results: list[dict], metadata: dict) -> None:
    add_comparisons(results)
    (output_dir / "session.json").write_text(
        json.dumps({"metadata": metadata, "trials": results}, indent=2) + "\n",
        encoding="utf-8",
    )
    fields = [
        "name", "kind", "angle", "servos", "duration", "wav_file",
        "capture_complete", "captured_seconds",
        "rms_dbfs", "peak_dbfs", "above_quiet_db", "clipped_samples",
        "speech_fraction", "mean_doa_degrees", "mean_speech_energy",
    ]
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def write_all_results(results_root: Path) -> Path:
    """Combine every completed session into one Excel-compatible CSV file."""
    rows = []
    for session_path in sorted(results_root.glob("*/session.json")):
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: skipped unreadable session {session_path}: {exc}")
            continue
        metadata = session.get("metadata", {})
        for trial in session.get("trials", []):
            # Preserve compatibility with sessions created before the actuator
            # was correctly identified as a servo rather than a solenoid.
            if "servos" not in trial and "solenoids" in trial:
                trial = {**trial, "servos": trial["solenoids"]}
            row = {
                "configuration": metadata.get("configuration", ""),
                "session_created": metadata.get("created", ""),
                "distance_metres": metadata.get("distance_metres", ""),
                "audio_device": metadata.get("audio_device_name", ""),
                "sample_rate": metadata.get("sample_rate", ""),
                "channels": metadata.get("channels", ""),
                "session_folder": session_path.parent.name,
                **trial,
            }
            energy = row.get("mean_speech_energy")
            if isinstance(energy, list):
                for index, value in enumerate(energy, start=1):
                    row[f"speech_energy_beam_{index}"] = value
                row["mean_speech_energy"] = json.dumps(energy)
            rows.append(row)

    output_path = results_root / "all_results.csv"
    fields = [
        "configuration", "session_created", "session_folder", "distance_metres",
        "name", "kind", "angle", "servos", "duration", "wav_file",
        "capture_complete", "captured_seconds",
        "rms_dbfs", "peak_dbfs", "above_quiet_db", "clipped_samples",
        "speech_fraction", "mean_doa_degrees", "speech_energy_beam_1",
        "speech_energy_beam_2", "speech_energy_beam_3", "speech_energy_beam_4",
        "mean_speech_energy", "audio_device", "sample_rate", "channels",
    ]
    results_root.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", help="Mount/cover name, e.g. foam_mount_v2")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Input device name fragment or index")
    parser.add_argument(
        "--rate",
        type=int,
        default=None,
        help="Recording rate; default auto-detects 16 kHz or 48 kHz",
    )
    parser.add_argument("--channels", type=int, default=2)
    parser.add_argument("--distance", type=float, default=1.0, help="Phone distance in metres")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "artifacts" / "xvf3800_tests")
    parser.add_argument("--trial", choices=[trial.name for trial in TRIALS], help="Run only one trial")
    parser.add_argument("--list-devices", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    import sounddevice as sd

    device_index, device_info = resolve_input_device(args.device)
    channels = min(args.channels, int(device_info["max_input_channels"]))
    if channels < 1:
        raise RuntimeError("Selected input exposes no recording channels")
    sample_rate = resolve_sample_rate(
        device_index,
        channels,
        args.rate,
        device_info,
    )
    mic = create_respeaker_or_raise()
    servo_motion = ServoMotion()
    servo_motion.initialize()

    configuration = args.configuration
    existing_sessions = existing_configuration_sessions(args.output, configuration)

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output / f"{stamp}_{safe_name(configuration)}"
    output_dir.mkdir(parents=True, exist_ok=False)
    selected = [trial for trial in TRIALS if not args.trial or trial.name == args.trial]
    metadata = {
        "configuration": configuration,
        "created": datetime.now().astimezone().isoformat(),
        "distance_metres": args.distance,
        "audio_device_index": device_index,
        "audio_device_name": device_info["name"],
        "sample_rate": sample_rate,
        "channels": channels,
    }

    print("\nXVF3800 mount/cover test")
    print(f"Configuration: {configuration}")
    print(f"Input: {device_index}: {device_info['name']} ({channels} channels at {sample_rate} Hz)")
    print(f"Results: {output_dir}")
    print("Keep phone volume, distance, orientation, room, and source recording unchanged.")

    results = []
    try:
        for trial in selected:
            results.append(
                record_trial(
                    trial,
                    output_dir,
                    device_index,
                    sample_rate,
                    channels,
                    mic,
                    servo_motion,
                )
            )
            write_summary(output_dir, results, metadata)
    except KeyboardInterrupt:
        servo_motion.stop()
        print("\nTest stopped; completed trials were retained.")
        return 130

    final_dir = finalize_duplicate_configuration(
        args.output,
        output_dir,
        configuration,
        existing_sessions,
    )
    if final_dir is None:
        return 0

    print(f"\nComplete. Session table: {final_dir / 'summary.csv'}")
    print(f"All-test Excel table: {args.output / 'all_results.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
