import sys
import time
import queue
from collections import deque

import numpy as np
import sounddevice as sd
import usb.core

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

MIC_DEVICE = 1

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1024
MIC_DEVICE = 1

# How long Ezra waits for you to begin the command
# after it prints "Ready for command."
COMMAND_TIMEOUT = 5.0

# Maximum duration of the spoken command itself
MAX_COMMAND_TIME = 10.0

# After wake word, silence before accepting command (if not continuous).
ARM_SILENCE = 0.10
ARM_THRESHOLD = 0.005

# Require speech detection before declaring command start.
START_THRESHOLD = 0.012
START_CONFIRM_BLOCKS = 1

# Preserve audio from before command confirmation.
PREBUFFER_SECONDS = 0.80

# End command after sustained quiet (ReSpeaker VAD-driven).
END_SILENCE = 0.8  # Silence duration to trigger end

# Direct ALSA devices can remain busy briefly while
# switching between Wake and Listen.
MIC_OPEN_RETRIES = 8
MIC_RETRY_DELAY = 0.25
MIC_RELEASE_DELAY = 0.25


# --------------------------------------------------
# RESPEAKER SETUP
# --------------------------------------------------

sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")

from xvf_host import ReSpeaker

dev = usb.core.find(idVendor=0x2886)

if not dev:
    raise RuntimeError("❌ ReSpeaker not found")

mic = ReSpeaker(dev)

print("✅ ReSpeaker hardware VAD ready")


# --------------------------------------------------
# HELPERS
# --------------------------------------------------


def read_vad():
    """Return the ReSpeaker speech flag and direction of arrival."""

    try:
        doa = mic.read("DOA_VALUE")

        if len(doa) >= 2:
            angle = doa[0]
            speech = bool(doa[1])
            return speech, angle

    except Exception as e:
        print(f"VAD error: {e}")

    return False, None


def open_microphone():
    """
    Open the direct ReSpeaker ALSA device.

    Wake and Listen use the same hardware device, so ALSA may need
    a brief moment to release it while switching between streams.
    """

    last_error = None

    for attempt in range(1, MIC_OPEN_RETRIES + 1):
        try:
            stream = sd.InputStream(
                device=MIC_DEVICE,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCKSIZE,
            )

            stream.start()
            return stream

        except sd.PortAudioError as e:
            last_error = e

            if attempt < MIC_OPEN_RETRIES:
                print(
                    f"⚠️ Microphone busy — retrying "
                    f"({attempt}/{MIC_OPEN_RETRIES})..."
                )
                time.sleep(MIC_RETRY_DELAY)

    raise last_error


# --------------------------------------------------
# LISTEN
# --------------------------------------------------


def listen(wake_audio=None):
    """
    Listen for a command after wake-word detection using ReSpeaker hardware VAD.

    If wake_audio is provided, it is prepended so that speech beginning
    immediately after the wake word is retained.
    """

    print("👂 Listening for command (ReSpeaker VAD)...")

    frames = []

    if wake_audio is not None and len(wake_audio) > 0:
        wake_audio = np.asarray(wake_audio, dtype=np.float32)
        if wake_audio.ndim == 1:
            wake_audio = wake_audio.reshape(-1, 1)
        frames.append(wake_audio)
        print(
            f"📼 Preserved {wake_audio.shape[0]/SAMPLE_RATE:.2f} sec of wake detection audio"
        )

    if frames:
        print(
            f"📼 Starting command capture with {frames[0].shape[0]/SAMPLE_RATE:.2f} sec of prebuffer audio"
        )

    start_time = time.time()
    command_started = False
    silence_start = None
    wake_tail_ignore_until = start_time + 0.20
    wake_tail_ignored = False

    audio_queue = queue.Queue()

    def audio_callback(indata, frames_count, time_info, status):
        audio_queue.put(indata.copy())

    with sd.InputStream(
        device=MIC_DEVICE,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_callback,
        blocksize=BLOCKSIZE,
    ):
        while True:
            # Collect available audio frames.
            while not audio_queue.empty():
                frames.append(audio_queue.get())

            # Check ReSpeaker hardware VAD.
            doa = mic.read("DOA_VALUE")
            vad_speech = bool(doa[1])
            angle = doa[0] if len(doa) > 0 else None

            # Ignore a brief wake-tail window so the prebuffer does not
            # immediately begin the command on the last syllable of "hey ezra".
            if not wake_tail_ignored and time.time() >= wake_tail_ignore_until:
                wake_tail_ignored = True
                print("⏳ Wake-tail ignore window ended")

            if not wake_tail_ignored:
                if time.time() - start_time >= COMMAND_TIMEOUT:
                    print("⚠️ No command speech detected within timeout")
                    break
                time.sleep(0.05)
                continue

            if not command_started:
                if vad_speech:
                    command_started = True
                    silence_start = None
                    print("🎤 Command speech detected")
                elif time.time() - start_time >= COMMAND_TIMEOUT:
                    print("⚠️ No command speech detected within timeout")
                    break
            else:
                if vad_speech:
                    silence_start = None
                else:
                    if silence_start is None:
                        silence_start = time.time()

                    if time.time() - silence_start >= END_SILENCE:
                        print("🛑 Command ended after silence")
                        break

            # Safety: max command time.
            if time.time() - start_time >= MAX_COMMAND_TIME:
                print("⚠️ Maximum command time reached")
                break

            time.sleep(0.05)

    # Convert frames to numpy array.
    if not frames:
        print("⚠️ No audio captured")
        return None

    audio = np.concatenate(frames, axis=0)

    # Ensure float32 format for STT.
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)

    duration = len(audio) / SAMPLE_RATE
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0

    print(f"Recording length: {duration:.2f} sec")
    print(f"Recording peak: {peak:.6f}")
    print(f"Recording RMS: {rms:.6f}")

    return audio
