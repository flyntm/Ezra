import contextlib
from collections import deque
import hashlib
import os
from pathlib import Path
import re
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd

from config import *
from ezra_emotion import set_emotion, set_talk_level
from mouth_sync import build_mouth_envelope
from respeaker_io import create_respeaker_or_raise
import state


@contextlib.contextmanager
def suppress_stderr():
    """Temporarily suppress low-level native stderr warnings."""

    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)

    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        os.close(devnull)


_stop_model = None
_stop_mic = None
_speech_cache = {}

if ENABLE_MID_RESPONSE_STOP:
    try:
        with suppress_stderr():
            from openwakeword.model import Model

            _stop_model = Model(
                wakeword_models=[MID_RESPONSE_STOP_MODEL_PATH],
                inference_framework="onnx",
            )

            # Warm up internal buffers so first live stop phrase is not missed.
            _stop_model.predict(np.zeros(WAKE_SAMPLE_RATE, dtype=np.int16))

        state.mid_response_stop_ready = True
    except Exception as e:
        _stop_model = None
        state.mid_response_stop_ready = False
        if not QUIET_STARTUP:
            print(f"⚠️ Mid-response stop disabled: {e}")

if ENABLE_MID_RESPONSE_STOP and ENABLE_MID_RESPONSE_VAD_ASSIST:
    try:
        _stop_mic = create_respeaker_or_raise()
    except Exception as e:
        _stop_mic = None
        if not QUIET_STARTUP:
            print(f"⚠️ Mid-response VAD assist disabled: {e}")


def _prediction_stop_score(predictions):
    """Return the stop score even if OpenWakeWord exposes a path-like key."""

    if "ezra_stop" in predictions:
        return float(predictions["ezra_stop"]), "ezra_stop"

    best_key = None
    best_score = 0.0

    for key, value in predictions.items():
        normalized_key = str(key).lower().replace("-", "_").replace(" ", "_")

        if "ezra_stop" in normalized_key or normalized_key.endswith("_stop"):
            score = float(value)
            if best_key is None or score > best_score:
                best_key = key
                best_score = score

    return best_score, best_key


def _flush_stop_model():
    """Clear OpenWakeWord's rolling features between TTS responses."""

    if _stop_model is None:
        return

    silence = np.zeros(WAKE_SAMPLE_RATE, dtype=np.int16)

    try:
        _stop_model.predict(silence)
        _stop_model.predict(silence)
    except Exception:
        pass


def _prepare_stop_audio(audio):
    """Apply gentle gain and RMS normalization for stop-word inference."""

    prepared = np.asarray(audio, dtype=np.float32)

    if prepared.size == 0:
        return prepared

    prepared = prepared - float(np.mean(prepared))
    prepared = np.clip(prepared * MID_RESPONSE_STOP_MIC_GAIN, -1.0, 1.0)

    rms = float(np.sqrt(np.mean(prepared**2)))

    if 0.0 < rms < MID_RESPONSE_STOP_TARGET_RMS:
        prepared = np.clip(
            prepared * (MID_RESPONSE_STOP_TARGET_RMS / rms),
            -1.0,
            1.0,
        )

    return prepared


def _read_respeaker_speech():
    """Return True when ReSpeaker reports speech, if available."""

    if _stop_mic is None:
        return False

    try:
        doa = _stop_mic.read("DOA_VALUE")
    except Exception:
        return False

    if len(doa) >= 4:
        return bool(doa[3])

    if len(doa) >= 2:
        return bool(doa[1])

    return False


