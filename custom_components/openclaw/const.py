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
