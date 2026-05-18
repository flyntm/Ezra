from pathlib import Path
from dotenv import load_dotenv
import os
import json
from openai import OpenAI
from config import *

# Load environment variables
load_dotenv(Path(__file__).parent / ".env", override=True)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not loaded")

client = OpenAI(api_key=api_key)


# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are Ezra, a warm conversational robot assistant.

Keep responses:
- short
- natural
- emotionally expressive

Return ONLY valid JSON in this exact format:

{
  "emotion": "neutral",
  "response": "Hello there."
}

Allowed emotions:
neutral
happy
curious
thinking
confused
excited
"""


# =========================
# CONVERSATION MEMORY
# =========================
conversation_history = []


# =========================
# MAIN FUNCTION
# =========================
def ask_ezra(user_text):
    global conversation_history

    # Add user input
    conversation_history.append({"role": "user", "content": user_text})

    # Trim history
    conversation_history = conversation_history[-MAX_HISTORY:]

    # Call OpenAI
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history,
    )

    # Extract text safely
    text = getattr(response, "output_text", "").strip()

    print(f"🧠 Raw GPT: {text}")

    # Parse JSON safely
    try:
        data = json.loads(text)
    except Exception:
        data = {
            "emotion": "neutral",
            "response": text if text else "I'm not sure what to say.",
        }

    # Store assistant response
    conversation_history.append({"role": "assistant", "content": data["response"]})

    return data