def _monitor_stop_phrase(stop_event, ready_event=None):
    """Listen for ezra_stop while TTS audio is playing."""

    if _stop_model is None:
        if ready_event is not None:
            ready_event.set()
        return

    _flush_stop_model()

    audio_queue = deque()
    stop_hits = deque(maxlen=MID_RESPONSE_STOP_GUARD_HITS)
    rolling = np.zeros(WAKE_SAMPLE_RATE, dtype=np.float32)
    rolling_filled = 0

    def audio_callback(indata, frames, time_info, status):
        audio_queue.append(indata[:, 0].copy())

    try:
        with sd.InputStream(
            device=WAKE_MIC_DEVICE,
            samplerate=WAKE_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=WAKE_BLOCK_SIZE,
            callback=audio_callback,
        ):
            if ready_event is not None:
                ready_event.set()

            while not stop_event.is_set():
                if not audio_queue:
                    time.sleep(0.01)
                    continue

                chunk = audio_queue.popleft()

                if chunk.size >= rolling.size:
                    rolling = chunk[-rolling.size :].astype(np.float32, copy=False)
                    rolling_filled = rolling.size
                else:
                    shift = chunk.size
                    rolling[:-shift] = rolling[shift:]
                    rolling[-shift:] = chunk.astype(np.float32, copy=False)
                    rolling_filled = min(rolling.size, rolling_filled + shift)

                min_samples = max(
                    1,
                    int(WAKE_SAMPLE_RATE * MID_RESPONSE_STOP_MIN_WINDOW_SECONDS),
                )
                if rolling_filled < min_samples:
                    continue

                raw_window = rolling[-rolling_filled:]
                input_rms = float(np.sqrt(np.mean(raw_window**2)))
                if input_rms < MID_RESPONSE_STOP_MIN_INPUT_RMS:
                    stop_hits.clear()
                    continue

                # Keep model input length fixed to match wake-word runtime expectations.
                prepared_audio = _prepare_stop_audio(rolling)
                audio_int16 = np.clip(
                    prepared_audio * 32767,
                    -32768,
                    32767,
                ).astype(np.int16)

                predictions = _stop_model.predict(audio_int16)
                stop_score, _ = _prediction_stop_score(predictions)
                vad_speech = ENABLE_MID_RESPONSE_VAD_ASSIST and _read_respeaker_speech()

                threshold = MID_RESPONSE_STOP_GUARD_THRESHOLD
                if vad_speech:
                    threshold = min(
                        threshold,
                        MID_RESPONSE_STOP_VAD_ASSIST_THRESHOLD,
                    )

                stop_hits.append(stop_score >= threshold)

                if len(stop_hits) == MID_RESPONSE_STOP_GUARD_HITS and all(stop_hits):
                    stop_event.set()
                    print("🛑 Stop phrase detected — interrupting response")
                    _flush_stop_model()
                    return
    except Exception as e:
        # Keep TTS running even if monitor fails, but surface diagnostics.
        if ready_event is not None:
            ready_event.set()

        if not QUIET_STARTUP:
            print(f"⚠️ Mid-response stop monitor error: {e}")
        return


def _split_tts_text(text):
    if len(text) <= TTS_CHUNK_MAX_CHARS:
        return [text]

    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[!?;])\s+|(?<=[a-z0-9]\.)\s+", text)
        if piece.strip()
    ]

    chunks = []
    current = ""

    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= TTS_CHUNK_MAX_CHARS:
            current = f"{current} {piece}"
        else:
            chunks.append(current)
            current = piece

    if current:
        chunks.append(current)

    return chunks or [text]


def _apply_pronunciation_overrides(text):
    """Apply whole-word, case-insensitive respellings only for Piper input."""
    spoken_text = str(text)

    for written, pronunciation in TTS_PRONUNCIATION_OVERRIDES.items():
        pattern = rf"(?<!\w){re.escape(written)}(?!\w)"
        spoken_text = re.sub(
            pattern,
            lambda _match, replacement=pronunciation: replacement,
            spoken_text,
            flags=re.IGNORECASE,
        )

    return spoken_text


