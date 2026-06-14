import sys
import time
import numpy as np
import sounddevice as sd
import usb.core

# ReSpeaker SDK
sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")

from xvf_host import ReSpeaker

SAMPLE_RATE = 48000
BLOCK_SIZE = 1024


def main():

    dev = usb.core.find(idVendor=0x2886)

    if not dev:
        print("❌ ReSpeaker not found")
        return

    mic = ReSpeaker(dev)

    print("✅ ReSpeaker Connected")
    print("Comparing RMS vs XVF3800 Speech Detection")
    print("Press Ctrl+C to stop\n")

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
    ) as stream:

        while True:

            audio, overflowed = stream.read(BLOCK_SIZE)

            rms = np.sqrt(np.mean(audio**2))

            doa = mic.read("DOA_VALUE")

            angle = doa[0]
            speech = bool(doa[1])

            print(
                f"RMS: {rms:.4f}    "
                f"Speech: {'YES' if speech else 'NO '}    "
                f"DOA: {angle:3d}°"
            )

            time.sleep(0.10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopping...")
