import time
from audio import listen
from stt import transcribe
from ezra_emotion import set_emotion

# Words that commonly get mistaken for "Ezra"
WAKE_WORDS = ["ezra", "extra", "israel", "ezrah", "ez"]


def wait_for_wake_word():
    print("👂 Waiting for wake word...")

    while True:
        audio = listen()

        if audio is None:
            continue

        text = transcribe(audio)
        if not text:
            continue

        text_lower = text.lower()
        print(f"(heard: {text_lower})")
        words = text_lower.replace(",", "").replace(".", "").split()
        print(f"(words parsed: {words})")

        # 1. Normal wake word
        if any(w in words[:2] for w in WAKE_WORDS):
            print("🟢 Wake word detected!")
            set_emotion("wake")
            time.sleep(0.25)
            return text

        # Skip single-word noise
        if len(words) == 1:
            continue

        # 2. FALLBACK: only if it looks like a command (starts immediately)
        if len(words) >= 2 and len(words) <= 6:
            print("🟡 Wake assumed (no wake word detected)")
            set_emotion("wake")
            time.sleep(0.25)
            return text
