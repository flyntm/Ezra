# =========================
# DEBUG FLAGS
# =========================

# Reduce startup chatter from hardware/model initialization logs.
QUIET_STARTUP = False

# Show detailed audio, wake-model, STT timing, and probe logs.
VERBOSE_RUNTIME_LOGS = False

# Toggle post-command audio replay diagnostics.
ENABLE_PLAYBACK_DIAGNOSTICS = False

# Print a stage-by-stage latency summary after each completed command.
ENABLE_COMMAND_TIMING_DIAGNOSTIC = False

# Item test 1: report the wake/utterance direction without running speech-to-text,
# command handling, AI response, TTS, or head movement. Set to False to restore
# normal operation.
ENABLE_DOA_DIAGNOSTIC = False

# Item test 2: transcribe and display the recorded command, then stop before
# command handling, AI, TTS, or head movement.
ENABLE_COMMAND_TEXT_DIAGNOSTIC = False

# Item test 3: exercise wake/command head direction, report final yaw, and skip
# STT, command handling, AI, and TTS. Unlike the other diagnostics, head motion
# intentionally remains enabled.
ENABLE_HEAD_DIRECTION_DIAGNOSTIC = False

# Shared guard used to keep the head stationary in either diagnostic.
ENABLE_INTERACTION_DIAGNOSTIC = ENABLE_DOA_DIAGNOSTIC or ENABLE_COMMAND_TEXT_DIAGNOSTIC

# Freeze eyes, eyelids, and facial animation only for the isolated DoA and
# command-text diagnostics. Head-direction diagnostics intentionally retain the
# normal animation path so servo-noise suppression is tested realistically.
ENABLE_FACE_MOTION_DIAGNOSTIC = ENABLE_INTERACTION_DIAGNOSTIC

# While Ezra is idle and waiting, glance toward qualified ambient speech using
# only the eyes. Wake-word and command interactions continue to use the head.
ENABLE_SOUND_GAZE = True

# Hold the eyes centered while waiting so ambient sound glances are unmistakable.
# The lock is released as soon as a wake word starts an interaction.
SOUND_GAZE_TEST_MODE = False
SOUND_GAZE_MAX_BEARING_DEGREES = 90.0
SOUND_GAZE_MAX_EYE_OFFSET = 28.0
# Below 1.0 makes medium bearings more visible while retaining proportionality.
SOUND_GAZE_RESPONSE_EXPONENT = 0.85
SOUND_GAZE_VERTICAL_POSITION = 86.0
# Ambient gaze needs a stronger signal than wake/command capture because the
# ReSpeaker hardware VAD can briefly classify quiet-room noise as speech.
SOUND_GAZE_AMBIENT_MIN_RMS = 0.012
SOUND_GAZE_AMBIENT_MIN_SPEECH_SECONDS = 0.40
SOUND_GAZE_AMBIENT_HOLD_SECONDS = 2.5
SOUND_GAZE_AMBIENT_COOLDOWN_SECONDS = 2.5
SOUND_GAZE_AMBIENT_RESET_SILENCE_SECONDS = 0.35
# Ignore microphone/VAD activity briefly after an eyelid blink so nearby servo
# noise cannot be mistaken for a speaker.
SOUND_GAZE_BLINK_SUPPRESSION_SECONDS = 0.60
# Ignore DoA briefly after eye-servo motion as well as eyelid motion.
DOA_EYE_MOTION_SUPPRESSION_SECONDS = 0.35

# Recover from a transient ReSpeaker USB reset without flooding the terminal.
RESPEAKER_RECONNECT_INTERVAL_SECONDS = 1.0
RESPEAKER_ERROR_LOG_INTERVAL_SECONDS = 5.0

# A DoA is diagnostic-worthy only after enough VAD-backed speech and a stable
# group of recent bearings. These values can be tuned from test observations.
COMMAND_DOA_MIN_ACTIVE_SPEECH_SECONDS = 0.40
COMMAND_DOA_STABILITY_WINDOW_SECONDS = 0.25
COMMAND_DOA_MAX_CIRCULAR_DEVIATION_DEGREES = 15.0
# Active speech must form one dominant angular cluster, and the final settled
# bearing must agree with that cluster before a head turn is allowed.
COMMAND_DOA_ACTIVE_CLUSTER_TOLERANCE_DEGREES = 25.0
COMMAND_DOA_MIN_ACTIVE_CLUSTER_FRACTION = 0.65
COMMAND_DOA_SETTLED_AGREEMENT_DEGREES = 25.0
# A wake-only phrase has less phonetic content than a command, so require a
# longer speech-backed observation before moving the head from it alone.
WAKE_ONLY_DOA_MIN_ACTIVE_SPEECH_SECONDS = 0.75

