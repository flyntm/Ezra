# calibration.py — 4 eye servos + 2 eyelid servos (arrow keys for all)

import json
import time
import sys
import termios
import tty
from robot import servos
from robot.constants import *

CAL_FILE = "calibration.txt"
JSON_CAL_FILE = "calibration.json"

DEFAULT_CAL = {
    "servos": {
        "left_h":  {"center": 90, "low": 60, "high": 120},
        "left_v":  {"center": 90, "low": 60, "high": 120},
        "right_h": {"center": 90, "low": 60, "high": 120},
        "right_v": {"center": 90, "low": 60, "high": 120},
        "lid_l":   {"center": 100, "low": 20, "high": 140, "wide_open": 140},
        "lid_r":   {"center": 100, "low": 20, "high": 140, "wide_open": 140}
    },
    "gaze": {
        "left_h":  {"left": 60, "center": 90, "right": 120},
        "right_h": {"left": 60, "center": 90, "right": 120},
        "left_v":  {"up": 60, "center": 90, "down": 120},
        "right_v": {"up": 60, "center": 90, "down": 120}
    }
}

SERVO_CHANNELS = {
    "left_h": CH_EYE_LEFT_H,
    "left_v": CH_EYE_LEFT_V,
    "right_h": CH_EYE_RIGHT_H,
    "right_v": CH_EYE_RIGHT_V,
    "lid_l": CH_LID_LEFT,
    "lid_r": CH_LID_RIGHT,
}

EYE_GAZE_LABELS = {
    "left_h": ("left", "right"),
    "right_h": ("left", "right"),
    "left_v": ("up", "down"),
    "right_v": ("up", "down"),
}

def _copy_default_cal():
    return json.loads(json.dumps(DEFAULT_CAL))

def _sync_servo_limits(cal, key):
    values = [cal["servos"][key]["center"]]

    if key in EYE_GAZE_LABELS:
        for label in EYE_GAZE_LABELS[key]:
            values.append(cal["gaze"][key][label])

    cal["servos"][key]["low"] = min(values)
    cal["servos"][key]["high"] = max(values)

def _normalize_cal(cal):
    merged = _copy_default_cal()

    for section, defaults in DEFAULT_CAL.items():
        if isinstance(cal.get(section), dict):
            for key, values in defaults.items():
                if isinstance(cal[section].get(key), dict):
                    merged[section][key].update(cal[section][key])

    for key in EYE_GAZE_LABELS:
        if "gaze" not in cal or key not in cal.get("gaze", {}):
            servo = merged["servos"][key]
            low_label, high_label = EYE_GAZE_LABELS[key]
            merged["gaze"][key] = {
                low_label: servo["low"],
                "center": servo["center"],
                high_label: servo["high"],
            }

        _sync_servo_limits(merged, key)

    return merged

