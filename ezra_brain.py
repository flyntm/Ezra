from pathlib import Path
from dotenv import load_dotenv
import os
import json
import re

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


class _StreamingResponseText:
    """Incrementally decode the JSON response string from text deltas."""

    def __init__(self):
        self.search_buffer = ""
        self.started = False
        self.finished = False
        self.escaped = False
        self.unicode_digits = None
        self.text = ""

    def feed(self, delta):
        if self.finished:
            return ""
        pending = str(delta)
        if not self.started:
            self.search_buffer += pending
            match = re.search(r'"response"\s*:\s*"', self.search_buffer)
            if match is None:
                self.search_buffer = self.search_buffer[-64:]
                return ""
            self.started = True
            pending = self.search_buffer[match.end() :]
            self.search_buffer = ""

        decoded = []
        escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b",
                   "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        for character in pending:
            if self.unicode_digits is not None:
                self.unicode_digits += character
                if len(self.unicode_digits) == 4:
                    try:
                        decoded.append(chr(int(self.unicode_digits, 16)))
                    except ValueError:
                        pass
                    self.unicode_digits = None
                continue
            if self.escaped:
                self.escaped = False
                if character == "u":
                    self.unicode_digits = ""
                else:
                    decoded.append(escapes.get(character, character))
                continue
            if character == "\\":
                self.escaped = True
            elif character == '"':
                self.finished = True
                break
            else:
                decoded.append(character)

        addition = "".join(decoded)
        self.text += addition
        return addition


def _pop_complete_sentences(buffer):
    """Return complete natural-language sentences and an unfinished tail."""
    sentences = []
    position = 0
    boundary = re.compile(r"(?<=[!?])\s+|(?<=[a-z0-9]\.)\s+")
    for match in boundary.finditer(buffer):
        sentence = buffer[position : match.start()].strip()
        if sentence:
            sentences.append(sentence)
        position = match.end()
    return sentences, buffer[position:]


def _ask_openai_streaming(messages, on_sentence):
    """Stream JSON deltas and deliver each completed response sentence."""
    if not internet_access_allowed():
        raise InternetUnavailableError("Ezra is not connected to the internet")

    raw_text = ""
    sentence_buffer = ""
    extractor = _StreamingResponseText()
    streamed_sentences = []
    interrupted = False
    first_sentence_delivered = False

    stream_failed = False
    try:
        with _get_openai_client().responses.stream(
            model=OPENAI_MODEL,
            input=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        ) as stream:
            for event in stream:
                if getattr(event, "type", "") != "response.output_text.delta":
                    continue
                delta = getattr(event, "delta", "")
                raw_text += delta
                sentence_buffer += extractor.feed(delta)
                sentences, sentence_buffer = _pop_complete_sentences(
                    sentence_buffer
                )
                for sentence in sentences:
                    streamed_sentences.append(sentence)
                    # Start speaking as soon as the first sentence is ready.
                    # Accumulate later sentences so they can be delivered in
                    # one smooth second batch rather than many tiny TTS calls.
                    if len(streamed_sentences) == 1:
                        first_sentence_delivered = True
                        if on_sentence(sentence):
                            interrupted = True
                            break
                if interrupted:
                    break
    except Exception:
        if not streamed_sentences:
            raise
        # Do not repeat already-spoken text through the fallback request. Keep
        # the completed sentences and discard any unfinished trailing fragment.
        stream_failed = True

    if not interrupted and not stream_failed:
        tail = sentence_buffer.strip()
        if tail:
            streamed_sentences.append(tail)

    if not interrupted and streamed_sentences and not first_sentence_delivered:
        first_sentence_delivered = True
        interrupted = bool(on_sentence(streamed_sentences[0]))

    if not interrupted and len(streamed_sentences) > 1:
        interrupted = bool(on_sentence(" ".join(streamed_sentences[1:])))

    data = _parse_brain_response(raw_text)
    if streamed_sentences:
        # If the stream was intentionally stopped, raw JSON may be incomplete.
        # Preserve exactly what was delivered for conversation history.
        data["response"] = " ".join(streamed_sentences).strip()
    data["streamed"] = bool(streamed_sentences)
    data["interrupted"] = interrupted
    return data


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
def ask_ezra(user_text, on_sentence=None):
    global conversation_history

    # Add user input
    conversation_history.append({"role": "user", "content": user_text})

    # Trim history
    conversation_history = conversation_history[-MAX_HISTORY:]

    provider = os.getenv("EZRA_AI_PROVIDER", AI_PROVIDER).strip().lower()

    if provider == "openai":
        if internet_access_allowed():
            if ENABLE_AI_RESPONSE_STREAMING and on_sentence is not None:
                try:
                    data = _ask_openai_streaming(
                        conversation_history,
                        on_sentence,
                    )
                except Exception:
                    # Falling back is safe only before any sentence was handed
                    # to playback; the streaming helper otherwise returns a
                    # partial result instead of raising.
                    text = _ask_openai(conversation_history)
                    data = _parse_brain_response(text)
            else:
                text = _ask_openai(conversation_history)
                data = _parse_brain_response(text)
        else:
            try:
                text = _ask_local(conversation_history)
                data = _parse_brain_response(text)
            except requests.RequestException as exc:
                raise InternetUnavailableError(
                    "Neither the internet nor the local AI is available"
                ) from exc
    elif provider == "local":
        text = _ask_local(conversation_history)
        data = _parse_brain_response(text)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")

    if VERBOSE_RUNTIME_LOGS and "text" in locals():
        print(f"🧠 Raw GPT: {text}")

    # Store assistant response
    conversation_history.append({"role": "assistant", "content": data["response"]})

    return data
