import sys
import time
import usb.core

# ReSpeaker SDK location
sys.path.append("/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control")

from xvf_host import ReSpeaker


def main():

    dev = usb.core.find(idVendor=0x2886)

    if not dev:
        print("❌ ReSpeaker not found")
        return

    mic = ReSpeaker(dev)

    print("✅ ReSpeaker Connected")
    print("Press Ctrl+C to stop")
    print()

    while True:

        try:
            doa = mic.read("DOA_VALUE")
            energy = mic.read("AEC_SPENERGY_VALUES")

            angle = doa[0]
            speech = bool(doa[1])

            energy_max = max(energy)

            print(
                f"Speech: {'YES' if speech else 'NO '}   "
                f"DOA: {angle:3d}°   "
                f"Energy Max: {energy_max:,.0f}"
            )
            
            energy_max = max(energy)

            print(
                f"Speech: {'YES' if speech else 'NO '}   "
                f"DOA: {angle:3d}°   "
                f"Energy Max: {energy_max:,.0f}"
            )

            time.sleep(0.25)

        except KeyboardInterrupt:
            print("\nStopping...")
            break

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

    try:
        mic.close()
    except:
        pass


if __name__ == "__main__":
    main()
