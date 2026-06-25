import contextlib
import os
import shutil
import time

import numpy as np
import scipy.io.wavfile as wav
from faster_whisper import WhisperModel

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SAMPLE_RATE = 16000

# Tuned for base.en Whisper model (fast, ~80M params).
# These thresholds balance filtering out noise/silence
# while avoiding false negatives on quiet speech.
MIN_AUDIO_SECONDS = 0.75  # Minimum command duration (0.75 sec)
MIN_AUDIO_PEAK = 0.008  # Minimum peak amplitude to transcribe

TEMP_WAV_FILE = "temp.wav"
DEBUG_WAV_FILE = "/tmp/whisper_input.wav"


# --------------------------------------------------
# STDERR SUPPRESSION
# --------------------------------------------------


@contextlib.contextmanager
def suppress_stderr():
    """
    Temporarily suppress low-level library warnings written directly
    to stderr.
    """

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)

    os.dup2(devnull, 2)

    try:
        yield

    finally:
        os.dup2(old_stderr, 2)
        os.close(devnull)
        os.close(old_stderr)


# --------------------------------------------------
# WHISPER MODEL
# --------------------------------------------------


print("🧠 Loading Whisper model...")

with suppress_stderr():
    # base.en: Fast (~80M params), good accuracy for commands.
    # Runs ~2-3 sec on CPU. Alternative: small.en (~244M) for better
    # accuracy but 5-7 sec latency; use compare_stt.py to benchmark.
    model = WhisperModel(
        "base.en",
        device="cpu",
        compute_type="int8",
    )

print("✅ Model loaded")


# --------------------------------------------------
# TRANSCRIPTION
# --------------------------------------------------


def transcribe(audio):
    """
    Transcribe 16 kHz mono float32 audio from Listen.

    Returns recognized text, or an empty string when no usable speech
    is found.
    """

    total_start = time.time()

    try:
        print("🧠 Transcribing...")

        if audio is None:
            print("⚠️ No audio supplied to STT")
            return ""

        audio_16k = np.asarray(
            audio,
            dtype=np.float32,
        ).flatten()

        if audio_16k.size == 0:
            print("⚠️ Empty audio supplied to STT")
            return ""

        # Protect against invalid samples.
        audio_16k = np.nan_to_num(
            audio_16k,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )

        duration = len(audio_16k) / SAMPLE_RATE
        peak = float(np.max(np.abs(audio_16k)))
        rms = float(np.sqrt(np.mean(audio_16k**2)))

        print(f"Audio length: {duration:.2f} sec")
        print(f"Audio peak: {peak:.6f}")
        print(f"Audio RMS: {rms:.6f}")

        # Normalize audio to a target peak to improve STT accuracy.
        # Always scale so the maximum peak is near 0.9 (about -1 dBFS).
        if peak > 0:
            target_peak = 0.9
            gain = target_peak / peak
            audio_16k = np.clip(audio_16k * gain, -1.0, 1.0)
            peak = float(np.max(np.abs(audio_16k)))
            rms = float(np.sqrt(np.mean(audio_16k**2)))
            print(
                f"🔊 Normalized to peak {target_peak:.2f} (gain x{gain:.2f}), new peak {peak:.6f}"
            )

        # --------------------------------------------------
        # REJECT CLEARLY EMPTY RECORDINGS
        # --------------------------------------------------

        if duration < MIN_AUDIO_SECONDS:
            print(f"⚠️ Skipping STT: recording too short " f"({duration:.2f} sec)")
            return ""

        if peak < MIN_AUDIO_PEAK:
            print(f"⚠️ Skipping STT: audio too quiet " f"(peak={peak:.6f})")
            return ""

        # Keep a WAV copy for troubleshooting.
        # Write the debug WAV as 16-bit PCM so playback tools like aplay
        # hear the same signal level that Whisper receives.
        audio_int16 = np.int16(np.clip(audio_16k * 32767.0, -32768, 32767))

        wav.write(
            TEMP_WAV_FILE,
            SAMPLE_RATE,
            audio_int16,
        )

        shutil.copy(
            TEMP_WAV_FILE,
            DEBUG_WAV_FILE,
        )

        if peak < 0.10:
            print(
                "⚠️ Low input level detected. "
                "Check microphone gain, proximity, and ambient noise."
            )

        print(f"💾 Saved Whisper input to " f"{DEBUG_WAV_FILE}")

        # --------------------------------------------------
        # WHISPER
        # --------------------------------------------------

        whisper_start = time.time()

        with suppress_stderr():
            # Transcription parameters tuned for real-time wake-word flow.
            # base.en with greedy decoding + VAD filter = ~2 sec latency.
            segments, info = model.transcribe(
                audio_16k,
                language="en",
                # Bias decoding toward a short voice command following the
                # wake phrase, which helps reduce "here's what" style
                # hallucinations from wake-word audio.
                initial_prompt="A short spoken home assistant command after the wake word Ezra.",
                # Greedy decoding (beam_size=1) is much faster than beam_size=5
                # and is sufficient for short voice commands.
                beam_size=1,
                # Prevent prior context bleeding into new commands.
                condition_on_previous_text=False,
                # VAD: Remove extended silence, speeds up decoding.
                # Tuned for base.en to reduce false positives on ambient noise.
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 500,  # Silence threshold
                    "speech_pad_ms": 200,  # Buffer around speech
                },
            )

            # faster-whisper performs decoding while the generator
            # is consumed, so convert it to a list while timing it.
            segments = list(segments)

        whisper_elapsed = time.time() - whisper_start

        print(f"⏱️ Whisper decoding took " f"{whisper_elapsed:.2f} sec")

        text = " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()

        total_elapsed = time.time() - total_start

        print(f"⏱️ Total STT took " f"{total_elapsed:.2f} sec")

        if not text:
            print("⚠️ No speech recognized")
            return ""

        print(f"You said: {text}")

        return text

    except Exception as e:
        elapsed = time.time() - total_start

        print(f"❌ STT ERROR after {elapsed:.2f} sec: {e}")
        return ""
