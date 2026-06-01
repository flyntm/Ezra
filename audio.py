import subprocess
import time
import os
import numpy as np
import soundfile as sf

MIC_DEVICE = "alsa_input.usb-Anker_PowerConf_A3321-DEV-SN1-01.mono-fallback"


def listen(timeout=None):

    print("🎤 Listening...")

    filename = "/home/flyntm/projects/ezra/ezra_record.wav"

    duration = 6

    # ---------------------------------
    # Warm up microphone
    # ---------------------------------

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

    # ---------------------------------
    # Record audio
    # ---------------------------------

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
    except Exception as e:
        print("Record failed:", e)
        return None

    time.sleep(0.1)

    # ---------------------------------
    # Verify recording
    # ---------------------------------

    try:
        filesize = os.path.getsize(filename)

        print(f"Recorded file size: {filesize:,} bytes")

        data, sr = sf.read(filename)

        print(f"WAV duration: {len(data)/sr:.2f} sec")

    except Exception as e:
        print("WAV verification failed:", e)

    # ---------------------------------
    # Load audio for Whisper
    # ---------------------------------

    try:

        audio, sr = sf.read(filename)

        audio = audio.astype(np.float32)

        print("Max amplitude:", np.max(np.abs(audio)))

        rms = np.sqrt(np.mean(audio**2))

        print(f"Level: {rms:.4f}")
        print(f"Samples: {len(audio)}")

        if rms < 0.01:
            print("⚠️ Audio too quiet")
            return None

        print(f"Recording length: {len(audio)/sr:.2f} sec")
        print(f"💾 Saved recording to {filename}")

        return audio

    except Exception as e:

        print("Audio load failed:", e)
        return None
