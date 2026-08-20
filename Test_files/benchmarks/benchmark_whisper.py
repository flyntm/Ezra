#!/usr/bin/env python3

import os
import time
import tempfile
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel

# Optional cloud providers
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from deepgram import DeepgramClient, PrerecordedOptions, FileSource
except ImportError:
    DeepgramClient = None

tiny_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

base_model = WhisperModel("base.en", device="cpu", compute_type="int8")

small_model = WhisperModel("small.en", device="cpu", compute_type="int8")

# --------------------------------------------------
# Settings
# --------------------------------------------------

WAV_FILE = "ezra_record.wav"
SAMPLE_RATE = 48000
RECORD_SECONDS = 6

results = []

# --------------------------------------------------
# Record
# --------------------------------------------------

answer = input("\nRecord new audio? (y/n): ").lower()

if answer == "y":

    print("\nDevice 0 info:")
    print(sd.query_devices(0))

    print("\nOpening stream...")

    with sd.InputStream(
        device=0, samplerate=SAMPLE_RATE, channels=1, dtype="float32"
    ) as stream:

        print("Stream open")

        # Give device time to stabilize
        time.sleep(2)

        print("Recording starts NOW")

        start = time.time()

        audio, overflowed = stream.read(SAMPLE_RATE * RECORD_SECONDS)

        elapsed = time.time() - start

        print(f"Capture time: {elapsed:.2f} sec")
        print(f"Overflow: {overflowed}")

    sf.write(WAV_FILE, audio, SAMPLE_RATE)

    print(f"Saved: {WAV_FILE}")

# --------------------------------------------------
# Playback
# --------------------------------------------------

answer = input("\nPlayback recording? (y/n): ").lower()

if answer == "y":

    audio, sr = sf.read(WAV_FILE)

    print("Playing...")
    sd.play(audio, sr)
    sd.wait()

# --------------------------------------------------
# Helper
# --------------------------------------------------


def print_result(name, elapsed, text):

    results.append((name, elapsed, text))

    print("\n" + "=" * 60)
    print(name)
    print(f"Time: {elapsed:.2f} sec")
    print(f"Text: {text}")
    print("=" * 60)


# --------------------------------------------------
# Whisper Benchmark
# --------------------------------------------------


def benchmark_whisper(model_name):

    if model_name == "tiny.en":
        model = tiny_model

    elif model_name == "base.en":
        model = base_model

    elif model_name == "small.en":
        model = small_model

    else:
        print(f"Unknown model: {model_name}")
        return

    print(f"\nUsing {model_name}...")

    start = time.time()

    segments, info = model.transcribe(WAV_FILE, beam_size=5)

    text = "".join(segment.text for segment in segments)

    elapsed = time.time() - start

    print_result(f"Whisper {model_name}", elapsed, text)


# --------------------------------------------------
# OpenAI Benchmark
# --------------------------------------------------


def benchmark_openai():

    if OpenAI is None:
        print("\nOpenAI package not installed.")
        return

    if not os.getenv("OPENAI_API_KEY"):
        print("\nOPENAI_API_KEY not set.")
        return

    client = OpenAI()

    start = time.time()

    with open(WAV_FILE, "rb") as audio:

        result = client.audio.transcriptions.create(
            model="gpt-4o-transcribe", file=audio
        )

    elapsed = time.time() - start

    print_result("OpenAI gpt-4o-transcribe", elapsed, result.text)


# --------------------------------------------------
# Deepgram Benchmark
# --------------------------------------------------


def benchmark_deepgram():

    if DeepgramClient is None:
        print("\nDeepgram SDK not installed.")
        return

    key = os.getenv("DEEPGRAM_API_KEY")

    if not key:
        print("\nDEEPGRAM_API_KEY not set.")
        return

    client = DeepgramClient(key)

    with open(WAV_FILE, "rb") as f:
        payload: FileSource = {"buffer": f.read()}

    options = PrerecordedOptions(model="nova-3", smart_format=True)

    start = time.time()

    response = client.listen.prerecorded.v("1").transcribe_file(payload, options)

    elapsed = time.time() - start

    text = response.results.channels[0].alternatives[0].transcript

    print_result("Deepgram Nova-3", elapsed, text)


# --------------------------------------------------
# Menu
# --------------------------------------------------

while True:

    print("""
1 - Whisper tiny.en
2 - Whisper base.en
3 - Whisper small.en
4 - OpenAI gpt-4o-transcribe
5 - Run ALL
0 - Exit
""")

    choice = input("Selection: ")

    if choice == "1":
        benchmark_whisper("tiny.en")

    elif choice == "2":
        benchmark_whisper("base.en")

    elif choice == "3":
        benchmark_whisper("small.en")

    elif choice == "4":
        benchmark_openai()

    elif choice == "5":
        benchmark_whisper("tiny.en")
        benchmark_whisper("base.en")
        benchmark_whisper("small.en")
        benchmark_openai()

    elif choice == "0":
        break

# --------------------------------------------------
# Summary
# --------------------------------------------------

if results:

    print("\n\nSUMMARY")
    print("-" * 80)

    for name, elapsed, text in results:

        print(f"{name:<30} " f"{elapsed:>6.2f} sec")
