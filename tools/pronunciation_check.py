#!/usr/bin/env python3
"""Type text and hear Ezra's current Piper pronunciation three times."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    PIPER_PATH,
    SPEAKER_DEVICE,
    TTS_LENGTH_SCALE,
    TTS_MODEL_PATH,
    TTS_SENTENCE_SILENCE,
    TTS_SYNTHESIS_TIMEOUT_SECONDS,
)
from persistent_piper import PersistentPiper
from tts_pronunciation import apply_pronunciation_overrides


def _play_audio(audio_path):
    candidates = list(dict.fromkeys((SPEAKER_DEVICE, "default", None)))
    failures = []

    for device in candidates:
        command = ["aplay"]
        if device is not None:
            command.extend(("-D", str(device)))
        command.append(os.fspath(audio_path))
        try:
            subprocess.run(command, check=True)
            return
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            failures.append(str(exc))

    raise RuntimeError("Audio playback failed: " + "; ".join(failures))


def main():
    parser = argparse.ArgumentParser(
        description="Synthesize text with Ezra's current Piper pronunciation and play it three times."
    )
    parser.add_argument("text", nargs="*", help="Text to synthesize")
    arguments = parser.parse_args()
    text = " ".join(arguments.text).strip()
    if not text:
        text = input("Text to speak three times: ").strip()
    if not text:
        print("No text entered.")
        return 1

    spoken_text = apply_pronunciation_overrides(text)
    if spoken_text != text:
        print(f"Piper will receive: {spoken_text}")

    piper = PersistentPiper(PIPER_PATH, TTS_MODEL_PATH)
    try:
        with tempfile.TemporaryDirectory(prefix="ezra-pronunciation-") as directory:
            audio_path = Path(directory) / "pronunciation.wav"
            synthesized = piper.synthesize(
                spoken_text,
                audio_path,
                TTS_LENGTH_SCALE,
                TTS_SENTENCE_SILENCE,
                timeout_seconds=TTS_SYNTHESIS_TIMEOUT_SECONDS,
            )
            if not synthesized:
                print("Piper could not synthesize the text.")
                return 1

            for repetition in range(1, 4):
                print(f"Playing {repetition}/3")
                _play_audio(audio_path)
    finally:
        piper.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
