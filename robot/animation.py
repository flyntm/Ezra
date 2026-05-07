# animation.py — idle eye, blink, and mouth motion

import time
import math
import random
from robot import eyes
from robot import eyelids
from robot import testmode

t0 = time.time()
next_blink = t0 + random.uniform(3.0, 7.0)
next_talk = t0 + random.uniform(5.0, 10.0)
talk_until = 0.0
next_mouth_frame = 0.0
mouth_is_lit = False

def reset():
    global t0, next_blink, next_talk, talk_until, next_mouth_frame, mouth_is_lit

    t0 = time.time()
    next_blink = t0 + random.uniform(6.0, 14.0)
    next_talk = t0 + random.uniform(5.0, 10.0)
    talk_until = 0.0
    next_mouth_frame = 0.0
    mouth_is_lit = False

def idle_motion():
    global next_blink, next_talk, talk_until, next_mouth_frame

    now = time.time()
    t = now - t0

    # small horizontal and vertical oscillation around center
    h_offset = 10 * math.sin(t * 0.4)
    v_offset = 5  * math.sin(t * 0.7)

    eyes.gaze(90 + h_offset, 90 + v_offset)

    if now >= next_blink:
        eyelids.close_lids()
        time.sleep(0.22)
        eyelids.open_lids()
        next_blink = now + random.uniform(6.0, 16.0)

    if now >= next_talk and now >= talk_until:
        talk_until = now + random.uniform(1.4, 2.6)
        next_talk = talk_until + random.uniform(5.0, 12.0)

    if now < talk_until:
        if now >= next_mouth_frame:
            _mouth_talk_frame()
            next_mouth_frame = now + random.uniform(0.05, 0.12)
    else:
        _mouth_off()

    time.sleep(0.03)

def _mouth_talk_frame():
    global mouth_is_lit

    if not testmode.neopixel_ready or testmode.pixels is None:
        return

    level = random.randint(25, 180)
    width = random.randint(2, testmode.LED_COUNT)
    start = (testmode.LED_COUNT - width) // 2

    testmode.pixels.fill((0, 0, 0))
    for i in range(start, start + width):
        testmode.pixels[i] = (level, max(0, level - 45), 0)
    testmode.pixels_show()
    mouth_is_lit = True

def _mouth_off():
    global mouth_is_lit

    if not mouth_is_lit:
        return

    if testmode.neopixel_ready and testmode.pixels is not None:
        testmode.pixels.fill((0, 0, 0))
        testmode.pixels_show()
    mouth_is_lit = False
