from pathlib import Path
from dotenv import load_dotenv
import os
import json

import requests
from openai import OpenAI
from config import *
from network_status import internet_access_allowed

# Load environment variables
load_dotenv(Path(__file__).parent / ".env", override=True)

_openai_client = None


class InternetUnavailableError(ConnectionError):
    """Raised when a cloud answer is requested while Ezra is offline."""


# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are Ezra, a warm conversational robot assistant.

Answer the user's most recent question directly. Keep the answer short, natural,
accurate, and emotionally expressive. Do not substitute a greeting for an
answer unless the user greeted you.

Return only one valid JSON object with exactly two string fields: "emotion"
and "response". Put your actual answer in "response". The "emotion" value must
be one of: neutral, happy, curious, thinking, confused, excited.
"""


# =========================
# CONVERSATION MEMORY
# =========================
conversation_history = []


def _get_openai_client():
    """Create the cloud client only when the cloud provider is used."""

    global _openai_client

    if _openai_client is not None:
        return _openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not loaded")

    _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _ask_openai(messages):
    if not internet_access_allowed():
        raise InternetUnavailableError("Ezra is not connected to the internet")

    response = _get_openai_client().responses.create(
        model=OPENAI_MODEL,
        input=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
    )
    return getattr(response, "output_text", "").strip()


def _ask_local(messages):
    local_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *[dict(message) for message in messages],
    ]

    if LOCAL_AI_DISABLE_THINKING and local_messages[-1]["role"] == "user":
        local_messages[-1]["content"] = (
            f'{local_messages[-1]["content"]}\n/no_think'
        )

    response = requests.post(
        f'{LOCAL_AI_BASE_URL.rstrip("/")}/chat/completions',
        json={
            "model": LOCAL_AI_MODEL,
            "messages": local_messages,
            "temperature": LOCAL_AI_TEMPERATURE,
            "max_tokens": LOCAL_AI_MAX_TOKENS,
        },
        timeout=LOCAL_AI_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError("Local AI server returned an unexpected response") from exc


def _parse_brain_response(text):
    """Convert a model response into Ezra's emotion/response dictionary."""

    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()

    try:
        data = json.loads(cleaned)
    except Exception:
        data = {
            "emotion": "neutral",
            "response": cleaned if cleaned else "I'm not sure what to say.",
        }

    if not isinstance(data, dict):
        return {"emotion": "neutral", "response": cleaned}

    response = str(data.get("response", "")).strip()
    emotion = str(data.get("emotion", "neutral")).strip().lower()

    if not response:
        response = "I'm not sure what to say."

    return {"emotion": emotion, "response": response}


# =========================
# MAIN FUNCTION
# =========================
def ask_ezra(user_text):
    global conversation_history

    # Add user input
    conversation_history.append({"role": "user", "content": user_text})

    # Trim history
    conversation_history = conversation_history[-MAX_HISTORY:]

    provider = os.getenv("EZRA_AI_PROVIDER", AI_PROVIDER).strip().lower()

    if provider == "openai":
        if internet_access_allowed():
            text = _ask_openai(conversation_history)
        else:
            try:
                text = _ask_local(conversation_history)
            except requests.RequestException as exc:
                raise InternetUnavailableError(
                    "Neither the internet nor the local AI is available"
                ) from exc
    elif provider == "local":
        text = _ask_local(conversation_history)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")

    if VERBOSE_RUNTIME_LOGS:
        print(f"🧠 Raw GPT: {text}")

    data = _parse_brain_response(text)

    # Store assistant response
    conversation_history.append({"role": "assistant", "content": data["response"]})

    return data
