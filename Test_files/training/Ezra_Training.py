import os
import time
import random
import threading
import numpy as np
import sounddevice as sd
import wave

# ==========================================
# OPTIONAL SERVO SUPPORT
# ==========================================
ENABLE_SERVOS = True

if ENABLE_SERVOS:
    from adafruit_pca9685 import PCA9685
    from board import SCL, SDA
    import busio
    from adafruit_motor import servo

    # ==========================================
    # PCA9685 SETUP
    # ==========================================
    i2c = busio.I2C(SCL, SDA)
    pca = PCA9685(i2c)
    pca.frequency = 50

    # CHANGE THESE TO YOUR CHANNELS
    SERVO_1_CHANNEL = 0
    SERVO_2_CHANNEL = 1

    servo1 = servo.Servo(pca.channels[SERVO_1_CHANNEL])
    servo2 = servo.Servo(pca.channels[SERVO_2_CHANNEL])

    servo_running = False

    # ==========================================
    # SERVO MOTION LOOP
    # ==========================================
    def servo_motion_loop():
        global servo_running

        while servo_running:
            angle1 = random.randint(20, 160)
            angle2 = random.randint(20, 160)

            servo1.angle = angle1
            servo2.angle = angle2

            time.sleep(random.uniform(0.05, 0.2))


# ==========================================
# CONFIG
# ==========================================
SAMPLE_RATE = 16000
INPUT_DEVICE = None
TRAINING_DIR = "training"
NUM_FILES = 10

# ==========================================
# SETUP
# ==========================================
if not os.path.exists(TRAINING_DIR):
    os.makedirs(TRAINING_DIR)
    print(f"📁 Created directory: {TRAINING_DIR}")


# ==========================================
# PLAYBACK
# ==========================================
def play_clip(filename):
    filepath = os.path.join(TRAINING_DIR, filename)

    if not os.path.exists(filepath):
        print(f"❌ Missing: {filename}")
        return

    print(f"🔊 Playing: {filename}")

    with wave.open(filepath, "rb") as wf:
        audio = wf.readframes(wf.getnframes())
        audio_np = np.frombuffer(audio, dtype=np.int16)

        sd.play(audio_np, samplerate=wf.getframerate())
        sd.wait()


def playback_all(start_index):
    print("\n🔊 Playing all recordings...\n")

    for i in range(NUM_FILES):
        filename = f"ezra_{start_index + i:03d}.wav"
        play_clip(filename)

    print("\n✅ Playback complete")


# ==========================================
# RECORD FUNCTION
# ==========================================
def record_clip(filename, duration, move_servos):
    filepath = os.path.join(TRAINING_DIR, filename)

    print(f"\n🔄 Warming up microphone...")

    frames = []

    def callback(indata, frames_count, time_info, status):
        if status:
            print("⚠️", status)

        frames.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        device=INPUT_DEVICE,
        callback=callback,
    ):

        # Warmup
        time.sleep(0.5)

        print(f"\n🎤 Recording: {filename}")

        for c in range(3, 0, -1):
            print(c)
            time.sleep(0.4)

        print("🎙️ Speak now!")

        # Remove countdown audio
        frames.clear()

        # ==========================================
        # START SERVO MOTION
        # ==========================================
        if ENABLE_SERVOS and move_servos:
            global servo_running

            servo_running = True

            servo_thread = threading.Thread(target=servo_motion_loop)

            servo_thread.start()

        # ==========================================
        # RECORD
        # ==========================================
        time.sleep(duration)

        # ==========================================
        # STOP SERVOS
        # ==========================================
        if ENABLE_SERVOS and move_servos:
            servo_running = False
            servo_thread.join()

    # ==========================================
    # VALIDATE AUDIO
    # ==========================================
    if len(frames) == 0:
        print("⚠️ No audio captured — retrying...")
        return record_clip(filename, duration, move_servos)

    audio = np.concatenate(frames)

    rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))

    print(f"🔎 RMS: {rms:.2f}")

    if rms < 50:
        print("⚠️ Too quiet — retrying...")
        return record_clip(filename, duration, move_servos)

    # ==========================================
    # SAVE
    # ==========================================
    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    print(f"✅ Saved: {filepath}")


# ==========================================
# RERECORD LOOP
# ==========================================
def rerecord_loop(start_index, duration, move_servos):
    while True:
        choice = input(
            "\n✏️ Enter file number to rerecord "
            "(e.g. 021) or press ENTER to finish: "
        ).strip()

        if choice == "":
            break

        try:
            num = int(choice)

            filename = f"ezra_{num:03d}.wav"

            print(f"\n🔁 Re-recording {filename}")

            record_clip(filename, duration, move_servos)

        except ValueError:
            print("❌ Invalid number")


# ==========================================
# MAIN
# ==========================================
mode = (
    input("🎯 Select mode: " "(R)ecord new batch or (E)dit existing? ").strip().lower()
)

start_index = int(input("🔢 Enter starting number (e.g. 21): "))

move_servos = input("🤖 Move servos during recording? (y/n): ").strip().lower() == "y"

# ==========================================
# RECORD MODE
# ==========================================
if mode == "r":

    duration = float(input("⏱️ Enter recording duration (seconds): "))

    print("\n🎤 Recording batch...")

    for i in range(NUM_FILES):
        filename = f"ezra_{start_index + i:03d}.wav"

        record_clip(filename, duration, move_servos)

    playback_all(start_index)

    rerecord_loop(start_index, duration, move_servos)

# ==========================================
# EDIT MODE
# ==========================================
elif mode == "e":

    duration = 2.0

    playback_all(start_index)

    rerecord_loop(start_index, duration, move_servos)

else:
    print("❌ Invalid mode")
