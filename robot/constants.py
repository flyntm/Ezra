# constants.py — corrected for Flynt's actual wiring

MIN_PULSE_MS = 0.5
MAX_PULSE_MS = 2.5
PERIOD_MS    = 20.0

# Eye servos
CH_EYE_LEFT_H  = 3
CH_EYE_LEFT_V  = 4
CH_EYE_RIGHT_H = 0
CH_EYE_RIGHT_V = 1

# Eyelid servos (one per eye)
CH_LID_LEFT  = 5
CH_LID_RIGHT = 2

# Head turn servo
CH_HEAD_TURN = 6

# Direction multipliers (flip sign if a servo is reversed)
DIR = {
    CH_EYE_LEFT_H:   1,
    CH_EYE_LEFT_V:  -1,

    CH_EYE_RIGHT_H:  1,
    CH_EYE_RIGHT_V:  1,

    CH_LID_LEFT:    -1,
    CH_LID_RIGHT:    1,
    CH_HEAD_TURN:    1,
}
