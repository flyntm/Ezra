# eyes.py — eye movement using calibration + smooth interpolation

import time
from robot import calibration
from robot import servos
from robot.constants import *

DEFAULT_CAL = {
    "servos": {
        "left_h":  {"center": 90, "low": 60, "high": 120},
        "left_v":  {"center": 90, "low": 60, "high": 120},
        "right_h": {"center": 90, "low": 60, "high": 120},
        "right_v": {"center": 90, "low": 60, "high": 120},
    },
    "gaze": {
        "left_h":  {"left": 60, "center": 90, "right": 120},
        "right_h": {"left": 60, "center": 90, "right": 120},
        "left_v":  {"up": 60, "center": 90, "down": 120},
        "right_v": {"up": 60, "center": 90, "down": 120},
    },
}

GAZE_MIN = 60.0
GAZE_CENTER = 90.0
GAZE_MAX = 120.0

def _load_cal():
    return calibration.load_cal()


CAL = _load_cal()


# ---------------------------------------------------------
# Track last positions for smooth motion
# ---------------------------------------------------------
_last_lh = 90
_last_lv = 90
_last_rh = 90
_last_rv = 90


def init():
    global CAL
    CAL = _load_cal()


# ---------------------------------------------------------
# Clamp using calibration
# ---------------------------------------------------------
def _clamp_servo(key, angle):
    low  = CAL["servos"][key]["low"]
    high = CAL["servos"][key]["high"]
    return max(low, min(high, angle))


def _logical_axis(value, low_value, center_value, high_value):
    value = max(GAZE_MIN, min(GAZE_MAX, float(value)))

    if value < GAZE_CENTER:
        t = (GAZE_CENTER - value) / (GAZE_CENTER - GAZE_MIN)
        return center_value + (low_value - center_value) * t

    t = (value - GAZE_CENTER) / (GAZE_MAX - GAZE_CENTER)
    return center_value + (high_value - center_value) * t


def _gaze_targets(h, v):
    gaze = CAL.get("gaze", DEFAULT_CAL["gaze"])

    lh = _logical_axis(h, gaze["left_h"]["left"], gaze["left_h"]["center"], gaze["left_h"]["right"])
    rh = _logical_axis(h, gaze["right_h"]["left"], gaze["right_h"]["center"], gaze["right_h"]["right"])
    lv = _logical_axis(v, gaze["left_v"]["up"], gaze["left_v"]["center"], gaze["left_v"]["down"])
    rv = _logical_axis(v, gaze["right_v"]["up"], gaze["right_v"]["center"], gaze["right_v"]["down"])

    return lh, lv, rh, rv


# ---------------------------------------------------------
# Center eyes
# ---------------------------------------------------------
def center():
    global _last_lh, _last_lv, _last_rh, _last_rv

    if CAL:
        lh = CAL["servos"]["left_h"]["center"]
        lv = CAL["servos"]["left_v"]["center"]
        rh = CAL["servos"]["right_h"]["center"]
        rv = CAL["servos"]["right_v"]["center"]
    else:
        lh = lv = rh = rv = 90

    servos.set_servo_angle(CH_EYE_LEFT_H,  lh)
    servos.set_servo_angle(CH_EYE_LEFT_V,  lv)
    servos.set_servo_angle(CH_EYE_RIGHT_H, rh)
    servos.set_servo_angle(CH_EYE_RIGHT_V, rv)

    _last_lh, _last_lv, _last_rh, _last_rv = lh, lv, rh, rv


def gaze(h, v):
    look(*_gaze_targets(h, v))


