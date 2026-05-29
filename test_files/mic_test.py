import sounddevice as sd
import scipy.io.wavfile as wav
import whisper
import numpy as np

# =========================
# CONFIG
# =========================
SAMPLE_RATE = 16000
DURATION = 4
GAIN = 4.0          # Adjust 3.0–6.0 depending on mic
DEVICE_INDEX = 3 # Set to an int if you want to force a device

# =========================
# LOAD MODEL
# =========================
print("🧠 Loading Whisper model...")
model = whisper.load_model("base")

# =========================
# OPTIONAL: SHOW DEVICES
# =========================
print("\n🎤 Available audio devices:")
print(sd.query_devices())

# =========================
# RECORD AUDIO
# =========================
print("\n🎙️ Recording...")

audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype='float32',
    device=DEVICE_INDEX
)

sd.wait()

# =========================
# PROCESS AUDIO
# =========================
audio = audio.flatten()

# Remove DC offset
audio = audio - np.mean(audio)

# Apply gain
audio = audio * GAIN

# Prevent clipping
audio = np.clip(audio, -1.0, 1.0)

# =========================
# ANALYZE SIGNAL
# =========================
rms = np.sqrt(np.mean(audio**2))
peak = np.max(np.abs(audio))

print(f"\n📊 RMS Level:  {rms:.4f}")
print(f"📊 Peak Level: {peak:.4f}")

# Level guidance
if rms < 0.02:
    print("⚠️  Very quiet — increase GAIN or move closer")
elif rms < 0.05:
    print("⚠️  A bit quiet — usable but could improve")
elif rms < 0.15:
    print("✅ Good level")
else:
    print("⚠️  Very loud — possible clipping")

# =========================
# SAVE AUDIO
# =========================
wav.write("test.wav", SAMPLE_RATE, audio)
print("💾 Saved to test.wav")

# =========================
# TRANSCRIBE
# =========================
print("\n🧠 Transcribing...")

result = model.transcribe(
    "test.wav",
    language="en",
    fp16=False  # avoids warning on CPU
)

print("\n🗣️ You said:", result["text"].strip())