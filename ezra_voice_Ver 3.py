import subprocess
import numpy as np
import scipy.io.wavfile as wav
import os
from faster_whisper import WhisperModel
from openai import OpenAI
from dotenv import load_dotenv
import signal
import sys

print("🚀 Starting Ezra...")

# 🔑 Load API key
load_dotenv()
client = OpenAI()

print("🧠 Loading Whisper model...")
model = WhisperModel("small", compute_type="int8")
print("✅ Model loaded")

# 🎤 Find mic
def find_usb_mic():
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    for line in result.stdout.split("\n"):
        if "USB" in line or "MIC" in line:
            card = line.split()[1].replace(":", "")
            return f"plughw:{card},0"
    return None

MIC_DEVICE = find_usb_mic()
if not MIC_DEVICE:
    print("❌ No microphone found")
    exit()

print(f"🎤 Using: {MIC_DEVICE}")

# ⚙️ Tuned settings for YOUR levels
CHUNK_DURATION = 1
START_THRESHOLD = 0.12
SILENCE_THRESHOLD = 0.05
SILENCE_LIMIT = 2
MIN_AUDIO_LENGTH = 1.5

current_proc = None

# 🛑 Clean shutdown
def signal_handler(sig, frame):
    global current_proc
    print("\n🛑 Shutting down Ezra...")

    if current_proc:
        try:
            current_proc.terminate()
        except:
            pass

    os.system("pkill espeak 2>/dev/null")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# 🎤 Record chunk
def record_chunk():
    global current_proc

    current_proc = subprocess.Popen([
        "arecord",
        "-D", MIC_DEVICE,
        "-f", "S16_LE",
        "-r", "16000",
        "-d", str(CHUNK_DURATION),
        "chunk.wav"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    current_proc.wait()
    current_proc = None

# 📥 Load audio
def get_audio():
    fs, audio = wav.read("chunk.wav")
    audio = audio.astype(np.float32) / 32768.0

    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # Light noise filter
    audio[np.abs(audio) < 0.01] = 0

    # Normalize
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val

    return audio

# 🎤 SIMPLIFIED + RELIABLE LISTEN
def listen():
    print("🎤 Listening...")

    recording = []
    speaking = False
    silence_counter = 0

    while True:
        record_chunk()
        audio = get_audio()

        rms = np.sqrt(np.mean(audio**2))
        print(f"Level: {rms:.3f}")

        # Detect start of speech
        if not speaking and rms > START_THRESHOLD:
            speaking = True
            print("🟢 Speech detected")

        # Once speaking, record everything
        if speaking:
            recording.extend(audio)

            # Detect silence
            if rms < SILENCE_THRESHOLD:
                silence_counter += 1
            else:
                silence_counter = 0

            # Stop after silence
            if silence_counter >= SILENCE_LIMIT:
                print("🔴 End of speech")
                break

    # Ignore too-short clips
    if len(recording) < 16000 * MIN_AUDIO_LENGTH:
        print("⚠️ Too short, ignoring")
        return None

    return np.array(recording)

# 🧠 Transcribe
def transcribe(audio):
    print("🧠 Transcribing...")

    wav.write("temp.wav", 16000, audio)

    segments, _ = model.transcribe(
        "temp.wav",
        language="en",
        beam_size=5,
        vad_filter=True
    )

    text = " ".join([seg.text for seg in segments]).strip()

    print(f"You said: {text}")
    return text

# 🤖 AI
def ask_ezra(text):
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=f"Keep responses short and conversational.\nUser: {text}"
    )
    return response.output_text

# 🔊 Speak
def speak(text):
    print(f"Ezra: {text}")
    os.system(f'espeak "{text}"')

# 🔁 Main
def main():
    print("🤖 Ezra ready! (Ctrl+C to exit)\n")

    while True:
        audio = listen()

        if audio is None:
            continue

        text = transcribe(audio)

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