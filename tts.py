import subprocess
import time
from config import *
from ezra_emotion import set_emotion
import state


def speak(text):
    if state.shutting_down:
        return

    print(f"Ezra: {text}")

    # Generate speech using Piper
    cmd = (
        f'echo "{text}" | '
        f"{PIPER_PATH} "
        f"--model {TTS_MODEL_PATH} "
        f"--output_file temp.wav"
    )

    subprocess.run(
        cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Talking animation
    set_emotion(EMOTION_TALKING)
    time.sleep(TTS_START_DELAY)

    # Play audio
    subprocess.run(
        ["aplay", "-D", SPEAKER_DEVICE, "temp.wav"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Return to listening
    set_emotion(EMOTION_LISTENING)