def _load_txt_cal():
    values = {}

    try:
        with open(CAL_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line or "=" not in line:
                    continue

                channel, rest = line.split(":", 1)
                label, value = rest.split("=", 1)
                values[(int(channel), label)] = float(value)
    except:
        return None

    def value(channel, label, default):
        return values.get((channel, label), default)

    cal = _copy_default_cal()

    for key, channel in SERVO_CHANNELS.items():
        cal["servos"][key]["center"] = value(channel, "center", cal["servos"][key]["center"])

    cal["gaze"]["left_h"]["left"] = value(CH_EYE_LEFT_H, "left", cal["gaze"]["left_h"]["left"])
    cal["gaze"]["left_h"]["center"] = cal["servos"]["left_h"]["center"]
    cal["gaze"]["left_h"]["right"] = value(CH_EYE_LEFT_H, "right", cal["gaze"]["left_h"]["right"])

    cal["gaze"]["right_h"]["left"] = value(CH_EYE_RIGHT_H, "left", cal["gaze"]["right_h"]["left"])
    cal["gaze"]["right_h"]["center"] = cal["servos"]["right_h"]["center"]
    cal["gaze"]["right_h"]["right"] = value(CH_EYE_RIGHT_H, "right", cal["gaze"]["right_h"]["right"])

    cal["gaze"]["left_v"]["up"] = value(CH_EYE_LEFT_V, "up", cal["gaze"]["left_v"]["up"])
    cal["gaze"]["left_v"]["center"] = cal["servos"]["left_v"]["center"]
    cal["gaze"]["left_v"]["down"] = value(CH_EYE_LEFT_V, "down", cal["gaze"]["left_v"]["down"])

    cal["gaze"]["right_v"]["up"] = value(CH_EYE_RIGHT_V, "up", cal["gaze"]["right_v"]["up"])
    cal["gaze"]["right_v"]["center"] = cal["servos"]["right_v"]["center"]
    cal["gaze"]["right_v"]["down"] = value(CH_EYE_RIGHT_V, "down", cal["gaze"]["right_v"]["down"])

    cal["servos"]["lid_l"]["high"] = value(CH_LID_LEFT, "open", cal["servos"]["lid_l"]["high"])
    cal["servos"]["lid_l"]["wide_open"] = value(CH_LID_LEFT, "wide_open", cal["servos"]["lid_l"]["high"])
    cal["servos"]["lid_l"]["low"] = value(CH_LID_LEFT, "closed", cal["servos"]["lid_l"]["low"])
    cal["servos"]["lid_r"]["high"] = value(CH_LID_RIGHT, "open", cal["servos"]["lid_r"]["high"])
    cal["servos"]["lid_r"]["wide_open"] = value(CH_LID_RIGHT, "wide_open", cal["servos"]["lid_r"]["high"])
    cal["servos"]["lid_r"]["low"] = value(CH_LID_RIGHT, "closed", cal["servos"]["lid_r"]["low"])

    for key in EYE_GAZE_LABELS:
        _sync_servo_limits(cal, key)

    return cal

def _load_json_cal():
    try:
        with open(JSON_CAL_FILE, "r") as f:
            return _normalize_cal(json.load(f))
    except:
        return None

def load_cal():
    txt_cal = _load_txt_cal()
    if txt_cal:
        return txt_cal

    json_cal = _load_json_cal()
    if json_cal:
        return json_cal

    return _copy_default_cal()

def save_cal(cal):
    with open(CAL_FILE, "w") as f:
        for key, channel in SERVO_CHANNELS.items():
            f.write(f"{channel}:center={cal['servos'][key]['center']}\n")

            if key in ("left_h", "right_h"):
                f.write(f"{channel}:left={cal['gaze'][key]['left']}\n")
                f.write(f"{channel}:right={cal['gaze'][key]['right']}\n")
            elif key in ("left_v", "right_v"):
                f.write(f"{channel}:up={cal['gaze'][key]['up']}\n")
                f.write(f"{channel}:down={cal['gaze'][key]['down']}\n")
            elif key in ("lid_l", "lid_r"):
                f.write(f"{channel}:open={cal['servos'][key]['high']}\n")
                f.write(f"{channel}:wide_open={cal['servos'][key]['wide_open']}\n")
                f.write(f"{channel}:closed={cal['servos'][key]['low']}\n")

    print("\nSaved calibration.txt")

def _ensure_servos_initialized():
    if servos.pca is not None:
        return True
    return servos.init()

def _move_all_servos_to_centers(cal):
    angles = {}

    for key, channel in SERVO_CHANNELS.items():
        angle = cal["servos"][key]["center"]
        servos.set_servo_angle(channel, angle)
        angles[key] = angle
        time.sleep(0.02)

    return angles

def center_all_servos_natural():
    """Move all servos to their built-in neutral centers, ignoring saved calibration."""
    if not _ensure_servos_initialized():
        return None

    return _move_all_servos_to_centers(_copy_default_cal())

def center_all_servos_from_calibration():
    """Reload calibration from disk and move all servos to the saved center positions."""
    if not _ensure_servos_initialized():
        return None

    return _move_all_servos_to_centers(load_cal())

def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch += sys.stdin.read(2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def calibrate():
    cal = load_cal()
    servos.init()

    servolist = [
        ("Left Eye Horizontal",  CH_EYE_LEFT_H,  "left_h"),
        ("Left Eye Vertical",    CH_EYE_LEFT_V,  "left_v"),
        ("Right Eye Horizontal", CH_EYE_RIGHT_H, "right_h"),
        ("Right Eye Vertical",   CH_EYE_RIGHT_V, "right_v"),
        ("Left Eyelid",          CH_LID_LEFT,    "lid_l"),
        ("Right Eyelid",         CH_LID_RIGHT,   "lid_r")
    ]

    angles = {key: cal["servos"][key]["center"] for _, _, key in servolist}
    idx = 0

    print("\n=== CALIBRATION MODE ===")
    print("Select servo:")
    print("  1–4 = eye servos")
    print("  5–6 = eyelid servos")
    print("Move:")
    print("  Up/Down arrows = move selected servo")
    print("Mark eye direction:")
    print("  c = center")
    print("  l/r = horizontal look-left/look-right")
    print("  u/d = vertical look-up/look-down")
    print("Mark eyelids:")
    print("  w = wide open, o = open, b = closed")
    print("Center all:")
    print("  n = natural centers, f = file centers")
    print("Other:")
    print("  s = save, q = quit\n")

    while True:
        label, ch, key = servolist[idx]
        angle = angles[key]

        print(f"\rSelected: {label} | Angle: {angle:3.0f}   ", end="")

        k = get_key()

        if k == "q":
            print("\nExiting calibration.")
            break

        if k in "123456":
            idx = int(k) - 1
            continue

        if k == "n":
            centered = center_all_servos_natural()
            if centered:
                angles.update(centered)
                print("\nAll servos moved to natural centers.")
            continue

        if k == "f":
            cal = load_cal()
            centered = _move_all_servos_to_centers(cal)
            angles.update(centered)
            print("\nAll servos moved to saved calibration centers.")
            continue

        # === MODIFIED SECTION ===
        # Up/Down arrows now work for ALL servos (eyes + eyelids)
        if k == "\x1b[A":
            angle = min(180, angle + 2)
        elif k == "\x1b[B":
            angle = max(0, angle - 2)
        # === END MODIFIED SECTION ===

        angles[key] = angle

        if k == "c":
            cal["servos"][key]["center"] = angle
            if key in EYE_GAZE_LABELS:
                cal["gaze"][key]["center"] = angle
                _sync_servo_limits(cal, key)
            print(f"\nCenter for {label} = {angle}")

        if key in ("left_h", "right_h"):
            if k == "l":
                cal["gaze"][key]["left"] = angle
                _sync_servo_limits(cal, key)
                print(f"\nLook-left for {label} = {angle}")

            if k == "r":
                cal["gaze"][key]["right"] = angle
                _sync_servo_limits(cal, key)
                print(f"\nLook-right for {label} = {angle}")

        if key in ("left_v", "right_v"):
            if k == "u":
                cal["gaze"][key]["up"] = angle
                _sync_servo_limits(cal, key)
                print(f"\nLook-up for {label} = {angle}")

            if k == "d":
                cal["gaze"][key]["down"] = angle
                _sync_servo_limits(cal, key)
                print(f"\nLook-down for {label} = {angle}")

        if key in ("lid_l", "lid_r"):
            if k == "w":
                cal["servos"][key]["wide_open"] = angle
                print(f"\nWide open for {label} = {angle}")

            if k in ("o", "h"):
                cal["servos"][key]["high"] = angle
                print(f"\nOpen for {label} = {angle}")

            if k in ("b", "l"):
                cal["servos"][key]["low"] = angle
                print(f"\nClosed for {label} = {angle}")

        if k == "s":
            save_cal(cal)

        servos.set_servo_angle(ch, angle)
        time.sleep(0.02)

if __name__ == "__main__":
    calibrate()