while True:
    angle = get_processed_doa()
    speaking = get_speech_flag()

    if speaking:
        print(f"Speaker at {angle:.0f}°")
