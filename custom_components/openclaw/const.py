"""Constants for the OpenClaw integration."""

DOMAIN = "openclaw"

# Addon
ADDON_SLUG = "openclaw_assistant_dev"
# The Supervisor prefixes a repo hash to the slug in the filesystem path
#   e.g. /addon_configs/0bfc167e_openclaw_assistant
# We cannot hardcode this — it must be discovered at runtime.
ADDON_CONFIGS_ROOT = "/addon_configs"
ADDON_SLUG_FRAGMENTS = ("openclaw_assistant", "openclaw")
OPENCLAW_CONFIG_REL_PATH = ".openclaw/openclaw.json"

# Defaults
DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 18789
DEFAULT_SCAN_INTERVAL = 30  # seconds

# Config entry keys
CONF_GATEWAY_HOST = "gateway_host"
CONF_GATEWAY_PORT = "gateway_port"
CONF_GATEWAY_TOKEN = "gateway_token"
CONF_USE_SSL = "use_ssl"
CONF_ADDON_CONFIG_PATH = "addon_config_path"

# Options
CONF_INCLUDE_EXPOSED_CONTEXT = "include_exposed_context"
CONF_CONTEXT_MAX_CHARS = "context_max_chars"
CONF_CONTEXT_STRATEGY = "context_strategy"
CONF_ENABLE_TOOL_CALLS = "enable_tool_calls"
CONF_WAKE_WORD_ENABLED = "wake_word_enabled"
CONF_WAKE_WORD = "wake_word"
CONF_ALWAYS_VOICE_MODE = "always_voice_mode"
CONF_ALLOW_BRAVE_WEBSPEECH = "allow_brave_webspeech"
CONF_VOICE_PROVIDER = "voice_provider"

DEFAULT_INCLUDE_EXPOSED_CONTEXT = True
DEFAULT_CONTEXT_MAX_CHARS = 13000
DEFAULT_CONTEXT_STRATEGY = "truncate"
DEFAULT_ENABLE_TOOL_CALLS = False
DEFAULT_WAKE_WORD_ENABLED = False
DEFAULT_WAKE_WORD = "hey openclaw"
DEFAULT_ALWAYS_VOICE_MODE = False
DEFAULT_ALLOW_BRAVE_WEBSPEECH = False
DEFAULT_VOICE_PROVIDER = "browser"

CONTEXT_STRATEGY_TRUNCATE = "truncate"
CONTEXT_STRATEGY_CLEAR = "clear"

# Coordinator data keys
DATA_STATUS = "status"
DATA_MODEL = "model"
DATA_SESSION_COUNT = "session_count"
DATA_SESSIONS = "sessions"
DATA_LAST_ACTIVITY = "last_activity"
DATA_CONNECTED = "connected"
DATA_GATEWAY_VERSION = "gateway_version"
DATA_UPTIME = "uptime"
DATA_PROVIDER = "provider"
DATA_CONTEXT_WINDOW = "context_window"

# Platforms
PLATFORMS = ["sensor", "binary_sensor", "conversation"]

# Events
EVENT_MESSAGE_RECEIVED = f"{DOMAIN}_message_received"

# Services
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_CLEAR_HISTORY = "clear_history"

# Attributes
ATTR_MESSAGE = "message"
ATTR_SESSION_ID = "session_id"
ATTR_ATTACHMENTS = "attachments"
ATTR_MODEL = "model"
ATTR_TIMESTAMP = "timestamp"

# API endpoints
# The OpenClaw gateway exposes only the OpenAI-compatible endpoints.
# /api/status and /api/sessions do not exist — the gateway returns its SPA
# home page (text/html) for any unrecognised route.
API_MODELS = "/v1/models"
API_CHAT_COMPLETIONS = "/v1/chat/completions"
