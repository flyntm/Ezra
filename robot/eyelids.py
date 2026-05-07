# eyelids.py — one servo per eyelid

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
