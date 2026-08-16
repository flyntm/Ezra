"""Standalone mouth animation test for Ezra's 3x8 NeoPixel array.

Controls:
    S = smile
    W = wake-word standby smile
    F = frown
    T = talking animation
    L = listening
    K = thinking
    A = all LEDs on, cycling through 8 colors
    Up/Down = browse hue wheel
    Enter = select current hue
    X = off
    Q = quit
"""

import sys
import termios
import time
import tty
import colorsys
import os
import select

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import board
import neopixel

import config as ezra_config

LEDS_PER_STRIP = ezra_config.MOUTH_LEDS_PER_STRIP
STRIP_COUNT = ezra_config.MOUTH_LED_STRIP_COUNT
LED_COUNT = LEDS_PER_STRIP * STRIP_COUNT
LED_PIN = getattr(board, ezra_config.MOUTH_LED_PIN)
LED_BRIGHTNESS = ezra_config.MOUTH_LED_BRIGHTNESS
LED_ORDER = getattr(neopixel, ezra_config.MOUTH_LED_ORDER)

OFF = (0, 0, 0)
ALL_LED_TEST_COLORS = (
    (255, 0, 0),      # red
    (255, 96, 0),     # orange
    (255, 255, 0),    # yellow
    (0, 255, 0),      # green
    (0, 255, 255),    # cyan
    (0, 0, 255),      # blue
    (180, 0, 255),    # purple
    (255, 255, 255),  # white
)
ALL_LED_TEST_COLOR_DELAY = 0.5

HUE_STEP_DEGREES = ezra_config.MOUTH_LED_HUE_STEP_DEGREES
HUE_CHOICES = 360 // HUE_STEP_DEGREES
TALK_FRAME_DELAY = ezra_config.MOUTH_LED_TALK_FRAME_DELAY
THINK_DURATION = ezra_config.MOUTH_LED_THINK_DURATION
THINK_STEP_DELAY = ezra_config.MOUTH_LED_THINK_STEP_DELAY
THINK_FULL_PAUSE = ezra_config.MOUTH_LED_THINK_FULL_PAUSE
MODE_SMILE = ezra_config.MOUTH_LED_MODE_SMILE
MODE_FROWN = ezra_config.MOUTH_LED_MODE_FROWN
MODE_TALK = ezra_config.MOUTH_LED_MODE_TALK
MODE_STANDBY = ezra_config.MOUTH_LED_MODE_STANDBY
MODE_LISTENING = ezra_config.MOUTH_LED_MODE_LISTENING
MODE_THINKING = ezra_config.MOUTH_LED_MODE_THINKING
DEFAULT_HUE = ezra_config.MOUTH_LED_DEFAULT_HUE
STANDBY_INTENSITY = ezra_config.MOUTH_LED_STANDBY_INTENSITY
MOUTH_MODES = (
    MODE_SMILE,
    MODE_FROWN,
    MODE_TALK,
    MODE_STANDBY,
    MODE_LISTENING,
    MODE_THINKING,
)
selected_hues = {mode: DEFAULT_HUE for mode in MOUTH_MODES}
active_mode = MODE_SMILE
pending_hue = DEFAULT_HUE
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config.py")

pixels = neopixel.NeoPixel(
    LED_PIN,
    LED_COUNT,
    brightness=LED_BRIGHTNESS,
    auto_write=False,
    pixel_order=LED_ORDER,
)


def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "UP"
                if ch3 == "B":
                    return "DOWN"
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def rc_to_index(row, col):
    # The physical strips are mounted bottom-to-top, while patterns are written
    # top-to-bottom. Flip the row so expressions render in the intended orientation.
    return (STRIP_COUNT - 1 - row) * LEDS_PER_STRIP + col


def expression_color(mode):
    return hue_to_rgb(selected_hues.get(mode, DEFAULT_HUE))


