# servos.py — stable, known-good version (no batch writes)

import atexit
import threading

import board
import busio
from adafruit_pca9685 import PCA9685
from config import QUIET_STARTUP
from robot.constants import *

pca = None
_pca_lock = threading.RLock()


def init(_=None):
    global pca
    with _pca_lock:
        try:
            if not QUIET_STARTUP:
                print("[servos] Initializing PCA9685...")
            i2c = busio.I2C(board.SCL, board.SDA)
            pca = PCA9685(i2c)
            pca.frequency = 50
            if not QUIET_STARTUP:
                print("[servos] PCA9685 initialized OK")
            return True
        except Exception as e:
            print(f"[servos] ERROR initializing PCA9685: {e}")
            pca = None
            return False


def angle_to_duty_cycle(angle: float) -> int:
    angle = max(0.0, min(180.0, float(angle)))
    pulse_range = MAX_PULSE_MS - MIN_PULSE_MS
    pulse_width = MIN_PULSE_MS + (pulse_range * angle / 180.0)
    return int((pulse_width / PERIOD_MS) * 65535)


def set_servo_angle(channel: int, angle: float) -> None:
    with _pca_lock:
        if pca is None:
            print("[servos] WARNING: set_servo_angle called before init()")
            return

        direction = DIR.get(channel, 1)
        if direction == -1:
            angle = 180.0 - angle

        duty = angle_to_duty_cycle(angle)
        pca.channels[channel].duty_cycle = duty


def relax_all_servos():
    with _pca_lock:
        if pca is None:
            return
        for ch in range(16):
            pca.channels[ch].duty_cycle = 0


def shutdown():
    global pca

    with _pca_lock:
        if pca is None:
            return
        try:
            relax_all_servos()
            pca.deinit()
        finally:
            pca = None


atexit.register(shutdown)
