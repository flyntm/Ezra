import os
import time
from config import *
from ezra_emotion import set_emotion

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

    set_emotion("normal_talking")
    time.sleep(0.05)

    os.system(f"aplay -D {SPEAKER_DEVICE} temp.wav > /dev/null 2>&1")

    set_emotion("listening")