def hue_to_rgb(hue_degrees):
    h = (hue_degrees % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def load_saved_state():
    configured_hues = getattr(ezra_config, "MOUTH_LED_SELECTED_HUES", {})
    return {
        mode: int(configured_hues.get(mode, DEFAULT_HUE)) % 360
        for mode in MOUTH_MODES
    }


def save_selected_hues():
    hues_block = (
        "MOUTH_LED_SELECTED_HUES = {\n"
        f"    MOUTH_LED_MODE_SMILE: {int(selected_hues[MODE_SMILE]) % 360},\n"
        f"    MOUTH_LED_MODE_FROWN: {int(selected_hues[MODE_FROWN]) % 360},\n"
        f"    MOUTH_LED_MODE_TALK: {int(selected_hues[MODE_TALK]) % 360},\n"
        f"    MOUTH_LED_MODE_STANDBY: {int(selected_hues[MODE_STANDBY]) % 360},\n"
        f"    MOUTH_LED_MODE_LISTENING: {int(selected_hues[MODE_LISTENING]) % 360},\n"
        f"    MOUTH_LED_MODE_THINKING: {int(selected_hues[MODE_THINKING]) % 360},\n"
        "}"
    )

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_text = f.read()

        start = config_text.index("MOUTH_LED_SELECTED_HUES = {")
        end = config_text.index("\n}", start) + 2
        updated_config_text = config_text[:start] + hues_block + config_text[end:]

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(updated_config_text)
    except Exception:
        pass


def show_pattern(pattern, color=None):
    if color is None:
        color = expression_color(active_mode)

    pixels.fill(OFF)
    for row in range(STRIP_COUNT):
        for col in range(LEDS_PER_STRIP):
            if pattern[row][col]:
                pixels[rc_to_index(row, col)] = color
    pixels.show()


def all_off():
    pixels.fill(OFF)
    pixels.show()


def all_led_color_test(color_delay=ALL_LED_TEST_COLOR_DELAY):
    """Light every LED and cycle through eight diagnostic colors."""
    for color in ALL_LED_TEST_COLORS:
        pixels.fill(color)
        pixels.show()
        time.sleep(color_delay)

    all_off()


def drain_input_buffer(window_seconds=0.35):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    try:
        # Clear what is already buffered first.
        termios.tcflush(fd, termios.TCIFLUSH)
        # Then keep draining for a short window to catch late key repeats.
        tty.setraw(fd)
        end = time.time() + window_seconds
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                os.read(fd, 1024)
    except Exception:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def smile_pattern():
    return [
        [1, 0, 0, 0, 0, 0, 0, 1],
        [0, 1, 0, 0, 0, 0, 1, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
    ]


def smile():
    show_pattern(smile_pattern(), color=expression_color(MODE_SMILE))


def standby_pattern():
    return [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [0, 1, 0, 0, 0, 0, 1, 0],
        [0, 0, 1, 1, 1, 1, 0, 0],
    ]


def standby_color(hue):
    return tuple(int(channel * STANDBY_INTENSITY) for channel in hue_to_rgb(hue))


def standby():
    show_pattern(
        standby_pattern(),
        color=standby_color(selected_hues[MODE_STANDBY]),
    )


def frown_pattern():
    return [
        [0, 0, 1, 1, 1, 1, 0, 0],
        [0, 1, 0, 0, 0, 0, 1, 0],
        [1, 0, 0, 0, 0, 0, 0, 1],
    ]


def frown():
    show_pattern(frown_pattern(), color=expression_color(MODE_FROWN))


def talk_preview_pattern():
    return [
        [0, 1, 1, 1, 1, 1, 1, 0],
        [1, 0, 0, 0, 0, 0, 0, 1],
        [0, 1, 1, 1, 1, 1, 1, 0],
    ]


def talking(duration=4.0, frame_delay=TALK_FRAME_DELAY):
    frames = [
        # Closed mouth
        [
            [0, 0, 0, 0, 0, 0, 0, 0],
            [1, 1, 1, 1, 1, 1, 1, 1],
            [0, 1, 1, 1, 1, 1, 1, 0],
        ],
        # Open mouth
        [
            [0, 1, 1, 1, 1, 1, 1, 0],
            [1, 0, 0, 0, 0, 0, 0, 1],
            [0, 1, 1, 1, 1, 1, 1, 0],
        ],
    ]

    end_at = time.time() + duration
    i = 0
    while time.time() < end_at:
        show_pattern(frames[i % len(frames)], color=expression_color(MODE_TALK))
        i += 1
        time.sleep(frame_delay)

    all_off()


def listening_pattern():
    return [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [1, 1, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]


def listening():
    show_pattern(listening_pattern(), color=expression_color(MODE_LISTENING))


def thinking_pattern(count=8):
    count = max(0, min(LEDS_PER_STRIP, int(count)))
    return [
        [0, 0, 0, 0, 0, 0, 0, 0],
        [1 if i >= LEDS_PER_STRIP - count else 0 for i in range(LEDS_PER_STRIP)],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]


def thinking(
    duration=THINK_DURATION,
    step_delay=THINK_STEP_DELAY,
    full_pause=THINK_FULL_PAUSE,
):
    end_at = time.time() + duration
    while time.time() < end_at:
        for count in range(1, LEDS_PER_STRIP + 1):
            show_pattern(thinking_pattern(count), color=expression_color(MODE_THINKING))
            if count == LEDS_PER_STRIP:
                time.sleep(full_pause)
            else:
                time.sleep(step_delay)

            if time.time() >= end_at:
                break

    all_off()


def render_active_expression_preview(hue):
    color = hue_to_rgb(hue)
    if active_mode == MODE_SMILE:
        show_pattern(smile_pattern(), color=color)
    elif active_mode == MODE_STANDBY:
        show_pattern(standby_pattern(), color=standby_color(hue))
    elif active_mode == MODE_FROWN:
        show_pattern(frown_pattern(), color=color)
    elif active_mode == MODE_LISTENING:
        show_pattern(listening_pattern(), color=color)
    elif active_mode == MODE_THINKING:
        show_pattern(thinking_pattern(), color=color)
    else:
        show_pattern(talk_preview_pattern(), color=color)


def render_active_expression_selected():
    if active_mode == MODE_SMILE:
        smile()
    elif active_mode == MODE_STANDBY:
        standby()
    elif active_mode == MODE_FROWN:
        frown()
    elif active_mode == MODE_LISTENING:
        listening()
    elif active_mode == MODE_THINKING:
        thinking()
    else:
        show_pattern(talk_preview_pattern(), color=expression_color(MODE_TALK))


def main():
    global pending_hue, active_mode

    selected_hues.update(load_saved_state())
    pending_hue = selected_hues[active_mode]

    print("\n=== Ezra Mouth LED Test (3x8 on D18) ===")
    print("S = smile")
    print("W = wake-word standby smile")
    print("F = frown")
    print("T = talking animation")
    print("L = listening")
    print("K = thinking")
    print("A = all LEDs, cycle through 8 colors")
    print("(press S/W/F/T/L/K first to choose which expression color to edit)")
    print("Up/Down = browse hue wheel")
    print("Enter = select current hue")
    print("X = off")
    print("Q = quit\n")

    print(
        f"[mouth_test] Editing SMILE hue: {selected_hues[MODE_SMILE]} deg "
        f"({(selected_hues[MODE_SMILE] // HUE_STEP_DEGREES) + 1}/{HUE_CHOICES})"
    )

    drain_input_buffer()
    smile()

    try:
        while True:
            key = get_key()

            if key in ("q", "Q"):
                break
            if key == "UP":
                pending_hue = (pending_hue - HUE_STEP_DEGREES) % 360
                render_active_expression_preview(pending_hue)
                print(
                    "[mouth_test] Hue "
                    f"{(pending_hue // HUE_STEP_DEGREES) + 1}/{HUE_CHOICES}: "
                    f"{pending_hue} deg for {active_mode.upper()} (press Enter to select)"
                )
            elif key == "DOWN":
                pending_hue = (pending_hue + HUE_STEP_DEGREES) % 360
                render_active_expression_preview(pending_hue)
                print(
                    "[mouth_test] Hue "
                    f"{(pending_hue // HUE_STEP_DEGREES) + 1}/{HUE_CHOICES}: "
                    f"{pending_hue} deg for {active_mode.upper()} (press Enter to select)"
                )
            elif key == "ENTER":
                selected_hues[active_mode] = pending_hue
                save_selected_hues()
                render_active_expression_selected()
                print(
                    f"[mouth_test] Selected hue for {active_mode.upper()}: {pending_hue} deg"
                )
            elif key in ("s", "S"):
                active_mode = MODE_SMILE
                pending_hue = selected_hues[MODE_SMILE]
                smile()
                print(
                    f"[mouth_test] Smile (editing hue {pending_hue} deg; Up/Down then Enter)"
                )
            elif key in ("w", "W"):
                active_mode = MODE_STANDBY
                pending_hue = selected_hues[MODE_STANDBY]
                standby()
                print(
                    "[mouth_test] Wake-word standby smile "
                    f"(editing hue {pending_hue} deg; Up/Down then Enter)"
                )
            elif key in ("f", "F"):
                active_mode = MODE_FROWN
                pending_hue = selected_hues[MODE_FROWN]
                frown()
                print(
                    f"[mouth_test] Frown (editing hue {pending_hue} deg; Up/Down then Enter)"
                )
            elif key in ("t", "T"):
                active_mode = MODE_TALK
                pending_hue = selected_hues[MODE_TALK]
                print("[mouth_test] Talking...")
                talking()
                drain_input_buffer(window_seconds=0.15)
            elif key in ("l", "L"):
                active_mode = MODE_LISTENING
                pending_hue = selected_hues[MODE_LISTENING]
                listening()
                print(
                    f"[mouth_test] Listening (editing hue {pending_hue} deg; Up/Down then Enter)"
                )
            elif key in ("k", "K"):
                active_mode = MODE_THINKING
                pending_hue = selected_hues[MODE_THINKING]
                print("[mouth_test] Thinking...")
                thinking()
                drain_input_buffer(window_seconds=0.15)
            elif key in ("a", "A"):
                print("[mouth_test] All LEDs: cycling through 8 colors...")
                all_led_color_test()
                drain_input_buffer(window_seconds=0.15)
                print("[mouth_test] All-LED color test complete")
            elif key in ("x", "X"):
                all_off()
                print("[mouth_test] Off")
    except KeyboardInterrupt:
        pass
    finally:
        all_off()


if __name__ == "__main__":
    main()
