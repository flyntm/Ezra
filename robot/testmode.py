# testmode.py — keyboard-driven manual test mode (smooth everywhere)

import sys
import termios
import tty
import time
import board
import neopixel
from robot import servos
from robot import eyes
from robot import eyelids

# Neopixel setup matching the working test_gpio13.py script.
LED_COUNT = 8
LED_PIN = board.D13
LED_BRIGHTNESS = 0.2
LED_ORDER = neopixel.GRB

# Track current incremental angles
eye_h = 90
eye_v = 90

pixels = None
neopixel_ready = False

def init_neopixel(silent=False):
    global pixels, neopixel_ready

    if neopixel_ready:
        clear_neopixel(silent=True)
        return True

    try:
        if not silent:
            print("[testmode] Initializing Neopixel on GPIO13...")
        pixels = neopixel.NeoPixel(
            LED_PIN,
            LED_COUNT,
            brightness=LED_BRIGHTNESS,
            auto_write=False,
            pixel_order=LED_ORDER,
        )
        neopixel_ready = True
        clear_neopixel(silent=True)
        if not silent:
            print("[testmode] Neopixel initialized successfully on GPIO13")
            print("[testmode] LEDs initialized OFF")
        return True
    except Exception as e:
        if not silent:
            print(f"[testmode] Neopixel initialization FAILED: {e}")
            print(f"[testmode] Error type: {type(e).__name__}")
            print("[testmode] Check: Is GPIO13 correctly wired to LED DIN?")
        pixels = None
        neopixel_ready = False
        return False


def pixels_show():
    if pixels is not None:
        pixels.show()


def clear_neopixel(silent=False):
    if not neopixel_ready:
        if not silent:
            print("[testmode] ERROR: Neopixel not available")
        return False

    try:
        pixels.fill((0, 0, 0))
        pixels_show()
        if not silent:
            print("[testmode] All LEDs: OFF")
        return True
    except Exception as e:
        if not silent:
            print(f"[testmode] ERROR turning off: {e}")
        return False


# ---------------------------------------------------------
# Keyboard input
# ---------------------------------------------------------
def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------
# Apply incremental angles (smooth)
# ---------------------------------------------------------
def apply_eye_angles():
    eyes.gaze_smooth(eye_h, eye_v, steps=12, duration=0.08)


# ---------------------------------------------------------
# Fixed-position directional tests (smooth)
# ---------------------------------------------------------
def eyes_test_up():
    global eye_v
    eye_v = 60
    eyes.gaze_smooth(eye_h, eye_v)

def eyes_test_down():
    global eye_v
    eye_v = 120
    eyes.gaze_smooth(eye_h, eye_v)

def eyes_test_left():
    global eye_h
    eye_h = 60
    eyes.gaze_smooth(eye_h, eye_v)

def eyes_test_right():
    global eye_h
    eye_h = 120
    eyes.gaze_smooth(eye_h, eye_v)


# ---------------------------------------------------------
# Multi-servo diagonal tests (smooth)
# ---------------------------------------------------------
def look_up_right():
    eyes.gaze_smooth(120, 60)

def look_down_left():
    eyes.gaze_smooth(60, 120)


# ---------------------------------------------------------
# Neopixel (Mouth) Tests
# ---------------------------------------------------------
def neopixel_all_red():
    if not neopixel_ready:
        print("[testmode] ERROR: Neopixel not available")
        return
    try:
        pixels.fill((255, 0, 0))
        pixels_show()
        print("[testmode] All LEDs: RED")
    except Exception as e:
        print(f"[testmode] ERROR setting red: {e}")

def neopixel_all_green():
    if not neopixel_ready:
        print("[testmode] ERROR: Neopixel not available")
        return
    try:
        pixels.fill((0, 255, 0))
        pixels_show()
        print("[testmode] All LEDs: GREEN")
    except Exception as e:
        print(f"[testmode] ERROR setting green: {e}")

def neopixel_all_blue():
    if not neopixel_ready:
        print("[testmode] ERROR: Neopixel not available")
        return
    try:
        pixels.fill((0, 0, 255))
        pixels_show()
        print("[testmode] All LEDs: BLUE")
    except Exception as e:
        print(f"[testmode] ERROR setting blue: {e}")

def neopixel_all_white():
    if not neopixel_ready:
        print("[testmode] ERROR: Neopixel not available")
        return
    try:
        pixels.fill((255, 255, 255))
        pixels_show()
        print("[testmode] All LEDs: WHITE")
    except Exception as e:
        print(f"[testmode] ERROR setting white: {e}")

def neopixel_off():
    clear_neopixel()

def neopixel_cycle():
    """Cycle through all LEDs one at a time"""
    if not neopixel_ready:
        return
    for i in range(8):
        pixels.fill((0, 0, 0))
        pixels[i] = (255, 100, 0)  # Orange
        pixels_show()
        print(f"[testmode] LED {i} lit")
        time.sleep(0.2)
    pixels.fill((0, 0, 0))
    pixels_show()

