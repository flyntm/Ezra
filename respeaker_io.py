import subprocess
import sys
import threading
import time

import usb.core

RESPEAKER_PYTHON_CONTROL_PATH = (
    "/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control"
)
RESPEAKER_VENDOR_ID = 0x2886
RESPEAKER_RECOGNITION_CHANNEL = 0
RESPEAKER_RESET_COMMAND = ("sudo", "-n", "/usr/local/sbin/ezra-reset-respeaker")
RESPEAKER_RESET_COOLDOWN_SECONDS = 60.0

_reset_lock = threading.Lock()
_last_reset_at = float("-inf")


def select_respeaker_recognition_channel(audio):
    """Return the model-calibrated channel while preserving a mono column."""
    if (
        getattr(audio, "ndim", 0) < 2
        or audio.shape[1] <= RESPEAKER_RECOGNITION_CHANNEL
    ):
        return audio.copy()
    channel = RESPEAKER_RECOGNITION_CHANNEL
    return audio[:, channel : channel + 1].copy()


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
