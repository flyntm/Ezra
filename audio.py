import subprocess
import time
import numpy as np

MIC_DEVICE = "alsa_input.usb-Anker_PowerConf_A3321-DEV-SN1-01.mono-fallback"


def listen(timeout=None):
    print("🎤 Listening...")

    # =========================
    # 🔥 MIC WARM-UP (stabilizes input)
    # =========================
    try:
        subprocess.run(
            [
                "parecord",
                "--device=" + MIC_DEVICE,
                "--rate=16000",
                "--channels=1",
                "--format=s16le",
                "--file-format=raw",
                "/dev/null",
            ],
            timeout=0.3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass

    filename = "/tmp/ezra_record.wav"
    duration = 6  # keep full capture window

    try:
        subprocess.run(
            [
                "timeout",
                str(duration),
                "parecord",
                "--device=" + MIC_DEVICE,
                "--rate=16000",
                "--channels=1",
                "--format=s16le",
                "--file-format=wav",
                filename,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return None

    time.sleep(0.1)

    try:
        with open(filename, "rb") as f:
            f.read(44)  # skip WAV header
            audio = np.frombuffer(f.read(), dtype=np.int16)
            audio = audio.astype(np.float32) / 32768.0

            # 🔥 CLEAN, SINGLE GAIN STAGE
            audio = np.clip(audio * 12.0, -1.0, 1.0)

    except Exception:
        return None

    # =========================
    # ENERGY CHECK
    # =========================
    rms = np.sqrt(np.mean(audio**2))
    print(f"Level: {rms:.4f}")

    # 🔥 FILTER OUT JUNK / FRAGMENTS
    if rms < 0.01:
        return None

    # =========================
    # 🔥 STABLE TRIM (BEST VERSION)
    # =========================
    max_samples = 16000 * 4  # last 4 seconds

    if len(audio) > max_samples:
        audio = audio[-max_samples:]

    return audio
