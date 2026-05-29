import subprocess
import numpy as np
import scipy.io.wavfile as wav
import time

MIC_DEVICE = "plughw:3,0"
FS = 16000

def record(filename, seconds):
    print(f"\n🎙 Recording {seconds} seconds → {filename}")
    subprocess.run([
        "arecord",
        "-D", MIC_DEVICE,
        "-f", "S16_LE",
        "-r", str(FS),
        "-d", str(seconds),
        filename
    ])

def analyze(filename):
    fs, audio = wav.read(filename)

    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0

    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)

    # Remove DC offset
    audio = audio - np.mean(audio)

    rms = np.sqrt(np.mean(audio**2))
    peak = np.max(np.abs(audio))

    return rms, peak


print("\n🎤 AUDIO CALIBRATION TOOL")
print("----------------------------")

# --- Silence ---
print("\n👉 Get ready to stay quiet...")
time.sleep(2)

print("🔴 Recording silence NOW...")
record("silence.wav", 3)

silence_rms, silence_peak = analyze("silence.wav")

print("\n📊 Silence Results:")
print(f"RMS:  {silence_rms:.4f}")
print(f"Peak: {silence_peak:.4f}")


# --- Speech ---
print("\n👉 Get ready to speak...")
time.sleep(2)

print("🟢 Speak NOW (normal, loud, soft)...")
record("speech.wav", 10)

speech_rms, speech_peak = analyze("speech.wav")

print("\n📊 Speech Results:")
print(f"RMS:  {speech_rms:.4f}")
print(f"Peak: {speech_peak:.4f}")


# --- Interpretation ---
print("\n🎯 INTERPRETATION")
print("----------------------------")

ratio = speech_rms / (silence_rms + 1e-6)

print(f"Speech/Silence Ratio: {ratio:.2f}")

if ratio < 1.5:
    print("❌ Speech too close to noise → increase mic gain or speak closer")
elif ratio < 3:
    print("⚠️ Usable but not great → could improve gain")
else:
    print("✅ Good separation between speech and silence")

print("\n✅ Calibration complete!\n")