# eyelids.py — one servo per eyelid

import time

from robot import calibration
from robot import servos
from robot.constants import *

def _load_cal():
    return calibration.load_cal()

CAL = _load_cal()

def init():
    global CAL
    CAL = _load_cal()

def open_lids():
    if CAL:
        servos.set_servo_angle(CH_LID_LEFT,  CAL["servos"]["lid_l"]["high"])
        servos.set_servo_angle(CH_LID_RIGHT, CAL["servos"]["lid_r"]["high"])
    else:
        servos.set_servo_angle(CH_LID_LEFT,  100)
        servos.set_servo_angle(CH_LID_RIGHT, 100)

def wide_open_lids():
    if CAL:
        left = CAL["servos"]["lid_l"].get("wide_open", CAL["servos"]["lid_l"]["high"])
        right = CAL["servos"]["lid_r"].get("wide_open", CAL["servos"]["lid_r"]["high"])
        servos.set_servo_angle(CH_LID_LEFT, left)
        servos.set_servo_angle(CH_LID_RIGHT, right)
    else:
        servos.set_servo_angle(CH_LID_LEFT,  100)
        servos.set_servo_angle(CH_LID_RIGHT, 100)

def close_lids():
    if CAL:
        servos.set_servo_angle(CH_LID_LEFT,  CAL["servos"]["lid_l"]["low"])
        servos.set_servo_angle(CH_LID_RIGHT, CAL["servos"]["lid_r"]["low"])
    else:
        servos.set_servo_angle(CH_LID_LEFT,  20)
        servos.set_servo_angle(CH_LID_RIGHT, 20)


def wink_left(times=1, closed_seconds=0.18, gap_seconds=0.14):
    """Wink the left eyelid while leaving the right eyelid open."""
    left_low = CAL["servos"]["lid_l"]["low"] if CAL else 20
    left_high = CAL["servos"]["lid_l"]["high"] if CAL else 100
    right_high = CAL["servos"]["lid_r"]["high"] if CAL else 100
    for index in range(max(0, int(times))):
        servos.set_servo_angle(CH_LID_RIGHT, right_high)
        servos.set_servo_angle(CH_LID_LEFT, left_low)
        time.sleep(closed_seconds)
        servos.set_servo_angle(CH_LID_LEFT, left_high)
        if index + 1 < times:
            time.sleep(gap_seconds)
