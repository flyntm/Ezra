import subprocess
import numpy as np
import scipy.io.wavfile as wav
import os
from faster_whisper import WhisperModel
from openai import OpenAI
from dotenv import load_dotenv
import signal
import sys

# 🔑 Load API key
load_dotenv()
client = OpenAI()

# 🧠 Whisper model (higher accuracy)
model = WhisperModel("medium", compute_type="int8")

# 🎤 Auto-detect USB mic
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

# ⚙️ Tuned for your mic
CHUNK_DURATION = 1
THRESHOLD = 0.025
SILENCE_LIMIT = 3
MIN_AUDIO_LENGTH = 2.5

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

# 🎤 Record chunk (interruptible)
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

# 📥 Load + clean audio
def get_audio():
    fs, audio = wav.read("chunk.wav")
    audio = audio.astype(np.float32) / 32768.0

    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # 🔥 Light noise filter (don’t overdo it)
    audio[np.abs(audio) < 0.01] = 0

    # 🔥 Normalize + boost
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val

    audio = audio * 1.5
    audio = np.clip(audio, -1.0, 1.0)

    return audio

# 🎤 Listen loop
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

        if rms > THRESHOLD:
            speaking = True
            silence_counter = 0
            recording.extend(audio)

        elif speaking:
            recording.extend(audio)
            silence_counter += 1

            if silence_counter >= SILENCE_LIMIT:
                # small tail capture
                recording.extend(audio)
                break

    # Ignore too-short recordings
    if len(recording) < 16000 * MIN_AUDIO_LENGTH:
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

# 🤖 Ask AI
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

# 🔁 Main loop
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