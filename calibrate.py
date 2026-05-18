import subprocess
import numpy as np
import scipy.io.wavfile as wav
import time
from datetime import datetime
from faster_whisper import WhisperModel
from config import *

# =========================
# SETUP
# =========================

model = WhisperModel(
    WHISPER_MODEL,
    device=WHISPER_DEVICE,
    compute_type=WHISPER_COMPUTE_TYPE,
)


# =========================
# RECORDING
# =========================
def record(filename, seconds):
    print(f"🎤 Recording {filename} ({seconds}s)...")
    print("▶️ Recording started — speak now")

    subprocess.run(
        [
            "arecord",
            "-D",
            MIC_DEVICE,
            "-f",
            AUDIO_FORMAT,
            "-r",
            str(SAMPLE_RATE),
            "-c",
            str(CHANNELS),
            "-d",
            str(seconds),
            "-t",
            "wav",
            filename,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def load_audio(filename):
    rate, data = wav.read(filename)
    audio = data.astype(np.float32) / 32768.0
    audio = audio - np.mean(audio)
    return audio


def compute_rms(audio):
    return np.sqrt(np.mean(audio**2))


# =========================
# TRANSCRIPTION
# =========================


def transcribe_file(filename):
    segments, _ = model.transcribe(filename, beam_size=1, temperature=0.0)
    return " ".join([s.text for s in segments]).strip()


# =========================
# CALIBRATION FLOW
# =========================

print("\n=== EZRA CALIBRATION ===\n")

input("👉 Stay SILENT (5 sec). Press Enter...")
record("silence.wav", 5)

input(
    "👉 Say: 'Ezra testing one two three. Please recognize speech clearly.'\nPress Enter..."
)
record("phrase1.wav", 7)

input("👉 Say: 'The quick brown fox jumps over the lazy dog.'\nPress Enter...")
record("phrase2.wav", 5)

input("👉 Say slowly: 'One... two... three... four... five...'\nPress Enter...")
record("numbers.wav", 5)

# =========================
# ANALYSIS
# =========================

silence = load_audio("silence.wav")
p1 = load_audio("phrase1.wav")
p2 = load_audio("phrase2.wav")
nums = load_audio("numbers.wav")

noise_floor = compute_rms(silence)

speech_rms_values = [
    compute_rms(p1),
    compute_rms(p2),
    compute_rms(nums),
]

speech_avg = np.mean(speech_rms_values)

speech_peak = max(
    np.max(np.abs(p1)),
    np.max(np.abs(p2)),
    np.max(np.abs(nums)),
)

snr = speech_avg - noise_floor

# =========================
# COMPUTE SETTINGS
# =========================

TARGET_SPEECH = 0.20

# Safe gain clamp
gain = min(max(TARGET_SPEECH / speech_avg, 2.0), 8.0)

start_offset = (speech_avg - noise_floor) * 0.30
silence_offset = (speech_avg - noise_floor) * 0.18

silence_limit = int(0.8 / CHUNK_DURATION)

# =========================
# OUTPUT RESULTS
# =========================

print("\n=== RESULTS ===")
print(f"Noise floor: {noise_floor:.3f}")
print(f"Speech avg:  {speech_avg:.3f}")
print(f"Speech peak: {speech_peak:.3f}")
print(f"SNR:         {snr:.3f}")

print("\n=== SUGGESTED CONFIG ===")
print(f"GAIN = {gain:.2f}")
print(f"START_THRESHOLD_OFFSET = {start_offset:.3f}")
print(f"SILENCE_THRESHOLD_OFFSET = {silence_offset:.3f}")
print(f"SILENCE_LIMIT = {silence_limit}")

# =========================
# TRANSCRIPTION
# =========================

print("\n=== TRANSCRIPTIONS ===")

for f in ["phrase1.wav", "phrase2.wav", "numbers.wav"]:
    text = transcribe_file(f)
    print(f"{f}: {text}")

# =========================
# SAVE CONFIG
# =========================

save = input("\nSave config? (y/n): ").lower()

if save == "y":
    name = input("Enter config name (e.g. snowball): ")
    desc = input("Enter mic description: ")

    new_file = f"config_{name}.py"

    with open("config.py", "r") as base:
        lines = base.readlines()

    def replace(line, key, value):
        if line.strip().startswith(key):
            return f"{key} = {value}\n"
        return line

    updated = []
    for line in lines:
        line = replace(line, "GAIN", f"{gain:.2f}")
        line = replace(line, "START_THRESHOLD_OFFSET", f"{start_offset:.3f}")
        line = replace(line, "SILENCE_THRESHOLD_OFFSET", f"{silence_offset:.3f}")
        line = replace(line, "SILENCE_LIMIT", silence_limit)
        updated.append(line)

    header = f"""# =========================================
# AUTO-GENERATED CONFIG
# Mic: {desc}
# Date: {datetime.now()}
# =========================================

# Measured:
# noise_floor = {noise_floor:.3f}
# speech_avg  = {speech_avg:.3f}
# speech_peak = {speech_peak:.3f}
# SNR         = {snr:.3f}

"""

    with open(new_file, "w") as f:
        f.write(header)
        f.writelines(updated)

    print(f"\n✅ Saved: {new_file}")
