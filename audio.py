import sys
import time

import numpy as np
import sounddevice as sd
import usb.core

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SAMPLE_RATE = 48000
CHANNELS = 1
BLOCKSIZE = 1024

COMMAND_TIMEOUT = 5
MAX_TIME = 10

# RMS-based end detection
END_THRESHOLD = 0.010
END_SILENCE = 0.8

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
    try:
        doa = mic.read("DOA_VALUE")

        if len(doa) >= 2:
            angle = doa[0]
            speech = bool(doa[1])
            return speech, angle

    except Exception as e:
        print(f"VAD error: {e}")

    return False, None


# --------------------------------------------------
# LISTEN
# --------------------------------------------------


def listen(wake_audio=None):
    """
    wake_audio is ignored.
    We now start fresh after wake-word detection.
    """

    print("🎤 Listening for command...")

    chunks = []

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        blocksize=BLOCKSIZE,
    ) as stream:

        print("Ready")

        heard_speech = False
        silence_start = None

        start_time = time.time()

        start_angle = None
        last_angle = None

        while True:

            audio, overflowed = stream.read(BLOCKSIZE)

            if overflowed:
                print("⚠️ Audio overflow")

            speech, angle = read_vad()

            if angle is not None:
                last_angle = angle

            # ---------------------------------
            # START RECORDING (VAD)
            # ---------------------------------

            if speech and not heard_speech:

                heard_speech = True
                start_angle = angle

                print(f"🎤 COMMAND STARTED  DOA={start_angle}°")

            # ---------------------------------
            # RECORD AUDIO
            # ---------------------------------

            if heard_speech:

                chunks.append(audio)

                rms = np.sqrt(np.mean(audio**2))

                # Debug if desired
                # print(f"RMS={rms:.4f}")

                if rms < END_THRESHOLD:

                    if silence_start is None:
                        silence_start = time.time()

                    elif time.time() - silence_start > END_SILENCE:
                        print(f"🛑 COMMAND ENDED    DOA={last_angle}°")
                        break

                else:
                    silence_start = None

            # ---------------------------------
            # NO COMMAND
            # ---------------------------------

            if not heard_speech and time.time() - start_time > COMMAND_TIMEOUT:
                print("No command detected")
                return None

            # ---------------------------------
            # SAFETY TIMEOUT
            # ---------------------------------

            if time.time() - start_time > MAX_TIME:
                print("Maximum time reached")
                break

            time.sleep(0.02)

    if not chunks:
        print("No audio captured")
        return None

    audio = np.concatenate(chunks, axis=0)

    print(f"Recording length: " f"{len(audio) / SAMPLE_RATE:.2f} sec")

    return audio.astype(np.float32)
