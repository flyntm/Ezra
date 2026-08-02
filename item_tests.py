"""Small, independently switchable tests for Ezra's interaction pipeline."""


def display_doa_diagnostic(wake_phrase, doa, diagnostic=None):
    """Display item test 1 without running speech-to-text."""
    if diagnostic is not None and not diagnostic["qualified"]:
        angle = diagnostic.get("angle")
        angle_text = "unavailable" if angle is None else f"{angle:+.1f}°"
        doa_text = (
            f"LOW CONFIDENCE {angle_text}; {diagnostic['reason']}; "
            f"speech={diagnostic['active_seconds']:.2f}s, "
            f"samples={diagnostic['sample_count']}"
        )
    elif diagnostic is not None:
        angle_text = (
            f"{doa:+.1f}°"
            if -90.0 <= doa <= 90.0
            else f"outside ±90° ({doa:+.1f}°)"
        )
        doa_text = (
            f"{angle_text} QUALIFIED; "
            f"speech={diagnostic['active_seconds']:.2f}s, "
            f"samples={diagnostic['sample_count']}, "
            f"spread=±{diagnostic['max_deviation']:.1f}°"
        )
    elif doa is None:
        doa_text = "unavailable"
    elif -90.0 <= doa <= 90.0:
        doa_text = f"{doa:+.1f}°"
    else:
        # Rear bearings are outside the requested/front-facing +/-90° field.
        doa_text = f"outside ±90° ({doa:+.1f}°)"

    print(
        f'🧪 ITEM TEST 1 | Wake: "{wake_phrase}" | STT: disabled | DoA: {doa_text}'
    )
    return True


def display_command_text_diagnostic(command):
    """Display item test 2 after speech-to-text and command normalization."""
    print(f'🧪 ITEM TEST 2 | Command: "{command}"')
    return True
