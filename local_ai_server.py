"""Start and stop Ezra's loopback llama.cpp server."""

from pathlib import Path
import subprocess
import threading
import time

import requests

from config import (
    LOCAL_AI_BASE_URL,
    LOCAL_AI_CONTEXT_SIZE,
    LOCAL_AI_MODEL_PATH,
    LOCAL_AI_SERVER_PATH,
    LOCAL_AI_STARTUP_TIMEOUT_SECONDS,
)


_lock = threading.Lock()
_process = None


def local_ai_is_ready():
    try:
        response = requests.get(
            f'{LOCAL_AI_BASE_URL.rstrip("/")}/models',
            timeout=0.5,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def start_local_ai_server():
    """Ensure llama.cpp is accepting requests, starting it when necessary."""

    global _process

    if local_ai_is_ready():
        return True

    with _lock:
        if local_ai_is_ready():
            return True

        executable = Path(LOCAL_AI_SERVER_PATH)
        model = Path(LOCAL_AI_MODEL_PATH)
        if not executable.is_file():
            raise RuntimeError(f"Local AI server is missing: {executable}")
        if not model.is_file():
            raise RuntimeError(f"Local AI model is missing: {model}")

        if _process is None or _process.poll() is not None:
            print("🧠 Loading local AI...")
            _process = subprocess.Popen(
                [
                    str(executable),
                    "--model",
                    str(model),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8081",
                    "--ctx-size",
                    str(LOCAL_AI_CONTEXT_SIZE),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        deadline = time.monotonic() + LOCAL_AI_STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if local_ai_is_ready():
                print("🧠 Local AI ready")
                return True
            if _process.poll() is not None:
                raise RuntimeError("Local AI server stopped while loading")
            time.sleep(0.25)

        raise RuntimeError("Local AI server timed out while loading")


def stop_local_ai_server():
    """Stop the server only when this Ezra process started it."""

    global _process
    with _lock:
        process = _process
        _process = None

    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