def generate_speech_file(text, output_file="temp.wav"):
    """Generate one Piper WAV, optionally for a reusable personality cache."""
    if state.shutting_down:
        return False

    text = _apply_pronunciation_overrides(text)
    cmd = [
        os.path.expanduser(PIPER_PATH),
        "--model",
        os.path.expanduser(TTS_MODEL_PATH),
        "--length_scale",
        str(TTS_LENGTH_SCALE),
        "--output_file",
        os.fspath(output_file),
    ]
    try:
        result = subprocess.run(
            cmd,
            input=text,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as e:
        print(f"⚠️ TTS generation failed: {e}")
        return False

    return result.returncode == 0 and os.path.exists(output_file)


def prepare_speech_cache(texts):
    """Pre-generate short, frequently used responses for immediate playback."""
    cache_dir = Path(__file__).parent / ".cache" / "speech"
    cache_dir.mkdir(parents=True, exist_ok=True)

    for text in texts:
        key = str(text)
        identity = f"{TTS_MODEL_PATH}|{TTS_LENGTH_SCALE}|{key}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        path = cache_dir / f"{digest}.wav"
        if path.exists() or generate_speech_file(key, path):
            _speech_cache[key] = path


def speak_cached(text, allow_mid_response_stop=False):
    """Speak from the prepared cache, falling back to normal generation."""
    return speak(
        text,
        allow_mid_response_stop=allow_mid_response_stop,
        audio_file=_speech_cache.get(str(text)),
    )


def _play_speech_file(
    stop_event,
    mouth_envelope,
    mouth_frame_seconds,
    audio_file="temp.wav",
):
    device_candidates = [SPEAKER_DEVICE, "default", None]
    deduped_candidates = []

    for candidate in device_candidates:
        if candidate not in deduped_candidates:
            deduped_candidates.append(candidate)

    for device in deduped_candidates:
        cmd = ["aplay", os.fspath(audio_file)]
        device_label = "system-default"

        if device is not None:
            cmd = ["aplay", "-D", device, os.fspath(audio_file)]
            device_label = str(device)

        set_talk_level(0.0)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            print(f"⚠️ TTS playback launch failed on '{device_label}': {e}")
            continue

        state.tts_process = proc
        playback_started_at = time.monotonic()
        last_mouth_index = -1

        try:
            while proc.poll() is None:
                playback_elapsed = time.monotonic() - playback_started_at
                if playback_elapsed < TTS_MOUTH_SYNC_OFFSET_SECONDS:
                    set_talk_level(0.0)
                else:
                    mouth_elapsed = playback_elapsed - TTS_MOUTH_SYNC_OFFSET_SECONDS
                    mouth_index = min(
                        len(mouth_envelope) - 1,
                        int(mouth_elapsed / mouth_frame_seconds),
                    )
                    if mouth_index != last_mouth_index:
                        set_talk_level(float(mouth_envelope[mouth_index]))
                        last_mouth_index = mouth_index

                if stop_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=0.3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return True
                time.sleep(0.02)
        finally:
            state.tts_process = None
            set_talk_level(0.0)

        if proc.returncode == 0:
            return False

        print(
            f"⚠️ TTS playback failed on '{device_label}' "
            f"(exit {proc.returncode}); trying fallback..."
        )

    print("⚠️ TTS playback failed on all output device attempts")
    return False


def speak(text, allow_mid_response_stop=True, audio_file=None):
    if state.shutting_down:
        return

    print(f"Ezra: {text}")

    # Open the live stop listener before playback so the speaker device does
    # not win the hardware race and hide "Ezra stop" from the microphone.
    stop_event = threading.Event()
    ready_event = threading.Event()
    monitor_thread = None
    interrupted_by_stop = False

    if (
        ENABLE_MID_RESPONSE_STOP
        and allow_mid_response_stop
        and state.mid_response_stop_ready
    ):
        monitor_thread = threading.Thread(
            target=_monitor_stop_phrase,
            args=(stop_event, ready_event),
            daemon=True,
        )
        monitor_thread.start()
        ready_event.wait(timeout=MID_RESPONSE_STOP_READY_TIMEOUT)
    elif allow_mid_response_stop:
        _flush_stop_model()

    try:
        chunks = _split_tts_text(text)
        for chunk in chunks:
            if stop_event.is_set():
                interrupted_by_stop = True
                break

            chunk_audio_file = audio_file if len(chunks) == 1 else None
            if chunk_audio_file is None:
                if not generate_speech_file(chunk):
                    break
                chunk_audio_file = "temp.wav"

            try:
                mouth_envelope, mouth_frame_seconds = build_mouth_envelope(
                    os.fspath(chunk_audio_file)
                )
            except Exception as e:
                print(f"⚠️ TTS mouth sync disabled for this chunk: {e}")
                mouth_envelope = np.ones(1, dtype=np.float32) * 0.5
                mouth_frame_seconds = max(0.01, TTS_MOUTH_SYNC_WINDOW_SECONDS)

            if TTS_START_DELAY > 0:
                time.sleep(TTS_START_DELAY)
            set_emotion(EMOTION_TALKING)

            if stop_event.is_set() or _play_speech_file(
                stop_event,
                mouth_envelope,
                mouth_frame_seconds,
                chunk_audio_file,
            ):
                interrupted_by_stop = True
                break
    finally:
        stop_event.set()
        set_talk_level(0.0)
        if monitor_thread is not None:
            monitor_thread.join(timeout=0.5)
        _flush_stop_model()

    # Return to wake-word standby.
    set_emotion(EMOTION_STANDBY)

    if interrupted_by_stop and not state.shutting_down:
        # Confirmation without recursive stop-monitoring.
        speak("Stopped.", allow_mid_response_stop=False)