# Enable live web lookups for weather/news style requests.
ENABLE_LIVE_INFO = True

# Simulate a device with no internet connection. This prevents connectivity
# probes and all known external HTTP/API calls while leaving local services
# (including the loopback AI server) available for offline testing.
OFFLINE_TEST_MODE = False

# Enable voice stop detection while Ezra is currently speaking.
ENABLE_MID_RESPONSE_STOP = True


# =========================
# AUDIO DEVICES
# =========================

# Stable PortAudio device-name fragment for the ReSpeaker. Avoid numeric device
# indexes: HDMI and USB enumeration order can change across boots.
MIC_DEVICE = "reSpeaker XVF3800 4-Mic Array"

# ALSA speaker output device. Use the PipeWire/ALSA default selected by wpctl.
SPEAKER_DEVICE = "default"


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

# Model used to detect stop phrase during TTS playback.
MID_RESPONSE_STOP_MODEL_PATH = "/home/flyntm/projects/ezra/ezra_stop.onnx"

# Mid-response stop sensitivity while Ezra is speaking.
# Require sustained confidence so Ezra's own amplified voice is less likely to
# be mistaken for a stop request. This is intentionally more sensitive than
# the idle stop guard because the user is competing with Ezra's speaker.
MID_RESPONSE_STOP_GUARD_THRESHOLD = 0.22
MID_RESPONSE_STOP_GUARD_HITS = 2

# Lower stop threshold while ReSpeaker hardware VAD sees active speech.
MID_RESPONSE_STOP_VAD_ASSIST_THRESHOLD = 0.16

# Do not normalize and classify near-silence. Servo and room noise can otherwise
# be amplified into a convincing stop-model input while Ezra is speaking.
MID_RESPONSE_STOP_MIN_INPUT_RMS = 0.0015

# Boost microphone input used for stop detection while TTS is playing.
MID_RESPONSE_STOP_MIC_GAIN = 3.0

# Normalize quiet mid-response stop audio toward this RMS before inference.
MID_RESPONSE_STOP_TARGET_RMS = 0.08

# Minimum rolling window length before running stop prediction.
MID_RESPONSE_STOP_MIN_WINDOW_SECONDS = 0.20

# How long TTS waits for the live stop listener to open before playback.
MID_RESPONSE_STOP_READY_TIMEOUT = 1.0

# Use ReSpeaker speech detection to assist "Ezra stop" while Ezra is talking.
ENABLE_MID_RESPONSE_VAD_ASSIST = True


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
WHISPER_MODEL = "small.en"

# Device ("cpu" for Raspberry Pi)
WHISPER_DEVICE = "cpu"

# Compute precision
WHISPER_COMPUTE_TYPE = "int8"

# Two inference threads benchmark faster than automatic/four-thread execution
# on this four-core Pi. Ezra transcribes one command at a time, so one worker
# avoids throughput-oriented overhead without changing decoding behavior.
WHISPER_CPU_THREADS = 2
WHISPER_NUM_WORKERS = 1

# Beam search size (higher = more accurate, slower)
WHISPER_BEAM_SIZE = 2

# Language
WHISPER_LANGUAGE = "en"


# =========================
# TEXT-TO-SPEECH (PIPER)
# =========================

# Path to Piper executable
PIPER_PATH = "~/projects/piper_tts/piper"

# Keep Piper and its voice model loaded between utterances. The existing
# one-shot CLI remains available as an automatic fallback.
ENABLE_PERSISTENT_PIPER = True

# Path to voice model
TTS_MODEL_PATH = "/home/flyntm/projects/ezra/voices/en_US-bryce-medium.onnx"

#  Talking Speed - Piper phoneme duration. Lower is faster; 1.0 is the voice model's default.
TTS_LENGTH_SCALE = 0.85

# Text inside [Emph]...[/Emph] is spoken more deliberately. Higher is slower.
TTS_EMPHASIS_LENGTH_SCALE_MULTIPLIER = 1.35
TTS_EMPHASIS_GAIN = 1.12
TTS_EMPHASIS_BOUNDARY_PAUSE_SECONDS = 0.40

# Silence Piper adds after sentence-ending punctuation.
TTS_SENTENCE_SILENCE = 1.0

# Prepared presentation scripts sound more natural with a shorter full-stop
# pause than conversational answers and Bible readings.
SCRIPTED_TTS_SENTENCE_SILENCE = 0.7

