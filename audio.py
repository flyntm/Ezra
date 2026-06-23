import sys
import time
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

# How long Ezra waits for you to begin the command
# after it prints "Ready for command."
COMMAND_TIMEOUT = 5.0

# Maximum duration of the spoken command itself
MAX_COMMAND_TIME = 10.0

# After the wake word, require this much quiet audio
# before accepting command speech.
ARM_SILENCE = 0.10
ARM_THRESHOLD = 0.005

# Require speech detection before declaring the command has started.
# A lower confirm block count helps preserve early words.
START_THRESHOLD = 0.012
START_CONFIRM_BLOCKS = 1

# Preserve more audio from before command confirmation
# so the first word does not get cut off.
PREBUFFER_SECONDS = 0.80

# End the command after sustained quiet.
END_THRESHOLD = 0.010
END_SILENCE = 1.20

# Direct ALSA devices can remain busy briefly while
# switching between Wake and Listen.
MIC_OPEN_RETRIES = 8
MIC_RETRY_DELAY = 0.25
MIC_RELEASE_DELAY = 0.25


# --------------------------------------------------
# RESPEAKER
# --------------------------------------------------

sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")

from xvf_host import ReSpeaker

dev = usb.core.find(idVendor=0x2886)

if not dev:
    raise RuntimeError("❌ ReSpeaker not found")

mic = ReSpeaker(dev)

print("✅ ReSpeaker VAD ready")


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
    Listen for a command after wake-word detection.

    If wake_audio is provided, it may contain the beginning
    of a continuously spoken command.
    """

    print("🎤 Listening for command...")

    chunks = []

    has_wake_audio = wake_audio is not None and len(wake_audio) > 0

    continuous_command = False
    wake_audio_chunks = []

    if has_wake_audio:
        wake_audio = np.asarray(
            wake_audio,
            dtype=np.float32,
        ).flatten()

        wake_audio_chunks = [
            wake_audio[i : i + BLOCKSIZE] for i in range(0, len(wake_audio), BLOCKSIZE)
        ]

        # Preserve the wake audio in the prebuffer so immediate follow-up speech
        # is still captured without forcing a false continuous-command state.
        prebuffer_blocks = max(
            1,
            int(PREBUFFER_SECONDS * SAMPLE_RATE / BLOCKSIZE),
        )

        prebuffer = deque(maxlen=prebuffer_blocks)
        prebuffer.extend(wake_audio_chunks)

        tail_samples = int(0.30 * SAMPLE_RATE)
        wake_tail = wake_audio[-tail_samples:]

        tail_rms = float(np.sqrt(np.mean(wake_tail**2)))
        continuous_command = tail_rms >= START_THRESHOLD

        if continuous_command:
            chunks.extend(wake_audio_chunks)

        print(f"Wake tail RMS: {tail_rms:.4f}")
    else:
        prebuffer_blocks = max(
            1,
            int(PREBUFFER_SECONDS * SAMPLE_RATE / BLOCKSIZE),
        )

        prebuffer = deque(maxlen=prebuffer_blocks)

    stream = open_microphone()

    try:
        print("Ready")

        armed = continuous_command
        heard_speech = continuous_command

        if has_wake_audio and not continuous_command:
            print("👂 Wake audio present — waiting for command speech")

        arm_silence_start = None
        command_wait_start = time.time()
        command_start_time = time.time() if continuous_command else None
        end_silence_start = None

        speech_blocks = 0

        start_angle = None
        last_angle = None

        if continuous_command:
            print("🎤 CONTINUOUS COMMAND STARTED")

        while True:
            audio, overflowed = stream.read(BLOCKSIZE)
            now = time.time()

            if overflowed:
                print("⚠️ Audio overflow")

            audio = np.asarray(
                audio,
                dtype=np.float32,
            ).flatten()

            rms = float(np.sqrt(np.mean(audio**2)))

            vad_speech, angle = read_vad()

            if angle is not None:
                last_angle = angle

            # Preserve recent audio until speech is confirmed.
            if not heard_speech:
                prebuffer.append(audio.copy())

            # Wait for the wake phrase to finish.
            if not armed:
                if rms < ARM_THRESHOLD:
                    if arm_silence_start is None:
                        arm_silence_start = now

                    elif now - arm_silence_start >= ARM_SILENCE:
                        armed = True
                        command_wait_start = now
                        speech_blocks = 0

                        print("👂 Ready for command")

                else:
                    arm_silence_start = None

                continue

            # Wait for a separately spoken command.
            if not heard_speech:
                if vad_speech and rms >= START_THRESHOLD:
                    speech_blocks += 1

                    if speech_blocks >= START_CONFIRM_BLOCKS:
                        heard_speech = True
                        command_start_time = now
                        start_angle = angle
                        end_silence_start = None

                        chunks.extend(list(prebuffer))
                        prebuffer.clear()

                        print(
                            f"🎤 COMMAND STARTED  "
                            f"DOA={start_angle}° "
                            f"RMS={rms:.4f}"
                        )

                else:
                    speech_blocks = 0

                if now - command_wait_start >= COMMAND_TIMEOUT:
                    print("No command detected")
                    return None

                continue

            # Record the command.
            chunks.append(audio.copy())

            if rms < END_THRESHOLD:
                if end_silence_start is None:
                    end_silence_start = now

                elif now - end_silence_start >= END_SILENCE:
                    print(f"🛑 COMMAND ENDED    " f"DOA={last_angle}°")
                    break

            else:
                end_silence_start = None

            if (
                command_start_time is not None
                and now - command_start_time >= MAX_COMMAND_TIME
            ):
                print("Maximum command time reached")
                break

    finally:
        try:
            stream.stop()
        except Exception:
            pass

        try:
            stream.close()
        except Exception:
            pass

        time.sleep(MIC_RELEASE_DELAY)

    if not chunks:
        print("No audio captured")
        return None

    audio = np.concatenate(chunks, axis=0).flatten()

    duration = len(audio) / SAMPLE_RATE
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0

    print(f"Recording length: {duration:.2f} sec")
    print(f"Recording peak: {peak:.6f}")
    print(f"Recording RMS: {rms:.6f}")

    return audio.astype(np.float32)
