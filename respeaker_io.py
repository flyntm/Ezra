import subprocess
import sys
import threading
import time
import math

import usb.core

RESPEAKER_PYTHON_CONTROL_PATH = (
    "/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control"
)
RESPEAKER_VENDOR_ID = 0x2886
RESPEAKER_RECOGNITION_CHANNEL = 0
RESPEAKER_LED_EFFECT_OFF = 0
RESPEAKER_LED_EFFECT_DOA = 4
RESPEAKER_LED_EFFECT_RING = 5
RESPEAKER_RING_LED_COUNT = 12
RESPEAKER_FRONT_LED_INDEX = 0
RESPEAKER_RING_INDEX_DIRECTION = 1
RESPEAKER_WAKE_LED_COLOR = 0x0000FF
RESPEAKER_RESET_COMMAND = ("sudo", "-n", "/usr/local/sbin/ezra-reset-respeaker")
RESPEAKER_RESET_COOLDOWN_SECONDS = 60.0

_reset_lock = threading.Lock()
_last_reset_at = float("-inf")


def select_respeaker_recognition_channel(audio):
    """Return the model-calibrated channel while preserving a mono column."""
    if getattr(audio, "ndim", 0) < 2 or audio.shape[1] <= RESPEAKER_RECOGNITION_CHANNEL:
        return audio.copy()
    channel = RESPEAKER_RECOGNITION_CHANNEL
    return audio[:, channel : channel + 1].copy()


def set_respeaker_listening_led(mic, enabled):
    """Show direction of arrival while listening; turn the ring off otherwise."""
    effect = RESPEAKER_LED_EFFECT_DOA if enabled else RESPEAKER_LED_EFFECT_OFF
    mic.write("LED_EFFECT", [effect])


def set_respeaker_wake_indicator(mic, bearing_degrees):
    """Show three blue LEDs centered on the signed wake bearing."""
    sector = math.floor((float(bearing_degrees) + 15.0) / 30.0)
    center = (
        RESPEAKER_FRONT_LED_INDEX + RESPEAKER_RING_INDEX_DIRECTION * sector
    ) % RESPEAKER_RING_LED_COUNT
    colors = [0] * RESPEAKER_RING_LED_COUNT
    colors[(center - 1) % RESPEAKER_RING_LED_COUNT] = RESPEAKER_WAKE_LED_COLOR
    colors[center] = RESPEAKER_WAKE_LED_COLOR
    colors[(center + 1) % RESPEAKER_RING_LED_COUNT] = RESPEAKER_WAKE_LED_COLOR
    mic.write("LED_RING_COLOR", colors)
    mic.write("LED_EFFECT", [RESPEAKER_LED_EFFECT_RING])


def reset_respeaker_usb():
    """Ask the narrowly privileged helper to re-enumerate the ReSpeaker."""
    global _last_reset_at
    with _reset_lock:
        now = time.monotonic()
        if now - _last_reset_at < RESPEAKER_RESET_COOLDOWN_SECONDS:
            return False
        _last_reset_at = now
        try:
            result = subprocess.run(
                RESPEAKER_RESET_COMMAND,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"⚠️ Automatic ReSpeaker USB reset failed: {exc}")
            return False
        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()
            print(
                "⚠️ Automatic ReSpeaker USB reset failed"
                + (f": {details}" if details else "")
            )
            return False
        print("♻️ ReSpeaker USB port reset; waiting for it to reconnect")
        time.sleep(3)
        return True


def create_respeaker_or_raise(recover=False, reset_first=False):
    """Return an initialized ReSpeaker control object or raise."""

    if RESPEAKER_PYTHON_CONTROL_PATH not in sys.path:
        sys.path.append(RESPEAKER_PYTHON_CONTROL_PATH)

    from xvf_host import ReSpeaker

    if recover and reset_first:
        reset_respeaker_usb()

    dev = usb.core.find(idVendor=RESPEAKER_VENDOR_ID)
    if not dev and recover:
        reset_respeaker_usb()
        dev = usb.core.find(idVendor=RESPEAKER_VENDOR_ID)
    if not dev:
        raise RuntimeError("❌ ReSpeaker not found")

    return ReSpeaker(dev)
