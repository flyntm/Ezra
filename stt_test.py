from faster_whisper import WhisperModel
import time

AUDIO_FILE = "test.wav"  # use your recorded file

print("🧠 Loading model...")
model = WhisperModel("small.en", device="cpu", compute_type="int8")
print("✅ Ready\n")

while True:
    print("🧠 Transcribing...")

    segments, _ = model.transcribe(AUDIO_FILE, language="en", beam_size=1, best_of=1)

    text = " ".join([seg.text for seg in segments]).strip()

    print(f"➡️  {text}\n")

    time.sleep(2)
