import os
import sys
import time
import queue
import wave

import numpy as np
import sounddevice as sd
import usb.core

os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")

from openwakeword.model import Model

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1024

WAV_FILE = "/tmp/vad_wake.wav"

WAKE_THRESHOLD = 0.20

# --------------------------------------------------
# LOAD WAKE MODELS
# --------------------------------------------------

print("🧠 Loading wake word models...")

wake_model = Model(
    wakeword_models=[
        "/home/flyntm/projects/ezra/ezra.onnx",
        "/home/flyntm/projects/ezra/hey_ezra.onnx",
        "/home/flyntm/projects/ezra/ezzera.onnx",
    ],
    inference_framework="onnx",
)

print("✅ Wake models loaded")
print("Loaded models:", wake_model.models.keys())

# --------------------------------------------------
# RESPEAKER
# --------------------------------------------------

sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")

from xvf_host import ReSpeaker

dev = usb.core.find(idVendor=0x2886)

if not dev:
    print("❌ ReSpeaker not found")
    sys.exit(1)

mic = ReSpeaker(dev)

print("✅ ReSpeaker Connected")

# --------------------------------------------------
# AUDIO
# --------------------------------------------------

audio_queue = queue.Queue()


def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)

    audio_queue.put(indata.copy())


# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

print("Waiting for speech...\n")

try:

    while True:

        # ------------------------------------------
        # WAIT FOR SPEECH START
        # ------------------------------------------

        while True:

            doa = mic.read("DOA_VALUE")

            speech = False

            if len(doa) >= 2:
                angle = doa[0]
                speech = bool(doa[1])

            if speech:
                print(f"\n🎤 START SPEECH   DOA={angle}°")
                break

            time.sleep(0.05)

        # ------------------------------------------
        # RECORD UNTIL SPEECH ENDS
        # ------------------------------------------

        frames = []

        start_time = time.time()
        silence_start = None

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCKSIZE,
            callback=audio_callback,
        ):

            while True:

                while not audio_queue.empty():
                    frames.append(audio_queue.get())

                doa = mic.read("DOA_VALUE")

                speech = False

                if len(doa) >= 2:
                    angle = doa[0]
                    speech = bool(doa[1])

                if speech:
                    silence_start = None

                else:

                    if silence_start is None:
                        silence_start = time.time()

                    elif time.time() - silence_start > 0.8:
                        break

                time.sleep(0.05)

        duration = time.time() - start_time

        print(f"🛑 END SPEECH     DOA={angle}°")

        # ------------------------------------------
        # BUILD AUDIO
        # ------------------------------------------

        if not frames:
            print("⚠️ No audio captured")
            continue

        audio = np.concatenate(frames, axis=0)

        audio = audio.flatten()

        audio_int16 = (audio * 32767).astype(np.int16)

        # ------------------------------------------
        # SAVE WAV
        # ------------------------------------------

        with wave.open(WAV_FILE, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

        print(f"💾 Saved: {WAV_FILE}")
        print(f"⏱ Duration: {duration:.2f} sec")

        # ------------------------------------------
        # RUN WAKE WORD
        # ------------------------------------------

        print("\n🔍 Checking wake word...\n")

        wake_model.reset()

        peak_ezra = 0.0
        peak_hey = 0.0
        peak_ezzera = 0.0

        for i in range(0, len(audio_int16), 1024):

            chunk = audio_int16[i : i + 1024]

            if len(chunk) < 1024:
                break

            predictions = wake_model.predict(chunk)

            ezra_score = predictions.get("ezra", 0.0)
            hey_score = predictions.get("hey_ezra", 0.0)
            ezzera_score = predictions.get("ezzera", 0.0)

            peak_ezra = max(peak_ezra, ezra_score)
            peak_hey = max(peak_hey, hey_score)
            peak_ezzera = max(peak_ezzera, ezzera_score)

        print(f"Peak EZRA score:      {peak_ezra:.3f}")
        print(f"Peak HEY_EZRA score:  {peak_hey:.3f}")
        print(f"Peak EZZERA score:    {peak_ezzera:.3f}")

        peak = max(peak_ezra, peak_hey, peak_ezzera)

        if peak >= WAKE_THRESHOLD:

            if peak == peak_ezzera:
                print("\n🚀 WAKE DETECTED: EZZERA")

            elif peak == peak_hey:
                print("\n🚀 WAKE DETECTED: HEY EZRA")

            else:
                print("\n🚀 WAKE DETECTED: EZRA")

        else:
            print("\n❌ Not a wake word")

        print("\nWaiting for speech...\n")

except KeyboardInterrupt:
    print("\nStopping...")
