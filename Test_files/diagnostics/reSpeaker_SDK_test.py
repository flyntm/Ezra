import sys
import time
import math
import struct
import usb.core
import usb.util

# --------------------------------------------------
# ReSpeaker XVF3800 SDK Explorer
# --------------------------------------------------

PARAMETERS = {
    "VERSION": (48, 0, 3, "ro", "uint8"),
    "DOA_VALUE": (20, 18, 4, "ro", "uint16"),
    "AEC_AZIMUTH_VALUES": (33, 75, 16, "ro", "radians"),
    "AEC_SPENERGY_VALUES": (33, 80, 16, "ro", "float"),
    "AUDIO_MGR_SELECTED_AZIMUTHS": (35, 11, 8, "ro", "radians"),
}


class ReSpeaker:
    TIMEOUT = 100000

    def __init__(self, dev):
        self.dev = dev

    def read(self, name):
        data = PARAMETERS[name]

        resid = data[0]
        cmdid = 0x80 | data[1]
        length = data[2] + 1

        response = self.dev.ctrl_transfer(
            usb.util.CTRL_IN
            | usb.util.CTRL_TYPE_VENDOR
            | usb.util.CTRL_RECIPIENT_DEVICE,
            0,
            cmdid,
            resid,
            length,
            self.TIMEOUT,
        )

        raw = response.tobytes()

        if data[4] == "uint8":
            return response.tolist()

        elif data[4] == "uint16":
            return response.tolist()

        elif data[4] in ("float", "radians"):
            count = (length - 1) // 4
            fmt = "<" + ("f" * count)
            return struct.unpack(fmt, raw[1 : 1 + count * 4])

        return response.tolist()


def find():
    dev = usb.core.find(idVendor=0x2886, idProduct=0x001A)

    if dev is None:
        return None

    return ReSpeaker(dev)


def rad_to_deg(value):
    if math.isnan(value):
        return float("nan")

    return round(math.degrees(value), 1)


# --------------------------------------------------

dev = find()

if not dev:
    print("❌ ReSpeaker not found")
    sys.exit(1)

print("✅ ReSpeaker Connected")
print("Firmware:", dev.read("VERSION"))
print()

while True:
    try:
        doa = dev.read("DOA_VALUE")
        beam_angles = dev.read("AEC_AZIMUTH_VALUES")
        energy = dev.read("AEC_SPENERGY_VALUES")
        selected = dev.read("AUDIO_MGR_SELECTED_AZIMUTHS")

        # DOA format discovered from testing
        angle = doa[1]
        speech = doa[3]

        print("=" * 60)

        print(f"Speech: {'YES' if speech else 'NO '}   " f"DOA: {angle}°")

        print()
        print("Selected Azimuths")

        for i, value in enumerate(selected):
            print(f"  [{i}] {value:.3f} rad   " f"({rad_to_deg(value)}°)")

        print()
        print("Beam Azimuths")

        for i, value in enumerate(beam_angles):
            print(f"  [{i}] {value:.3f} rad   " f"({rad_to_deg(value)}°)")

        print()
        print("Speech Energy")

        for i, value in enumerate(energy):
            print(f"  [{i}] {value:,.0f}")

        time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopped.")
        break

    except Exception as e:
        print("Error:", e)
        time.sleep(1)
