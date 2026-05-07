import os
import sys
import signal
import contextlib
import subprocess
import numpy as np
import scipy.io.wavfile as wav

from dotenv import load_dotenv
from faster_whisper import WhisperModel

from ezra_brain import ask_ezra
from ezra_emotion import set_emotion


# 🔥 FULL stderr suppression
@contextlib.contextmanager
def suppress_stderr_fully():

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr_fd = os.dup(2)

    os.dup2(devnull, 2)

    try:
        yield

    finally:
        os.dup2(old_stderr_fd, 2)
        os.close(devnull)
        os.close(old_stderr_fd)


print("🚀 Starting Ezra...")

load_dotenv()

print("🧠 Loading Whisper model...")

with suppress_stderr_fully():

    model = WhisperModel(
        "base",
        device="cpu",
        compute_type="int8"
    )

print("✅ Model loaded")


# 🎤 Audio Settings
MIC_DEVICE = "plughw:3,0"

CHUNK_DURATION = 1

START_THRESHOLD = 0.07
SILENCE_THRESHOLD = 0.03

SILENCE_LIMIT = 2
MIN_AUDIO_LENGTH = 1.2


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

    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


# 🎤 Record chunk
def record_chunk():

    global current_proc

    current_proc = subprocess.Popen(
        [
            "arecord",
            "-D", MIC_DEVICE,
            "-f", "S16_LE",
            "-r", "16000",
            "-d", str(CHUNK_DURATION),
            "chunk.wav"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    current_proc.wait()
    current_proc = None


# 📥 Read audio safely
def get_audio():

    try:
        fs, audio = wav.read("chunk.wav")

    except Exception:
        print("⚠️ Bad audio chunk")
        return None

    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0

    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # Remove DC offset
    audio = audio - np.mean(audio)

    return audio


# 🎤 Listen for speech
def listen():

    print("🎤 Listening...")

    recording = []
    speaking = False

    silence_counter = 0
    speech_chunks = 0

    while True:

        record_chunk()

        audio = get_audio()

        if audio is None:
            continue

        rms = np.sqrt(np.mean(audio**2))

        print(f"Level: {rms:.3f}")

        # Speech start
        if not speaking and rms > START_THRESHOLD:

            speaking = True
            print("🟢 Speech detected")

        if speaking:

            recording.extend(audio)
            speech_chunks += 1

            # Silence detection
            if rms < SILENCE_THRESHOLD:
                silence_counter += 1
            else:
                silence_counter = 0

            # Stop recording
            if silence_counter >= SILENCE_LIMIT and speech_chunks > 3:

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

    with suppress_stderr_fully():

        segments, _ = model.transcribe(
            "temp.wav",
            language="en",
            beam_size=5,
            vad_filter=True
        )

    text = " ".join([seg.text for seg in segments]).strip()

    print(f"You said: {text}")

    return text


# 🔊 Piper speech
def speak(text):

    print(f"Ezra: {text}")

    cmd = (
        f'echo "{text}" | '
        f'~/projects/piper_tts/piper '
        f'--model ~/projects/piper_tts/en_US-lessac-medium.onnx '
        f'--output_file temp.wav '
        f'> /dev/null 2>&1'
    )

    os.system(cmd)

    os.system(
        "aplay -D plughw:2,0 temp.wav > /dev/null 2>&1"
    )


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

        # 🧠 Ask brain
        result = ask_ezra(text)

        emotion = result["emotion"]
        response = result["response"]

        # 👀 Trigger emotion
        set_emotion(emotion)

        # 🔊 Speak
        speak(response)


# ▶️ Start
if __name__ == "__main__":
    main()