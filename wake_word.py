import time
import string
from audio import listen
from stt import transcribe
from ezra_emotion import set_emotion

# Words that commonly get mistaken for "Ezra"
WAKE_WORDS = ["ezra", "extra", "israel", "ezrah", "ez"]


def clean_text(text):
    """Lowercase and remove punctuation for reliable matching"""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    return text


def contains_wake_word(text):
    """Fuzzy wake detection (handles ezra, ezra's, etc.)"""
    for w in WAKE_WORDS:
        if w in text:
            return True
    return False


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
        cleaned = clean_text(text)

        print(f"(heard: {text_lower})")
        words = cleaned.split()
        print(f"(words parsed: {words})")

        # =========================
        # 1. STRONG WAKE DETECTION
        # =========================
        if contains_wake_word(cleaned):
            print("🟢 Wake word detected!")
            set_emotion("wake")
            time.sleep(0.25)
            return text

        # =========================
        # 2. IGNORE SINGLE-WORD NOISE
        # =========================
        if len(words) == 1:
            continue