# Head movement used while Ezra delivers prepared presentation scripts.
PRESENTATION_HEAD_INITIAL_LOOK_DELAY_SECONDS = (2.0, 4.0)
PRESENTATION_HEAD_LOOK_INTERVAL_SECONDS = (3.0, 6.0)
PRESENTATION_WIDE_AUDIENCE_BEARINGS = (
    -48.0,
    -35.0,
    -22.0,
    -10.0,
    0.0,
    12.0,
    25.0,
    38.0,
    50.0,
)
PRESENTATION_NARROW_AUDIENCE_BEARINGS = (
    -35.0,
    -18.0,
    0.0,
    18.0,
    35.0,
)

# Additional silence requested by an exact [Pause] speech-control marker.
TTS_EXPLICIT_PAUSE_SECONDS = 1.5

# Brief silence immediately before text marked [Humor].
TTS_HUMOR_PAUSE_SECONDS = 0.6

# Hold the happy expression through the wink and a brief beat after it opens.
TTS_SMILE_PAUSE_SECONDS = 2.0

# [Smile] is a silent physical gesture; it does not add a spoken response.
TTS_SMILE_RESPONSES = ("",)

# Text inside [Humor]...[/Humor] gets a short setup pause and slower delivery.
# Its final clause is slowed further to emphasize the punchline.
TTS_HUMOR_LENGTH_SCALE_MULTIPLIER = 1.07
TTS_HUMOR_EMPHASIS_LENGTH_SCALE_MULTIPLIER = 1.14

# [Smile] performs one deliberately slow wink.
TTS_SMILE_WINK_CLOSED_SECONDS = 1.5

# Add a separate pause after clause-ending colons and semicolons. Colons inside
# values such as times and ratios are left unchanged.
TTS_PAUSE_AT_COLONS_AND_SEMICOLONS = True
TTS_COLON_SEMICOLON_PAUSE_SECONDS = 0.45

# Optional short personality comments played while a non-local AI request is
# pending. Audio is generated once and cached. A comment is stopped as soon as
# the real answer is ready so filler never delays the response.
ENABLE_THINKING_COMMENTS = True
THINKING_COMMENT_DELAY_SECONDS = 0.45
THINKING_COMMENTS = (
    "One moment.",
    "Let me think.",
    "Checking.",
    "Give me a second.",
)

# TTS-only respellings for names Piper pronounces incorrectly. The original
# response text remains unchanged in logs and conversation history.
TTS_PRONUNCIATION_OVERRIDES = {
    "Plano": "Play-no",
    "goofy": "goo-fee",
}

# Delay before playback (seconds)
TTS_START_DELAY = 0.05


# Keep responses in one continuous WAV when practical. This avoids the
# generation/launch gap between short TTS chunks sounding like a long period.
# Long responses are synthesized in sentence-aware chunks. While one chunk is
# playing, Piper prepares the next one so Ezra starts speaking sooner.
TTS_CHUNK_MAX_CHARS = 350

# Retain a named presentation setting for the slide narration call site while
# using the same smooth speech segmentation everywhere.
PRESENTATION_TTS_CHUNK_MAX_CHARS = TTS_CHUNK_MAX_CHARS

# Drive mouth shapes from short loudness windows in Piper's generated WAV.
TTS_MOUTH_SYNC_WINDOW_SECONDS = 0.04
TTS_MOUTH_SYNC_OFFSET_SECONDS = 0.03
TTS_MOUTH_NOISE_GATE_RMS = 0.012
TTS_MOUTH_REFERENCE_PERCENTILE = 90.0
TTS_MOUTH_LEVEL_GAMMA = 0.70


# =========================
# EMOTIONS
# =========================

# Default listening state
EMOTION_LISTENING = "listening"

# Idle wake-word monitoring state
EMOTION_STANDBY = "standby"

# Talking animation state
EMOTION_TALKING = "normal_talking"

# Command processing animation state
EMOTION_THINKING = "thinking"

# Show a smile briefly after upbeat/curious AI responses finish speaking.
POST_RESPONSE_SMILE_SECONDS = 5.0
POST_RESPONSE_SMILE_EMOTIONS = ("happy", "curious")


# =========================
# EYELID MOTION
# =========================

# Time for each closing/opening half of a blink. This runs only in the
# background face-animation thread and does not block audio or Whisper.
EYELID_BLINK_TRAVEL_SECONDS = 0.12
EYELID_BLINK_STEPS = 8


# =========================
# MOUTH LEDS
# =========================

MOUTH_LED_PIN = "D18"
MOUTH_LEDS_PER_STRIP = 8
MOUTH_LED_STRIP_COUNT = 3
MOUTH_LED_BRIGHTNESS = 0.2
MOUTH_LED_ORDER = "GRB"