# ---------------------------------------------------------
# Instant movement
# ---------------------------------------------------------
def look(lh, lv, rh, rv):
    global _last_lh, _last_lv, _last_rh, _last_rv

    lh = _clamp_servo("left_h",  lh)
    lv = _clamp_servo("left_v",  lv)
    rh = _clamp_servo("right_h", rh)
    rv = _clamp_servo("right_v", rv)

    servos.set_servo_angle(CH_EYE_LEFT_H,  lh)
    servos.set_servo_angle(CH_EYE_LEFT_V,  lv)
    servos.set_servo_angle(CH_EYE_RIGHT_H, rh)
    servos.set_servo_angle(CH_EYE_RIGHT_V, rv)

    _last_lh, _last_lv, _last_rh, _last_rv = lh, lv, rh, rv


# ---------------------------------------------------------
# Smooth movement (staggers servo updates to avoid power spikes)
# ---------------------------------------------------------
def look_smooth(lh, lv, rh, rv, steps=40, duration=0.3):
    """Move both eyes smoothly with coordinated servo updates."""
    global _last_lh, _last_lv, _last_rh, _last_rv

    # Clamp targets
    target_lh = _clamp_servo("left_h",  lh)
    target_lv = _clamp_servo("left_v",  lv)
    target_rh = _clamp_servo("right_h", rh)
    target_rv = _clamp_servo("right_v", rv)

    # Starting positions
    start_lh = _last_lh
    start_lv = _last_lv
    start_rh = _last_rh
    start_rv = _last_rv

    if steps < 1:
        steps = 1

    step_time = duration / steps

    for i in range(steps + 1):
        t = i / steps

        cur_lh = start_lh + (target_lh - start_lh) * t
        cur_lv = start_lv + (target_lv - start_lv) * t
        cur_rh = start_rh + (target_rh - start_rh) * t
        cur_rv = start_rv + (target_rv - start_rv) * t

        servos.set_servo_angle(CH_EYE_LEFT_H,  cur_lh)
        servos.set_servo_angle(CH_EYE_LEFT_V,  cur_lv)
        servos.set_servo_angle(CH_EYE_RIGHT_H, cur_rh)
        servos.set_servo_angle(CH_EYE_RIGHT_V, cur_rv)
        time.sleep(step_time)

    _last_lh, _last_lv, _last_rh, _last_rv = target_lh, target_lv, target_rh, target_rv


def gaze_smooth(h, v, steps=60, duration=0.35):
    look_smooth(*_gaze_targets(h, v), steps=steps, duration=duration)


# ---------------------------------------------------------
# Alternative: Move eye pairs sequentially (even safer)
# ---------------------------------------------------------
def look_smooth_sequential(lh, lv, rh, rv, steps=40, duration=0.3):
    """Move left eye, then right eye to minimize simultaneous current draw."""
    global _last_lh, _last_lv, _last_rh, _last_rv

    target_lh = _clamp_servo("left_h",  lh)
    target_lv = _clamp_servo("left_v",  lv)
    target_rh = _clamp_servo("right_h", rh)
    target_rv = _clamp_servo("right_v", rv)

    start_lh = _last_lh
    start_lv = _last_lv
    start_rh = _last_rh
    start_rv = _last_rv

    if steps < 1:
        steps = 1

    step_time = duration / steps

    # Move left eye
    for i in range(steps + 1):
        t = i / steps
        cur_lh = start_lh + (target_lh - start_lh) * t
        cur_lv = start_lv + (target_lv - start_lv) * t
        servos.set_servo_angle(CH_EYE_LEFT_H,  cur_lh)
        servos.set_servo_angle(CH_EYE_LEFT_V,  cur_lv)
        time.sleep(step_time)

    _last_lh = target_lh
    _last_lv = target_lv

    # Move right eye
    for i in range(steps + 1):
        t = i / steps
        cur_rh = start_rh + (target_rh - start_rh) * t
        cur_rv = start_rv + (target_rv - start_rv) * t
        servos.set_servo_angle(CH_EYE_RIGHT_H, cur_rh)
        servos.set_servo_angle(CH_EYE_RIGHT_V, cur_rv)
        time.sleep(step_time)

    _last_rh = target_rh
    _last_rv = target_rv
