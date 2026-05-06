import warnings
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")

import subprocess
import scipy.io.wavfile as wav
import scipy.signal
import numpy as np
import whisper
import os
import time
from openai import OpenAI
from dotenv import load_dotenv

# 🔑 Load API key
load_dotenv()
client = OpenAI()

# 🧠 Whisper model (good balance)
model = whisper.load_model("small")

# 🎤 Auto-detect USB mic
def find_usb_mic():
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    for line in result.stdout.split("\n"):
        if "USB" in line or "MIC" in line:
            card = line.split()[1].replace(":", "")
            return f"plughw:{card},0"
    return None

MIC_DEVICE = find_usb_mic()
if MIC_DEVICE is None:
    print("❌ No USB microphone found!")
    exit()

print(f"🎤 Using microphone: {MIC_DEVICE}")

# ⚙️ Tuning (based on your real audio data)
CHUNK_DURATION = 1
THRESHOLD = 0.035
SILENCE_LIMIT = 2
PRE_ROLL = 1.0
BOOST_AUDIO = True

# 🎤 Record one chunk
def record_chunk(filename):
    cmd = [
        "arecord",
        "-D", MIC_DEVICE,
        "-f", "S16_LE",
        "-r", "44100",
        "-d", str(CHUNK_DURATION),
        filename
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 📥 Load audio
def get_audio(filename):
    fs, audio = wav.read(filename)
    audio = audio.astype(np.float32) / 32768.0

    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    if BOOST_AUDIO:
        audio = audio * 1.5
        audio = np.clip(audio, -1.0, 1.0)

    return fs, audio

# 🎤 Continuous listening with improved pre-roll
def listen():
    print("🎤 Listening... (speak anytime)")

    recording = []
    pre_buffer = []
    silence_counter = 0
    speaking = False

    while True:
        record_chunk("chunk.wav")
        fs, audio = get_audio("chunk.wav")

        rms = np.sqrt(np.mean(audio**2))
        print(f"Level: {rms:.3f}")

        # Maintain rolling pre-buffer
        pre_buffer.extend(audio)
        max_samples = int(PRE_ROLL * fs)
        if len(pre_buffer) > max_samples:
            pre_buffer = pre_buffer[-max_samples:]

        # 🔥 Speech detection with clean pre-roll snapshot
        if rms > THRESHOLD:
            if not speaking:
                speaking = True
                silence_counter = 0

                # Capture clean pre-roll ONCE
                recording = pre_buffer.copy()
                # 🔥 Trim last chunk from pre-buffer to avoid duplication

                trim_samples = int(0.5 * fs)  # remove ~0.5 sec overlap
                if len(recording) > trim_samples:
                     recording = recording[:-trim_samples]

            recording.extend(audio)

        elif speaking:
            recording.extend(audio)

            # Smarter silence detection
            if rms < THRESHOLD * 0.6:
                silence_counter += 1
            else:
                silence_counter = 0

             # dynamic stop (faster + smarter)
            if silence_counter >= SILENCE_LIMIT or (speaking and rms < THRESHOLD * 0.5):
                break

    if len(recording) == 0:
        return None

    return np.array(recording), fs

# 🧠 Transcription
def transcribe(audio, fs):
    print("🧠 Transcribing...")

    audio_16k = scipy.signal.resample_poly(audio, 16000, fs)
    wav.write("temp.wav", 16000, audio_16k)

    result = model.transcribe("temp.wav", language="en")
    text = result["text"].strip()

    print(f"You said: {text}")
    return text

# 🤖 AI response
def ask_ezra(user_input):
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"""
You are Ezra, a friendly and wise robotic assistant.
Keep responses short and conversational.

User: {user_input}
"""
    )
    return response.output_text

# 🔊 Speak
def speak(text):
    print(f"Ezra: {text}")
    os.system(f'espeak "{text}"')

# 🔁 Main loop
def main():
    print("🤖 Ezra (final tuned) ready!\n")

    while True:
        result = listen()

        if result is None:
            continue

        audio, fs = result
        text = transcribe(audio, fs)

        if not text:
            continue

        if "quit" in text.lower():
            speak("Goodbye!")
            break

        response = ask_ezra(text)
        speak(response)

# ▶️ Run
if __name__ == "__main__":
    main()