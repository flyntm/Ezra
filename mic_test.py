import sounddevice as sd
import scipy.io.wavfile as wav
import whisper

model = whisper.load_model("base")

fs = 16000
duration = 4

print("Recording...")
audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='float32')
sd.wait()

audio = audio.flatten()
wav.write("test.wav", fs, audio)

print("Transcribing...")
result = model.transcribe("test.wav", language="en")

print("You said:", result["text"])
