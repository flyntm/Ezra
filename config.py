# =========================
# DEBUG FLAGS
# =========================

# Reduce startup chatter from hardware/model initialization logs.
QUIET_STARTUP = False

# Toggle post-command audio replay diagnostics.
ENABLE_PLAYBACK_DIAGNOSTICS = True

# Enable live web lookups for weather/news style requests.
ENABLE_LIVE_INFO = True


# =========================
# AUDIO DEVICES
# =========================

# ALSA microphone input device
MIC_DEVICE = "plughw:3,0"

# ALSA speaker output device
SPEAKER_DEVICE = "plughw:CARD=UACDemoV10,DEV=0"


# =========================
# AUDIO SETTINGS
# =========================

# Sample rate for recording (Hz)
SAMPLE_RATE = 16000

# Duration of each audio chunk (seconds)
CHUNK_DURATION = 0.25

# Gain applied to microphone signal
GAIN = 2.00

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
START_THRESHOLD_OFFSET = 0.035

# Threshold above noise floor to detect SILENCE
SILENCE_THRESHOLD_OFFSET = 0.054

# Number of silent chunks before stopping recording
SILENCE_LIMIT = 5

# Minimum audio length (seconds)
MIN_AUDIO_LENGTH = 1.0

# How fast silence counter decreases when speech resumes
SILENCE_DECAY = 1


# =========================
# SPEECH START CONTROL
# =========================

# Number of loud chunks required to confirm speech start
START_CHUNKS_REQUIRED = 1


# =========================
# PRE-BUFFER
# =========================

# Number of chunks saved before speech detection
PRE_BUFFER_SIZE = 5


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


# =========================
# COMMAND NORMALIZATION
# =========================

# Common Whisper misinterpretations of "Ezra" used for prefix stripping.
WAKE_WORD_ALIASES = (
    "ezra",
    "zra",
    "ra",
    "edra",
    "extra",
    "israel",
    "ezrah",
    "ez",
    "you",
)

# Common tokens that appear as the second word in a mangled "hey ezra".
WAKE_SECOND_WORD_VARIANTS = (
    "there",
    "theres",
    "thereis",
    "here",
    "heres",
)

# Phrases that should be treated as wake-only/no command.
WAKE_ONLY_PHRASES = (
    "",
    "here's",
    "heres",
    "heres what",
    "hey there",
    "hey theres",
    "hey here",
    "hey heres",
    "ezra",
    "edra",
    "hey ezra",
    "hey edra",
    "extra",
    "israel",
    "ezrah",
)


# =========================
# DEBUG AUDIO
# =========================

DEBUG_WAV_FILE = "/tmp/whisper_input.wav"
DEBUG_AUDIO_SAMPLE_RATE = 16000


# =========================
# WAKE PIPELINE
# =========================

WAKE_MIC_DEVICE = 1
WAKE_SAMPLE_RATE = 16000
WAKE_CHANNELS = 1
WAKE_BLOCK_SIZE = 1024

WAKE_THRESHOLD = 0.10
WAKE_REARM_THRESHOLD = 0.05

HEY_EZRA_MIN_SCORE = 0.55
HEY_EZRA_DOMINANCE_MARGIN = 0.12
EZRA_PREFERENCE_FLOOR = 0.18
FORCE_HEY_EZRA_SCORE = 0.985

STOP_GUARD_THRESHOLD = 0.80
STOP_GUARD_HITS = 3

WAKE_CONFIRM_DELAY = 0.05

RECENT_AUDIO_SECONDS = 16.0
PREBUFFER_SECONDS = 1.10

CONTINUOUS_CAPTURE_AFTER_WAKE = True

WAKE_COMMAND_TIMEOUT = 5.0
WAKE_MAX_COMMAND_TIME = 10.0
WAKE_ACTIVE_RMS_THRESHOLD = 0.0055
WAKE_END_SILENCE = 0.95
WAKE_END_POST_ROLL_SECONDS = 0.60
SEED_ACTIVITY_WINDOW_SECONDS = 0.35

POST_WAKE_AUDIO_SECONDS_EZRA = 1.10
POST_WAKE_AUDIO_SECONDS_HEY_EZRA = 1.35

WAKE_TAIL_TRIM_SECONDS_EZRA = 0.00
WAKE_TAIL_TRIM_SECONDS_HEY_EZRA = 0.00

SLEEP_TIMEOUT = 20

WAKE_MIC_OPEN_RETRIES = 8
WAKE_MIC_RETRY_DELAY = 0.25
WAKE_MIC_RELEASE_DELAY = 0.08


# =========================
# LISTEN PIPELINE
# =========================

LISTEN_MIC_DEVICE = 1
LISTEN_SAMPLE_RATE = 16000
LISTEN_CHANNELS = 1
LISTEN_BLOCKSIZE = 1024

LISTEN_COMMAND_TIMEOUT = 5.0
LISTEN_MAX_COMMAND_TIME = 10.0

LISTEN_PRE_ROLL_SECONDS = 0.75
LISTEN_START_RMS_THRESHOLD = 0.008
LISTEN_ACTIVE_RMS_THRESHOLD = 0.0055
LISTEN_END_SILENCE = 0.95
LISTEN_END_POST_ROLL_SECONDS = 0.60


# =========================
# LIVE INFO (WEB)
# =========================

# Network timeout for live info HTTP requests.
LIVE_INFO_TIMEOUT_SECONDS = 6

# Headlines returned when user asks for news/current events.
NEWS_HEADLINE_COUNT = 3

# Public RSS feeds checked in order.
NEWS_RSS_FEEDS = (
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
)

# Weather location for generic requests; "auto" uses IP-based location.
DEFAULT_WEATHER_LOCATION = "Plano"

# Include country name in spoken weather location.
WEATHER_INCLUDE_COUNTRY = False
