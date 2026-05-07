# constants.py — corrected for Flynt's actual wiring

MIN_PULSE_MS = 0.5
MAX_PULSE_MS = 2.5
PERIOD_MS    = 20.0

# Eye servos
CH_EYE_LEFT_H  = 0
CH_EYE_LEFT_V  = 1
CH_EYE_RIGHT_H = 3
CH_EYE_RIGHT_V = 4

# Eyelid servos (one per eye)
CH_LID_LEFT  = 2
CH_LID_RIGHT = 5

# Direction multipliers (flip sign if a servo is reversed)
DIR = {
    CH_EYE_LEFT_H:   1,   # left eye horizontal OK in test
    CH_EYE_LEFT_V:   1,   # left eye vertical OK in test

    CH_EYE_RIGHT_H:  1,   # you asked to restore this
    CH_EYE_RIGHT_V: -1,   # right eye vertical backwards in test → FIXED

    CH_LID_LEFT:     1,
    CH_LID_RIGHT:   -1,   # right eyelid backwards → FIXED
}

