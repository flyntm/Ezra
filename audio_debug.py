import os
import sys

import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav

from config import DEBUG_AUDIO_SAMPLE_RATE, DEBUG_WAV_FILE


def save_debug_wav(
    audio, sample_rate=DEBUG_AUDIO_SAMPLE_RATE, debug_wav=DEBUG_WAV_FILE
):
    """Save captured audio as debug WAV normalized to peak 0.9."""

    if audio is None:
        return

    arr = np.asarray(audio, dtype=np.float32).flatten()

    if arr.size == 0:
        return

    peak = float(np.max(np.abs(arr)))
    if peak > 0:
        gain = 0.9 / peak
        arr = np.clip(arr * gain, -1.0, 1.0)

    arr_int16 = np.int16(np.clip(arr * 32767.0, -32768, 32767))
    wav.write(debug_wav, sample_rate, arr_int16)


def get_single_key():
    """Read a single key press without requiring Enter (Unix/Linux)."""

    try:
        import tty
        import termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        return ch.lower()

    except Exception:
        return input().lower()


def playback_diagnostic(debug_wav=DEBUG_WAV_FILE):
    """Auto-play the STT debug WAV file with optional repeat."""

    if not os.path.isfile(debug_wav):
        print("🧪 No debug WAV found")
        return

    try:
        sample_rate, data = wav.read(debug_wav)
    except Exception as e:
        print(f"⚠️ Failed to read debug WAV: {e}")
        return

    print("\n🧪 Playback diagnostic")
    print("🧪 Playing recorded command...")

    try:
        sd.play(data, sample_rate)
        sd.wait()
        print("🧪 Playback finished")
    except Exception as e:
        print(f"⚠️ Playback failed: {e}")
        return

    while True:
        print("🧪 Play again? [y/n]: ", end="", flush=True)

        try:
            ch = get_single_key()
            print(ch)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if ch not in {"y", "yes"}:
            break

        try:
            sd.play(data, sample_rate)
            sd.wait()
            print("🧪 Playback finished")
        except Exception as e:
            print(f"⚠️ Playback failed: {e}")
            break