MOUTH_LED_HUE_STEP_DEGREES = 6
MOUTH_LED_DEFAULT_HUE = 30
MOUTH_LED_TALK_FRAME_DELAY = 0.2
MOUTH_LED_THINK_DURATION = 4.0
MOUTH_LED_THINK_STEP_DELAY = 0.25
MOUTH_LED_THINK_FULL_PAUSE = 1.5
MOUTH_LED_STANDBY_INTENSITY = 0.05

MOUTH_LED_MODE_SMILE = "smile"
MOUTH_LED_MODE_FROWN = "frown"
MOUTH_LED_MODE_TALK = "talk"
MOUTH_LED_MODE_STANDBY = "standby"
MOUTH_LED_MODE_LISTENING = "listening"
MOUTH_LED_MODE_THINKING = "thinking"

MOUTH_LED_SELECTED_HUES = {
    MOUTH_LED_MODE_SMILE: 354,
    MOUTH_LED_MODE_FROWN: 252,
    MOUTH_LED_MODE_TALK: 258,
    MOUTH_LED_MODE_STANDBY: 293,
    MOUTH_LED_MODE_LISTENING: 258,
    MOUTH_LED_MODE_THINKING: 216,
}


# =========================
# SYSTEM
# =========================

# Words that exit the program
QUIT_KEYWORDS = ["quit", "exit", "stop"]

# Spoken exit message
GOODBYE_TEXT = "Goodbye!"

# Hold the completed sleep pose briefly before powering off the Pi.
SHUTDOWN_SLEEP_SETTLE_SECONDS = 1.0


# =========================
# AI SETTINGS
# =========================

# AI response provider. Use "openai" for the current cloud brain or "local"
# for an OpenAI-compatible llama.cpp server running on this Pi. The
# EZRA_AI_PROVIDER environment variable can override this during testing.
AI_PROVIDER = "openai"

# OpenAI model
OPENAI_MODEL = "gpt-4.1-mini"

# Speak complete sentences as the cloud response arrives instead of waiting for
# the entire answer. Local/offline responses retain the non-streaming path.
ENABLE_AI_RESPONSE_STREAMING = True

# Local llama.cpp server settings. The server is deliberately bound to the Pi's
# loopback interface so it is unavailable to other devices on the network.
LOCAL_AI_BASE_URL = "http://127.0.0.1:8081/v1"
LOCAL_AI_MODEL = "Qwen3-1.7B-Q8_0.gguf"
LOCAL_AI_SERVER_PATH = "/home/flyntm/.local/share/ezra/llama/llama-server"
LOCAL_AI_MODEL_PATH = "/home/flyntm/.local/share/ezra/models/Qwen3-1.7B-Q8_0.gguf"
LOCAL_AI_STARTUP_TIMEOUT_SECONDS = 60
LOCAL_AI_CONTEXT_SIZE = 2048
LOCAL_AI_TIMEOUT_SECONDS = 45
LOCAL_AI_MAX_TOKENS = 120
LOCAL_AI_TEMPERATURE = 0.2
LOCAL_AI_DISABLE_THINKING = True

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

# Short acknowledgements used when Ezra hears a wake word without a command.
WAKE_ONLY_RESPONSES = (
    "I'm listening.",
    "Yes?",
)


# =========================
# DEBUG AUDIO
# =========================

DEBUG_WAV_FILE = "/tmp/whisper_input.wav"
DEBUG_AUDIO_SAMPLE_RATE = 16000


# =========================
# WAKE PIPELINE
# =========================

WAKE_MIC_DEVICE = MIC_DEVICE
WAKE_SAMPLE_RATE = 16000
WAKE_CHANNELS = 1
WAKE_BLOCK_SIZE = 1024

WAKE_THRESHOLD = 0.20
WAKE_REARM_THRESHOLD = 0.05

HEY_EZRA_MIN_SCORE = 0.55
HEY_EZRA_DOMINANCE_MARGIN = 0.12
EZRA_PREFERENCE_FLOOR = 0.18
FORCE_HEY_EZRA_SCORE = 0.985

STOP_GUARD_THRESHOLD = 0.80
STOP_GUARD_HITS = 3

WAKE_CONFIRM_DELAY = 0.25

RECENT_AUDIO_SECONDS = 16.0
PREBUFFER_SECONDS = 1.10

CONTINUOUS_CAPTURE_AFTER_WAKE = True

