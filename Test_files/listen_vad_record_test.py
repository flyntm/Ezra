import sys
import time
import queue
import wave

import numpy as np
import sounddevice as sd
import usb.core
from faster_whisper import WhisperModel
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv("/home/flyntm/projects/ezra/.env")

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1024

WAV_FILE = "/tmp/vad_test.wav"

client = OpenAI()

# --------------------------------------------------
# LOAD WHISPER
# --------------------------------------------------

print("🧠 Loading Whisper model...")
model = WhisperModel("base.en", device="cpu", compute_type="int8")
print("✅ Whisper loaded")

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
    audio_queue.put(indata.copy())


# --------------------------------------------------
# MAIN LOOP
# --------------------------------------------------

print("Waiting for speech...\n")

try:

    while True:

        # ------------------------------------------
        # WAIT FOR SPEECH
        # ------------------------------------------

        while True:
            doa = mic.read("DOA_VALUE")

            speech = bool(doa[1])

            if speech:
                angle = doa[0]
                print(f"\n🎤 START SPEECH   DOA={angle}°")
                break

            time.sleep(0.05)

        # ------------------------------------------
        # RECORD
        # ------------------------------------------

        frames = []

        start_time = time.time()
        silence_start = None

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=audio_callback,
            blocksize=BLOCKSIZE,
        ):

            while True:

                while not audio_queue.empty():
                    frames.append(audio_queue.get())

                doa = mic.read("DOA_VALUE")
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

        angle = doa[0]

        print(f"🛑 END SPEECH     DOA={angle}°")

        # ------------------------------------------
        # SAVE WAV
        # ------------------------------------------

        audio = np.concatenate(frames, axis=0)

        audio_int16 = (audio * 32767).astype(np.int16)

        with wave.open(WAV_FILE, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_int16.tobytes())

        print(f"💾 Saved: {WAV_FILE}")
        print(f"⏱ Duration: {duration:.2f} sec")

        # ------------------------------------------
        # WHISPER
        # ------------------------------------------

        print("📝 Transcribing...\n")

        segments, _ = model.transcribe(WAV_FILE)

        text = " ".join(segment.text for segment in segments).strip()

        if not text:
            print("⚠️ Nothing detected\n")
            continue

        print("You said:")
        print(text)

        # ------------------------------------------
        # CHATGPT
        # ------------------------------------------

        print("\n🤖 Thinking...\n")

        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": "You are Ezra, a friendly desktop robot.",
                },
                {"role": "user", "content": text},
            ],
        )

        answer = response.choices[0].message.content

        print("Ezra:")
        print(answer)
        print()

        print("Waiting for speech...\n")

except KeyboardInterrupt:
    print("\nStopping...")
