from pathlib import Path
from dotenv import load_dotenv
import os
import json
from openai import OpenAI

# Load env once
load_dotenv(Path(__file__).parent / ".env", override=True)

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY not loaded")

client = OpenAI(api_key=api_key)


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

conversation_history = []
MAX_HISTORY = 12


def ask_ezra(user_text):

    global conversation_history

    conversation_history.append({"role": "user", "content": user_text})

    conversation_history = conversation_history[-MAX_HISTORY:]

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history,
    )

    text = response.output_text.strip()

    print(f"🧠 Raw GPT: {text}")

    try:
        data = json.loads(text)
    except Exception:
        data = {"emotion": "neutral", "response": text}

    conversation_history.append({"role": "assistant", "content": data["response"]})

    return data