# Allow a natural pause after the wake word before treating the interaction as
# wake-only and opening the separate follow-up listening turn.
WAKE_COMMAND_TIMEOUT = 3.0
WAKE_MAX_COMMAND_TIME = 10.0
WAKE_ACTIVE_RMS_THRESHOLD = 0.0055
WAKE_END_SILENCE = 0.75
WAKE_END_POST_ROLL_SECONDS = 0.35
SEED_ACTIVITY_WINDOW_SECONDS = 0.35

POST_WAKE_AUDIO_SECONDS_EZRA = 1.10
POST_WAKE_AUDIO_SECONDS_HEY_EZRA = 1.35

WAKE_TAIL_TRIM_SECONDS_EZRA = 0.00
WAKE_TAIL_TRIM_SECONDS_HEY_EZRA = 0.00

# Time until Ezra goes to sleep
SLEEP_TIMEOUT = 60

WAKE_MIC_OPEN_RETRIES = 8
WAKE_MIC_RETRY_DELAY = 0.25
WAKE_MIC_RELEASE_DELAY = 0.08


# =========================
# LISTEN PIPELINE
# =========================

LISTEN_MIC_DEVICE = MIC_DEVICE
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
# HEAD TRACKING
# =========================

ENABLE_HEAD_TRACKING = True

# Installed ReSpeaker orientation and Ezra head-coordinate convention.
HEAD_TRACKING_MIC_FORWARD_AZIMUTH = 180.0
HEAD_TRACKING_DIRECTION = 1.0

HEAD_TRACKING_MAX_YAW_DEGREES = 90.0
HEAD_TRACKING_CENTER_DEADBAND_DEGREES = 8.0

HEAD_TRACKING_SAMPLE_INTERVAL_SECONDS = 0.05
HEAD_TRACKING_WAKE_HISTORY_SECONDS = 1.10
HEAD_TRACKING_WAKE_SETTLE_SECONDS = 0.50
HEAD_TRACKING_MIN_SPEECH_SECONDS = 0.6
HEAD_TRACKING_MIN_CONTINUOUS_SPEECH_SECONDS = 0.2
HEAD_TRACKING_MIN_ACTIVE_AUDIO_SECONDS = 0.4
HEAD_TRACKING_AVERAGE_SECONDS = 0.25

# Head movement speed everywhere. Higher values move more slowly; lower values
# move more quickly. Motion is internally divided into small, smooth steps.
# 0.1 is the original speed; 0.2 takes approximately twice as long.
HEAD_MOVEMENT_STEP_DELAY_SECONDS = 0.2


# =========================
# LIVE INFO (WEB)
# =========================

# Network timeout for live info HTTP requests.
LIVE_INFO_TIMEOUT_SECONDS = 6

# Background internet-status monitor. A TCP connection is enough to verify
# usable DNS and outbound connectivity without downloading page content.
INTERNET_CHECK_INTERVAL_SECONDS = 30
INTERNET_CHECK_TIMEOUT_SECONDS = 2
INTERNET_CHECK_ENDPOINTS = (
    ("rest.api.bible", 443),
    ("api.openai.com", 443),
)


# =========================
# BIBLE SOURCES
# =========================

# Exact Scripture readings use NIV through API.Bible when it is reachable and
# fall back to the public-domain World English Bible stored on the Pi.
ENABLE_BIBLE_PASSAGES = True
ENABLE_BIBLE_DISPLAY = True
API_BIBLE_BASE_URL = "https://rest.api.bible/v1"
API_BIBLE_TIMEOUT_SECONDS = 5
API_BIBLE_NIV_ID = ""  # Optional; Ezra can discover it from the account.
WEB_BIBLE_DATABASE = "/home/flyntm/.local/share/ezra/bible/web.sqlite3"
BIBLE_MAX_SPOKEN_VERSES = 30

# Headlines returned per source when user asks for news/current events.
NEWS_HEADLINE_COUNT = 3

# Public RSS feeds checked in order.
NEWS_RSS_FEEDS = (
    "https://feeds.npr.org/1001/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
)

# Weather location for generic requests; "auto" uses IP-based location.
DEFAULT_WEATHER_LOCATION = "Plano"

# Default coordinates avoid a geocoding request for the usual weather command.
DEFAULT_WEATHER_LATITUDE = 33.020
DEFAULT_WEATHER_LONGITUDE = -96.699

# National Weather Service requests require an identifying User-Agent.
WEATHER_NWS_USER_AGENT = "Ezra personal home assistant"
WEATHER_MAX_OBSERVATION_AGE_MINUTES = 180
WEATHER_STATION_SEARCH_LIMIT = 5

# Include country name in spoken weather location.
WEATHER_INCLUDE_COUNTRY = False
