# =========================================
# AUTO-GENERATED CONFIG
# Mic: ATR4697
# Date: 2026-05-16 15:13:33.601997
# =========================================

# Measured:
# noise_floor = 0.006
# speech_avg  = 0.039
# speech_peak = 0.447
# SNR         = 0.033

# =========================
# AUDIO DEVICES
# =========================

# ALSA microphone input device
MIC_DEVICE = "plughw:3,0"

# ALSA speaker output device
SPEAKER_DEVICE = "plughw:2,0"


# =========================
# AUDIO SETTINGS
# =========================

# Sample rate for recording (Hz)
SAMPLE_RATE = 16000

# Duration of each audio chunk (seconds)
CHUNK_DURATION = 0.25

# Gain applied to microphone signal
GAIN = 5.17

# Bytes per sample (2 = 16-bit audio)
BYTES_PER_SAMPLE = 2

# Audio format for arecord
AUDIO_FORMAT = "S16_LE"

# Number of channels (1 = mono)
CHANNELS = 1

# Clamp RMS values to avoid spikes
RMS_CLAMP = 0.6


# =========================
# SPEECH DETECTION
# =========================

# Threshold above noise floor to START speech
START_THRESHOLD_OFFSET = 0.010

# Threshold above noise floor to detect SILENCE
SILENCE_THRESHOLD_OFFSET = 0.006

# Number of silent chunks before stopping recording
SILENCE_LIMIT = 3

# Minimum audio length (seconds)
MIN_AUDIO_LENGTH = 1.0

# How fast silence counter decreases when speech resumes
SILENCE_DECAY = 1


# =========================
# SPEECH START CONTROL
# =========================

# Number of loud chunks required to confirm speech start
START_CHUNKS_REQUIRED = 2


# =========================
# PRE-BUFFER
# =========================

# Number of chunks saved before speech detection
PRE_BUFFER_SIZE = 0


# =========================
# WHISPER (STT)
# =========================

# Whisper model size
WHISPER_MODEL = "small"

# Device ("cpu" for Raspberry Pi)
WHISPER_DEVICE = "cpu"

# Compute precision
WHISPER_COMPUTE_TYPE = "int8"

# Beam search size (higher = more accurate, slower)
WHISPER_BEAM_SIZE = 1

# Language
WHISPER_LANGUAGE = "en"


# =========================
# TEXT-TO-SPEECH (PIPER)
# =========================

# Path to Piper executable
PIPER_PATH = "~/projects/piper_tts/piper"

# Path to voice model
TTS_MODEL_PATH = "~/projects/piper_tts/en_US-lessac-medium.onnx"

# Delay before playback (seconds)
TTS_START_DELAY = 0.05


# =========================
# EMOTIONS
# =========================

# Default listening state
EMOTION_LISTENING = "listening"

# Talking animation state
EMOTION_TALKING = "normal_talking"


# =========================
# SYSTEM
# =========================

# Words that exit the program
QUIT_KEYWORDS = ["quit", "exit", "stop"]

# Spoken exit message
GOODBYE_TEXT = "Goodbye!"


# =========================
# AI SETTINGS
# =========================

# OpenAI model
OPENAI_MODEL = "gpt-4.1-mini"

# Max conversation history length
MAX_HISTORY = 12
