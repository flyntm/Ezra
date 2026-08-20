import contextlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import termios
import tempfile
import threading
import time
import wave

import numpy as np
import sounddevice as sd

from config import *
from ezra_emotion import set_emotion, set_talk_level
from mouth_sync import build_mouth_envelope
from persistent_piper import PersistentPiper
from respeaker_io import create_respeaker_or_raise
import state
from command_timing import (
    note_speech_finished,
    note_speech_requested,
    note_speech_started,
)


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
_evdev_warning_shown = False
_persistent_piper = PersistentPiper(PIPER_PATH, TTS_MODEL_PATH)


def _monitor_presentation_skip(
    stop_event,
    skip_event,
    ready_event,
    allow_space=False,
):
    """Treat Escape, and optionally Space, as a speech interruption."""
    if not sys.stdin.isatty():
        ready_event.set()
        return

    fd = sys.stdin.fileno()
    original = None
    try:
        original = termios.tcgetattr(fd)
        settings = termios.tcgetattr(fd)
        settings[3] &= ~(termios.ICANON | termios.ECHO)
        settings[6][termios.VMIN] = 0
        settings[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        ready_event.set()

        while not stop_event.is_set():
            readable, _, _ = select.select([fd], [], [], 0.1)
            if readable:
                key = os.read(fd, 1)
                if key == b"\x1b" or (allow_space and key == b" "):
                    key_name = "escape" if key == b"\x1b" else "space"
                    print(f"[presentation] keyboard_skip={key_name}")
                    skip_event.set()
                    stop_event.set()
                    return
    except (OSError, termios.error) as exc:
        ready_event.set()
        print(f"⚠️ Presentation keyboard skip unavailable: {exc}")
    finally:
        if original is not None:
            try:
                termios.tcsetattr(fd, termios.TCSANOW, original)
            except (OSError, termios.error):
                pass


def _monitor_external_presentation_skip(stop_event, skip_event, external_event):
    """Forward a focused slideshow's Escape key event to audio playback."""
    while not stop_event.is_set():
        if external_event.wait(timeout=0.1):
            print("[presentation] keyboard_skip=slideshow")
            skip_event.set()
            stop_event.set()
            return


def _monitor_linux_escape(stop_event, skip_event):
    """Listen for Escape on Pi keyboards regardless of window focus."""
    global _evdev_warning_shown

    try:
        from evdev import InputDevice, ecodes, list_devices
    except ImportError:
        if not _evdev_warning_shown:
            print("⚠️ Pi Escape-key listener unavailable: install evdev")
            _evdev_warning_shown = True
        return

    devices = []
    try:
        for path in list_devices():
            device = InputDevice(path)
            key_codes = device.capabilities().get(ecodes.EV_KEY, ())
            if ecodes.KEY_ESC in key_codes:
                devices.append(device)

        if not devices:
            if not _evdev_warning_shown:
                print(
                    "⚠️ Pi Escape-key listener found no accessible keyboard; "
                    "check input-group permissions"
                )
                _evdev_warning_shown = True
            return

        while not stop_event.is_set():
            readable, _, _ = select.select(devices, [], [], 0.1)
            for device in readable:
                for event in device.read():
                    if (
                        event.type == ecodes.EV_KEY
                        and event.code == ecodes.KEY_ESC
                        and event.value == 1
                    ):
                        print("[presentation] keyboard_skip=escape source=linux-input")
                        skip_event.set()
                        stop_event.set()
                        return
    except (OSError, PermissionError) as exc:
        if not _evdev_warning_shown:
            print(f"⚠️ Pi Escape-key listener unavailable: {exc}")
            _evdev_warning_shown = True
    finally:
        for device in devices:
            device.close()

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


def _open_stop_microphone(audio_callback):
    """Open the stop listener with the same retry/fallback policy as wake."""

    candidates = [WAKE_MIC_DEVICE, MIC_DEVICE, "default", None]
    candidates = list(dict.fromkeys(candidates))
    last_error = None

    for device in candidates:
        for attempt in range(1, WAKE_MIC_OPEN_RETRIES + 1):
            try:
                stream = sd.InputStream(
                    device=device,
                    samplerate=WAKE_SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=WAKE_BLOCK_SIZE,
                    callback=audio_callback,
                )
                stream.start()
                return stream
            except sd.PortAudioError as e:
                last_error = e
                error_text = str(e).lower()

                # Retrying cannot make an absent/incompatible device usable;
                # move directly to the next fallback in those cases.
                if (
                    "no input device matching" in error_text
                    or "invalid sample rate" in error_text
                ):
                    break

                if attempt < WAKE_MIC_OPEN_RETRIES:
                    time.sleep(WAKE_MIC_RETRY_DELAY)

    if last_error is not None:
        raise last_error
    raise RuntimeError("No microphone candidates are configured")


def _monitor_stop_phrase(stop_event, ready_event=None):
    """Listen for ezra_stop while TTS audio is playing."""

    if _stop_model is None:
        if ready_event is not None:
            ready_event.set()
        return

    _flush_stop_model()

    audio_queue = deque()
    stop_hits = deque(maxlen=MID_RESPONSE_STOP_GUARD_HITS)

    def audio_callback(indata, frames, time_info, status):
        audio_queue.append(indata[:, 0].copy())

    stream = None
    try:
        stream = _open_stop_microphone(audio_callback)
        try:
            if ready_event is not None:
                ready_event.set()

            while not stop_event.is_set():
                if not audio_queue:
                    time.sleep(0.01)
                    continue

                chunk = audio_queue.popleft()
                input_rms = float(np.sqrt(np.mean(chunk**2)))
                if input_rms < MID_RESPONSE_STOP_MIN_INPUT_RMS:
                    stop_hits.clear()
                    continue

                # OpenWakeWord is stateful: each live microphone sample must be
                # supplied exactly once and in chronological order. Replaying an
                # overlapping rolling window here corrupts its feature timeline.
                prepared_audio = _prepare_stop_audio(chunk)
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
        finally:
            try:
                stream.stop()
            finally:
                stream.close()
    except Exception as e:
        # Keep TTS running even if monitor fails, but surface diagnostics.
        if ready_event is not None:
            ready_event.set()

        if not QUIET_STARTUP:
            print(f"⚠️ Mid-response stop monitor error: {e}")
        return


def _split_tts_text(text, max_chars=None):
    max_chars = TTS_CHUNK_MAX_CHARS if max_chars is None else max_chars
    if len(text) <= max_chars:
        return [text]

    pieces = [
        piece.strip()
        for piece in re.split(r"(?<=[!?;])\s+|(?<=[a-z0-9]\.)\s+", text)
        if piece.strip()
    ]

    bounded_pieces = []
    for piece in pieces:
        while len(piece) > max_chars:
            split_at = piece.rfind(" ", 0, max_chars + 1)
            if split_at < 1:
                split_at = max_chars
            bounded_pieces.append(piece[:split_at].strip())
            piece = piece[split_at:].strip()
        if piece:
            bounded_pieces.append(piece)

    chunks = []
    current = ""

    for piece in bounded_pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= max_chars:
            current = f"{current} {piece}"
        else:
            chunks.append(current)
            current = piece

    if current:
        chunks.append(current)

    return chunks or [text]


def _render_speech_unit(speech_unit, output_file, sentence_silence=None):
    """Render one chunk to its own file for look-ahead synthesis."""
    text, emphasized, _pause_after = speech_unit
    length_scale = TTS_LENGTH_SCALE
    if emphasized:
        length_scale *= TTS_EMPHASIS_LENGTH_SCALE_MULTIPLIER
        print(f"[tts] emphasis={text!r}")
    if generate_speech_file(
        text,
        output_file,
        length_scale=length_scale,
        sentence_silence=sentence_silence,
    ):
        return output_file
    return None


def _split_emphasis_segments(text):
    """Return clean text segments tagged by exact [Emph] markers."""
    segments = []
    position = 0
    pattern = re.compile(r"\[Emph\](.*?)\[/Emph\]", re.DOTALL)

    for match in pattern.finditer(str(text)):
        normal = str(text)[position : match.start()].strip()
        emphasized = match.group(1).strip()
        if normal:
            segments.append((normal, False))
        if emphasized:
            segments.append((emphasized, True))
        position = match.end()

    remainder = str(text)[position:].strip()
    if remainder:
        segments.append((remainder, False))

    # Never pass unmatched control markers through to speech. Attach trailing
    # punctuation to the preceding unit so Piper is not asked to speak a WAV
    # containing only a period or comma.
    cleaned = []
    for segment, emphasized in segments or [(str(text), False)]:
        segment = segment.replace("[Emph]", "").replace("[/Emph]", "").strip()
        if not segment:
            continue
        if cleaned and not re.search(r"\w", segment):
            previous, previous_emphasis = cleaned[-1]
            cleaned[-1] = (previous + segment, previous_emphasis)
        else:
            cleaned.append((segment, emphasized))
    return cleaned


def _split_clause_pause_segments(text):
    """Split prose at colons/semicolons and retain the requested pause."""
    if not TTS_PAUSE_AT_COLONS_AND_SEMICOLONS:
        return [(str(text), 0.0)]

    segments = []
    position = 0
    for match in re.finditer(r"[:;](?=\s|$)", str(text)):
        clause = str(text)[position : match.end()].strip()
        if clause:
            segments.append((clause, TTS_COLON_SEMICOLON_PAUSE_SECONDS))
        position = match.end()

    remainder = str(text)[position:].strip()
    if remainder:
        segments.append((remainder, 0.0))
    elif segments:
        clause, _pause = segments[-1]
        segments[-1] = (clause, 0.0)

    return segments or [(str(text), 0.0)]


def _split_explicit_pause_segments(text):
    """Remove [Pause] markers and attach silence to the preceding text."""

    pieces = re.split(r"\s*\[Pause\]\s*", str(text), flags=re.IGNORECASE)
    segments = []
    for index, piece in enumerate(pieces):
        cleaned = piece.strip()
        if not cleaned:
            continue
        pause_after = (
            TTS_EXPLICIT_PAUSE_SECONDS if index < len(pieces) - 1 else 0.0
        )
        segments.append((cleaned, pause_after))
    return segments or [(str(text).replace("[Pause]", "").strip(), 0.0)]


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


def generate_speech_file(
    text,
    output_file="temp.wav",
    length_scale=None,
    sentence_silence=None,
):
    """Generate one Piper WAV, optionally for a reusable personality cache."""
    if state.shutting_down:
        return False

    text = _apply_pronunciation_overrides(text)
    selected_length_scale = (
        TTS_LENGTH_SCALE if length_scale is None else length_scale
    )
    selected_sentence_silence = (
        TTS_SENTENCE_SILENCE
        if sentence_silence is None
        else sentence_silence
    )
    if ENABLE_PERSISTENT_PIPER:
        try:
            if _persistent_piper.synthesize(
                text,
                output_file,
                selected_length_scale,
                selected_sentence_silence,
            ):
                return True
            print("⚠️ Persistent Piper unavailable; using one-shot synthesis")
        except Exception as exc:
            print(f"⚠️ Persistent Piper failed; using one-shot synthesis: {exc}")

    cmd = [
        os.path.expanduser(PIPER_PATH),
        "--model",
        os.path.expanduser(TTS_MODEL_PATH),
        "--length_scale",
        str(selected_length_scale),
        "--sentence_silence",
        str(selected_sentence_silence),
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


def _generate_combined_speech_file(
    speech_units,
    output_file="temp.wav",
    sentence_silence=None,
):
    """Synthesize marked segments and join them with controlled pauses."""
    with tempfile.TemporaryDirectory(prefix="ezra-speech-") as directory:
        rendered = []
        for index, (text, emphasized, _pause_after) in enumerate(speech_units):
            path = Path(directory) / f"segment-{index}.wav"
            length_scale = TTS_LENGTH_SCALE
            if emphasized:
                length_scale *= TTS_EMPHASIS_LENGTH_SCALE_MULTIPLIER
                print(f"[tts] emphasis={text!r}")
            if not generate_speech_file(
                text,
                path,
                length_scale=length_scale,
                sentence_silence=sentence_silence,
            ):
                return False
            rendered.append(path)

        parameters = None
        joined_frames = []
        for index, path in enumerate(rendered):
            with wave.open(os.fspath(path), "rb") as source:
                current_parameters = source.getparams()
                frames = source.readframes(source.getnframes())
            if parameters is None:
                parameters = current_parameters
            elif (
                current_parameters.nchannels,
                current_parameters.sampwidth,
                current_parameters.framerate,
                current_parameters.comptype,
            ) != (
                parameters.nchannels,
                parameters.sampwidth,
                parameters.framerate,
                parameters.comptype,
            ):
                return False

            if parameters.sampwidth == 2 and frames:
                samples = np.frombuffer(frames, dtype="<i2")
                channels = parameters.nchannels
                sample_frames = samples.reshape(-1, channels)
                if speech_units[index][1]:
                    sample_frames = np.clip(
                        sample_frames.astype(np.float32) * TTS_EMPHASIS_GAIN,
                        -32768,
                        32767,
                    ).astype("<i2")
                active = np.flatnonzero(np.max(np.abs(sample_frames), axis=1) > 160)
                if active.size:
                    padding = int(parameters.framerate * 0.025)
                    start = 0 if index == 0 else max(0, int(active[0]) - padding)
                    end = (
                        len(sample_frames)
                        if index == len(rendered) - 1
                        else min(len(sample_frames), int(active[-1]) + padding + 1)
                    )
                    frames = sample_frames[start:end].astype("<i2").tobytes()
            joined_frames.append(frames)
            if index < len(rendered) - 1:
                pause_seconds = speech_units[index][2]
                if (
                    pause_seconds <= 0
                    and speech_units[index][1] != speech_units[index + 1][1]
                ):
                    pause_seconds = TTS_EMPHASIS_BOUNDARY_PAUSE_SECONDS
                silence_frames = round(parameters.framerate * pause_seconds)
                if silence_frames:
                    joined_frames.append(
                        b"\x00"
                        * silence_frames
                        * parameters.nchannels
                        * parameters.sampwidth
                    )

        with wave.open(os.fspath(output_file), "wb") as destination:
            destination.setparams(parameters)
            destination.writeframes(b"".join(joined_frames))
    return True


def prepare_speech_cache(texts):
    """Pre-generate short, frequently used responses for immediate playback."""
    cache_dir = Path(__file__).parent / ".cache" / "speech"
    cache_dir.mkdir(parents=True, exist_ok=True)

    for text in texts:
        key = str(text)
        identity = (
            f"{TTS_MODEL_PATH}|{TTS_LENGTH_SCALE}|"
            f"{TTS_SENTENCE_SILENCE}|{key}"
        )
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
    return None


def speak(
    text,
    allow_mid_response_stop=True,
    audio_file=None,
    on_playback_start=None,
    on_playback_complete=None,
    allow_keyboard_skip=False,
    presentation_skip_event=None,
    chunk_max_chars=None,
    allow_escape_stop=True,
    sentence_silence=None,
):
    if state.shutting_down:
        return False

    note_speech_requested()

    terminal_text = re.sub(
        r"\s*\[Pause\]\s*",
        " ",
        str(text),
        flags=re.IGNORECASE,
    ).strip()
    print(f"Ezra: {terminal_text}")

    # Open the live stop listener before playback so the speaker device does
    # not win the hardware race and hide "Ezra stop" from the microphone.
    stop_event = threading.Event()
    ready_event = threading.Event()
    monitor_thread = None
    keyboard_thread = None
    external_keyboard_thread = None
    linux_keyboard_thread = None
    keyboard_ready = threading.Event()
    keyboard_skip = threading.Event()
    interrupted_by_stop = False
    skipped_by_keyboard = False

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

    if allow_keyboard_skip or allow_escape_stop:
        keyboard_thread = threading.Thread(
            target=_monitor_presentation_skip,
            args=(
                stop_event,
                keyboard_skip,
                keyboard_ready,
                allow_keyboard_skip,
            ),
            daemon=True,
        )
        keyboard_thread.start()
        keyboard_ready.wait(timeout=0.5)
        linux_keyboard_thread = threading.Thread(
            target=_monitor_linux_escape,
            args=(stop_event, keyboard_skip),
            daemon=True,
        )
        linux_keyboard_thread.start()

    if presentation_skip_event is not None:
        presentation_skip_event.clear()
        external_keyboard_thread = threading.Thread(
            target=_monitor_external_presentation_skip,
            args=(stop_event, keyboard_skip, presentation_skip_event),
            daemon=True,
        )
        external_keyboard_thread.start()

    try:
        speech_units = []
        for segment, emphasized in _split_emphasis_segments(text):
            for explicit_text, explicit_pause in _split_explicit_pause_segments(
                segment
            ):
                clauses = _split_clause_pause_segments(explicit_text)
                for clause_index, (clause, pause_after) in enumerate(clauses):
                    if clause_index == len(clauses) - 1:
                        pause_after = max(pause_after, explicit_pause)
                    chunks = _split_tts_text(clause, max_chars=chunk_max_chars)
                    speech_units.extend(
                        (
                            chunk,
                            emphasized,
                            pause_after if index == len(chunks) - 1 else 0.0,
                        )
                        for index, chunk in enumerate(chunks)
                    )
        combined_audio_file = None
        speech_character_count = sum(len(unit[0]) for unit in speech_units)
        if (
            speech_character_count <= TTS_CHUNK_MAX_CHARS
            and len(speech_units) > 1
            and any(
                emphasized or pause_after > 0
                for _, emphasized, pause_after in speech_units
            )
        ):
            combined_audio_file = "temp.wav"
            if _generate_combined_speech_file(
                speech_units,
                combined_audio_file,
                sentence_silence=sentence_silence,
            ):
                speech_units = [("", False, 0.0)]
            else:
                # Preserve narration even if WAV joining is unavailable.
                print("⚠️ TTS audio joining failed; using segment playback")
                combined_audio_file = None
        playback_started = False
        playback_completed = bool(speech_units)
        streaming_directory = None
        streaming_executor = None
        render_future = None
        stream_chunks = (
            combined_audio_file is None
            and audio_file is None
            and len(speech_units) > 1
        )
        if stream_chunks:
            streaming_directory = tempfile.TemporaryDirectory(
                prefix="ezra-streaming-speech-"
            )
            streaming_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="ezra-tts",
            )
            first_path = Path(streaming_directory.name) / "chunk-0.wav"
            render_future = streaming_executor.submit(
                _render_speech_unit,
                speech_units[0],
                first_path,
                sentence_silence,
            )

        for index, (chunk, emphasized, _pause_after) in enumerate(speech_units):
            if stop_event.is_set():
                if keyboard_skip.is_set():
                    skipped_by_keyboard = True
                else:
                    interrupted_by_stop = True
                    playback_completed = False
                break

            chunk_audio_file = combined_audio_file
            if stream_chunks:
                chunk_audio_file = render_future.result()
                if chunk_audio_file is None:
                    playback_completed = False
                    break
                if index + 1 < len(speech_units):
                    next_path = (
                        Path(streaming_directory.name)
                        / f"chunk-{index + 1}.wav"
                    )
                    render_future = streaming_executor.submit(
                        _render_speech_unit,
                        speech_units[index + 1],
                        next_path,
                        sentence_silence,
                    )
            if chunk_audio_file is None:
                chunk_audio_file = (
                    audio_file
                    if len(speech_units) == 1 and not emphasized
                    else None
                )
            if chunk_audio_file is None:
                length_scale = TTS_LENGTH_SCALE
                if emphasized:
                    length_scale *= TTS_EMPHASIS_LENGTH_SCALE_MULTIPLIER
                    print(f"[tts] emphasis={chunk!r}")
                if not generate_speech_file(
                    chunk,
                    length_scale=length_scale,
                    sentence_silence=sentence_silence,
                ):
                    playback_completed = False
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

            note_speech_started()

            if not playback_started and on_playback_start is not None:
                try:
                    on_playback_start()
                except Exception as e:
                    print(f"⚠️ TTS playback-start callback failed: {e}")
                playback_started = True

            playback_result = _play_speech_file(
                stop_event, mouth_envelope, mouth_frame_seconds, chunk_audio_file
            )
            if stop_event.is_set() or playback_result is True:
                if keyboard_skip.is_set():
                    skipped_by_keyboard = True
                    playback_completed = True
                else:
                    interrupted_by_stop = True
                    playback_completed = False
                break
            if playback_result is not False:
                playback_completed = False
                break
            if _pause_after > 0 and combined_audio_file is None:
                stop_event.wait(_pause_after)

        note_speech_finished()

        if streaming_executor is not None:
            streaming_executor.shutdown(wait=True, cancel_futures=True)
        if streaming_directory is not None:
            streaming_directory.cleanup()

        if playback_completed and on_playback_complete is not None:
            try:
                on_playback_complete()
            except Exception as e:
                print(f"⚠️ TTS playback-complete callback failed: {e}")
    finally:
        stop_event.set()
        set_talk_level(0.0)
        if monitor_thread is not None:
            monitor_thread.join(timeout=0.5)
        if keyboard_thread is not None:
            keyboard_thread.join(timeout=0.5)
        if external_keyboard_thread is not None:
            external_keyboard_thread.join(timeout=0.5)
        if linux_keyboard_thread is not None:
            linux_keyboard_thread.join(timeout=0.5)
        _flush_stop_model()

    # Return to wake-word standby.
    set_emotion(EMOTION_STANDBY)

    if interrupted_by_stop and not state.shutting_down:
        # Confirmation without recursive stop-monitoring.
        speak("Stopped.", allow_mid_response_stop=False)

    if skipped_by_keyboard:
        print("[presentation] narration_skipped=True")

    return interrupted_by_stop
