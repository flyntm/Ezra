import sys

import usb.core

RESPEAKER_PYTHON_CONTROL_PATH = (
    "/home/flyntm/reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control"
)
RESPEAKER_VENDOR_ID = 0x2886


def create_respeaker_or_raise():
    """Return an initialized ReSpeaker control object or raise."""

    if RESPEAKER_PYTHON_CONTROL_PATH not in sys.path:
        sys.path.append(RESPEAKER_PYTHON_CONTROL_PATH)

    from xvf_host import ReSpeaker

    dev = usb.core.find(idVendor=RESPEAKER_VENDOR_ID)
    if not dev:
        raise RuntimeError("❌ ReSpeaker not found")

    return ReSpeaker(dev)