def neopixel_rainbow():
    """Rainbow animation"""
    if not neopixel_ready:
        return
    colors = [
        (255, 0, 0),      # Red
        (255, 127, 0),    # Orange
        (255, 255, 0),    # Yellow
        (0, 255, 0),      # Green
        (0, 0, 255),      # Blue
        (75, 0, 130),     # Indigo
        (148, 0, 211),    # Violet
        (255, 255, 255),  # White
    ]
    for i, color in enumerate(colors):
        pixels[i] = color
    pixels_show()
    print("[testmode] Rainbow pattern")

def neopixel_pulse():
    """Pulse effect"""
    if not neopixel_ready:
        return
    print("[testmode] Pulsing white...")
    for brightness in range(0, 11):
        level = int(255 * brightness / 10)
        pixels.fill((level, level, level))
        pixels_show()
        time.sleep(0.1)
    for brightness in range(10, -1, -1):
        level = int(255 * brightness / 10)
        pixels.fill((level, level, level))
        pixels_show()
        time.sleep(0.1)
    pixels.fill((0, 0, 0))
    pixels_show()


# ---------------------------------------------------------
# Main Test Mode
# ---------------------------------------------------------
def run():
    global eye_h, eye_v

    print("\n=== TEST MODE (Smooth Motion) ===")
    print("Incremental Controls (smooth):")
    print("  A = eyes left")
    print("  D = eyes right")
    print("  W = eyes up")
    print("  S = eyes down")
    print("  C = center eyes")
    print("")
    print("Fixed Test Positions (smooth):")
    print("  F = eyes left")
    print("  H = eyes right")
    print("  T = eyes up")
    print("  G = eyes down")
    print("")
    print("Diagonal Multi-Servo Tests (smooth):")
    print("  U = look up-right")
    print("  N = look down-left")
    print("")
    print("Eyelids:")
    print("  P = wide open lids")
    print("  O = open lids")
    print("  B = close lids")
    print("  K = blink")
    print("")
    print("Neopixel (Mouth):")
    print("  R = all red")
    print("  E = all green")
    print("  L = all blue")
    print("  M = all white")
    print("  X = all off")
    print("  Y = cycle through LEDs")
    print("  V = rainbow pattern")
    print("  Z = pulse effect")
    print("")
    print("Info:")
    print("  I = show angles")
    print("  Q = quit\n")

    servos.init()
    eyes.init()
    eyelids.init()
    eyes.center()
    eyelids.open_lids()

    init_neopixel()

    if neopixel_ready:
        print("[testmode] Neopixel initialized OK (GPIO13, 8 LEDs)")
    else:
        print("[testmode] WARNING: Neopixel not initialized - check GPIO13 connection")

    while True:
        k = get_key()

        if k in ("q", "Q"):
            print("\nExiting test mode.")
            break

        # Incremental movement (smooth)
        if k in ("a", "A"):
            eye_h = max(0, eye_h - 3)
            apply_eye_angles()

        elif k in ("d", "D"):
            eye_h = min(180, eye_h + 3)
            apply_eye_angles()

        elif k in ("w", "W"):
            eye_v = max(0, eye_v - 3)
            apply_eye_angles()

        elif k in ("s", "S"):
            eye_v = min(180, eye_v + 3)
            apply_eye_angles()

        elif k in ("c", "C"):
            eye_h = 90
            eye_v = 90
            apply_eye_angles()

        # Fixed-position directional tests (smooth)
        elif k in ("t", "T"):
            eyes_test_up()

        elif k in ("g", "G"):
            eyes_test_down()

        elif k in ("f", "F"):
            eyes_test_left()

        elif k in ("h", "H"):
            eyes_test_right()

        # Multi-servo diagonal tests (smooth)
        elif k in ("u", "U"):
            look_up_right()

        elif k in ("n", "N"):
            look_down_left()

        # Eyelids
        elif k in ("p", "P"):
            eyelids.wide_open_lids()

        elif k in ("o", "O"):
            eyelids.open_lids()

        elif k in ("b", "B"):
            eyelids.close_lids()

        elif k in ("k", "K"):
            eyelids.close_lids()
            time.sleep(0.15)
            eyelids.open_lids()

        # Neopixel tests
        elif k in ("r", "R"):
            neopixel_all_red()

        elif k in ("e", "E"):
            neopixel_all_green()

        elif k in ("l", "L"):
            neopixel_all_blue()

        elif k in ("m", "M"):
            neopixel_all_white()

        elif k in ("x", "X"):
            neopixel_off()

        elif k in ("y", "Y"):
            neopixel_cycle()

        elif k in ("v", "V"):
            neopixel_rainbow()

        elif k in ("z", "Z"):
            neopixel_pulse()

        # Info
        elif k in ("i", "I"):
            print(f"\nEye angles: H={eye_h}, V={eye_v}")

        time.sleep(0.01)


if __name__ == "__main__":
    run()
