import sounddevice as sd
import soundfile as sf
import time

SAMPLE_RATE = 48000
RECORD_SECONDS = 5

print("Opening stream...")

with sd.InputStream(
    device=0, samplerate=SAMPLE_RATE, channels=1, dtype="float32"
) as stream:

    print("Stream open")
    time.sleep(10)

    print("Recording now...")

    audio, overflowed = stream.read(SAMPLE_RATE * RECORD_SECONDS)

    print("Overflow:", overflowed)

sf.write("stream_test.wav", audio, SAMPLE_RATE)

print("Saved stream_test.wav")
