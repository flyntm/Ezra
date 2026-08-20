#!/usr/bin/env python3
"""
Benchmarking tool: Compare local Whisper (base.en & Vosk) vs online STT models.

Usage:
  python compare_stt.py --record --prompt "Say something"
  python compare_stt.py --wav /path/to/audio.wav --reference "expected text"

Standalone tool for evaluating transcription quality and speed.
Production main.py uses local base.en Whisper exclusively.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from stt import transcribe as local_transcribe


def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    n = len(ref_words)
    m = len(hyp_words)
    dp = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],
                    dp[i][j - 1],
                    dp[i - 1][j - 1],
                )

    return dp[n][m] / max(1, n)


def transcribe_openai(wav_path: Path, model: str) -> str:
    if OpenAI is None:
        raise RuntimeError("OpenAI package is not installed.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)

    with open(wav_path, "rb") as audio_file:
        result = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
        )

    return result.text.strip()


def transcribe_vosk(wav_path: Path, model_dir: Path) -> str:
    try:
        from vosk import KaldiRecognizer, Model
    except ImportError as exc:
        raise RuntimeError("Vosk package is not installed.") from exc

    if not model_dir.exists():
        raise RuntimeError(f"Vosk model directory not found: {model_dir}")

    with open(wav_path, "rb") as wf_file:
        import wave

        with wave.open(wf_file, "rb") as wf:
            sample_rate = wf.getframerate()
            model = Model(str(model_dir))
            recognizer = KaldiRecognizer(model, sample_rate)
            recognizer.SetWords(False)

            transcript = []
            while True:
                data = wf.readframes(4000)
                if len(data) == 0:
                    break
                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    transcript.append(result.get("text", ""))

            final = json.loads(recognizer.FinalResult())
            transcript.append(final.get("text", ""))

    return " ".join(part for part in transcript if part).strip()


def record_wav(
    target_path: Path,
    prompt: str,
    duration: float = 3.0,
    samplerate: int = 16000,
    channels: int = 1,
) -> None:
    """Record a short WAV file with a text prompt for the user."""

    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            "Recording requires the sounddevice and soundfile packages."
        ) from exc

    while True:
        print("\nPlease read the following text clearly:\n")
        print(f"  {prompt}\n")
        input("Press Enter to start recording...")

        print("Recording...")
        audio = sd.rec(
            int(duration * samplerate),
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
        )
        sd.wait()

        sf.write(str(target_path), audio, samplerate)
        print(f"Saved new recording to: {target_path}\n")

        print("Playing back the recording...")
        data, sr = sf.read(str(target_path), dtype="float32")
        sd.play(data, sr)
        sd.wait()

        keep = input("Keep this recording and continue? [y/N]: ").strip().lower()
        if keep in ("y", "yes"):
            break

        retry = input("Rerecord? [y/N]: ").strip().lower()
        if retry not in ("y", "yes"):
            raise RuntimeError("Recording canceled by user.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare local Whisper transcription with an online STT service."
    )

    parser.add_argument(
        "--wav",
        type=Path,
        default=Path("/tmp/whisper_input.wav"),
        help="Path to the WAV file to transcribe (default: /tmp/whisper_input.wav)",
    )
    parser.add_argument(
        "--openai-model",
        default="gpt-4o-transcribe",
        help="Online OpenAI transcription model to use.",
    )
    parser.add_argument(
        "--openai-model-2",
        default="whisper-1",
        help="Second online OpenAI transcription model to compare.",
    )
    parser.add_argument(
        "--vosk-model",
        default=Path("vosk-model-small-en-us-0.15"),
        type=Path,
        help="Local Vosk model directory to use.",
    )
    parser.add_argument(
        "--reference",
        help=(
            "Optional reference transcription to compute WER against. "
            "If omitted, the prompt text is used as the reference."
        ),
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record a new WAV file before transcription.",
    )
    parser.add_argument(
        "--prompt",
        default="Hey Ezra, what time is it?",
        help="Text to display for the recording prompt.",
    )
    parser.add_argument(
        "--record-duration",
        type=float,
        default=8.0,
        help="Duration in seconds to record for the new WAV file.",
    )

    args = parser.parse_args()
    wav_path = args.wav

    if args.reference is None:
        args.reference = args.prompt

    if args.record:
        try:
            record_wav(wav_path, args.prompt, args.record_duration)
        except Exception as exc:
            print(f"ERROR during recording: {exc}")
            return 1

    if not wav_path.exists():
        print(f"ERROR: WAV file not found: {wav_path}")
        return 1

    print(f"Using WAV file: {wav_path}")
    print("Running local Whisper transcription...")
    start_local = time.time()

    try:
        import wave
        import numpy as np

        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if sampwidth == 1:
            dtype = np.uint8
        elif sampwidth == 2:
            dtype = np.int16
        elif sampwidth == 4:
            dtype = np.int32
        else:
            raise ValueError(f"Unsupported WAV sample width: {sampwidth}")

        audio_data = np.frombuffer(frames, dtype=dtype)
        if channels > 1:
            audio_data = audio_data.reshape(-1, channels)[:, 0]

        if dtype == np.int16:
            audio_float = audio_data.astype("float32") / 32768.0
        elif dtype == np.int32:
            audio_float = audio_data.astype("float32") / 2147483648.0
        elif dtype == np.uint8:
            audio_float = (audio_data.astype("float32") - 128.0) / 128.0
        else:
            audio_float = audio_data.astype("float32")

        if sr != 16000:
            print(f"WARNING: WAV sample rate is {sr}; local STT expects 16000.")

        local_text = local_transcribe(audio_float)

    except Exception as exc:
        print(f"ERROR during local transcription: {exc}")
        return 1

    elapsed_local = time.time() - start_local
    print(f"Local Whisper time: {elapsed_local:.2f} sec")
    print(f"Local Whisper transcript:\n{local_text}\n")

    print("Running local Vosk transcription...")
    start_vosk = time.time()
    try:
        vosk_text = transcribe_vosk(wav_path, args.vosk_model)
    except Exception as exc:
        print(f"ERROR during local Vosk transcription: {exc}")
        return 1
    elapsed_vosk = time.time() - start_vosk
    print(f"Local Vosk time: {elapsed_vosk:.2f} sec")
    print(f"Local Vosk transcript:\n{vosk_text}\n")

    print("Running OpenAI online transcription...")
    start_online = time.time()
    try:
        openai_text = transcribe_openai(wav_path, args.openai_model)
    except Exception as exc:
        print(f"ERROR during online transcription: {exc}")
        return 1

    elapsed_online = time.time() - start_online
    print(f"Online model ({args.openai_model}) time: {elapsed_online:.2f} sec")
    print(f"Online ({args.openai_model}) transcript:\n{openai_text}\n")

    openai_text_2 = None
    elapsed_online_2 = None
    if args.openai_model_2:
        print(f"Running second OpenAI model ({args.openai_model_2})...")
        start_online_2 = time.time()
        try:
            openai_text_2 = transcribe_openai(wav_path, args.openai_model_2)
        except Exception as exc:
            print(f"ERROR during online transcription for {args.openai_model_2}: {exc}")
            return 1
        elapsed_online_2 = time.time() - start_online_2
        print(f"Online model ({args.openai_model_2}) time: {elapsed_online_2:.2f} sec")
        print(f"Online ({args.openai_model_2}) transcript:\n{openai_text_2}\n")

    if args.reference:
        reference = normalize_text(args.reference)
        reference_words = reference.split()

        if reference in ("...", "n/a") or len(reference_words) < 2:
            print(
                f"WARNING: reference appears invalid or too short for WER: {args.reference!r}"
            )
            print("Skipping WER calculation.")
        else:
            local_score = word_error_rate(reference, normalize_text(local_text))
            vosk_score = word_error_rate(reference, normalize_text(vosk_text))
            online_score = word_error_rate(reference, normalize_text(openai_text))
            print(f"Reference: {reference}")
            print(f"Local Whisper WER: {local_score:.3f}")
            print(f"Local Vosk WER: {vosk_score:.3f}")
            print(f"Online ({args.openai_model}) WER: {online_score:.3f}")
            if openai_text_2 is not None:
                online_score_2 = word_error_rate(
                    reference, normalize_text(openai_text_2)
                )
                print(f"Online ({args.openai_model_2}) WER: {online_score_2:.3f}")

    print("Comparison complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
