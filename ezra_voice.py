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

# Load API key
load_dotenv()
client = OpenAI()

# Load Whisper model
model = whisper.load_model("base")

duration = 4  # seconds


# 🔥 AUTO-DETECT MICROPHONE
def find_usb_mic():
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    lines = result.stdout.split("\n")

    for line in lines:
        if "USB" in line or "MIC" in line:
            # Example line:
            # card 3: MIC [USB MIC], device 0
            parts = line.split()
            card_index = parts[1].replace(":", "")
            return f"plughw:{card_index},0"

    return None


MIC_DEVICE = find_usb_mic()

if MIC_DEVICE is None:
    print("❌ No USB microphone found!")
    exit()

print(f"🎤 Using microphone: {MIC_DEVICE}")


def record_audio(filename="temp.wav"):
    print("\n🎤 Listening...")

    cmd = [
        "arecord",
        "-D", MIC_DEVICE,
        "-f", "S16_LE",
        "-r", "44100",
        "-d", str(duration),
        filename
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not os.path.exists(filename):
        print("❌ Recording failed")
        return False

    return True


def listen():
    success = record_audio()

    if not success:
        return None

    fs, audio = wav.read("temp.wav")

    # Convert to float
    audio = audio.astype(np.float32) / 32768.0

    # Stereo → mono if needed
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # RMS level
    rms = np.sqrt(np.mean(audio**2))
    print(f"Audio RMS level: {rms:.4f}")

    if rms < 0.02:
        print("...silence...")
        return None

    print("🧠 Transcribing...")

    # Resample to 16kHz
    audio_16k = scipy.signal.resample_poly(audio, 16000, fs)
    wav.write("temp.wav", 16000, audio_16k)

    result = model.transcribe("temp.wav", language="en")

    text = result["text"].strip()
    print(f"You said: {text}")

    return text


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


def speak(text):
    print(f"Ezra: {text}")
    os.system(f'espeak "{text}"')


def main():
    print("🤖 Ezra is ready! Speak clearly...\n")

    while True:
        user_input = listen()

        if user_input is None:
            time.sleep(0.5)
            continue

        if "quit" in user_input.lower():
            speak("Goodbye!")
            break

        response = ask_ezra(user_input)
        speak(response)

        time.sleep(0.5)


if __name__ == "__main__":
    main()