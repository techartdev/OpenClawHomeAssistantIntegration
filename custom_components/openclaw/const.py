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
CONF_VERIFY_SSL = "verify_ssl"
CONF_ADDON_CONFIG_PATH = "addon_config_path"

# Options
CONF_INCLUDE_EXPOSED_CONTEXT = "include_exposed_context"
CONF_CONTEXT_MAX_CHARS = "context_max_chars"
CONF_CONTEXT_STRATEGY = "context_strategy"
CONF_ENABLE_TOOL_CALLS = "enable_tool_calls"
CONF_WAKE_WORD_ENABLED = "wake_word_enabled"
CONF_WAKE_WORD = "wake_word"
CONF_ALLOW_BRAVE_WEBSPEECH = "allow_brave_webspeech"
CONF_VOICE_PROVIDER = "voice_provider"
CONF_BROWSER_VOICE_LANGUAGE = "browser_voice_language"
CONF_THINKING_TIMEOUT = "thinking_timeout"

DEFAULT_INCLUDE_EXPOSED_CONTEXT = True
DEFAULT_CONTEXT_MAX_CHARS = 13000
DEFAULT_CONTEXT_STRATEGY = "truncate"
DEFAULT_ENABLE_TOOL_CALLS = False
DEFAULT_WAKE_WORD_ENABLED = False
DEFAULT_WAKE_WORD = "hey openclaw"
DEFAULT_ALLOW_BRAVE_WEBSPEECH = False
DEFAULT_VOICE_PROVIDER = "browser"
DEFAULT_BROWSER_VOICE_LANGUAGE = "auto"
DEFAULT_THINKING_TIMEOUT = 120

BROWSER_VOICE_LANGUAGES: tuple[str, ...] = (
	"auto",
	"bg-BG",
	"en-US",
	"en-GB",
	"de-DE",
	"fr-FR",
	"es-ES",
	"it-IT",
	"pt-PT",
	"pt-BR",
	"ru-RU",
	"nl-NL",
	"pl-PL",
	"tr-TR",
	"uk-UA",
	"cs-CZ",
	"ro-RO",
	"el-GR",
	"sv-SE",
	"no-NO",
	"da-DK",
	"fi-FI",
	"hu-HU",
	"sk-SK",
	"sl-SI",
	"hr-HR",
	"sr-RS",
	"ja-JP",
	"ko-KR",
	"zh-CN",
	"zh-TW",
	"ar-SA",
	"he-IL",
	"hi-IN",
)

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
DATA_LAST_TOOL_NAME = "last_tool_name"
DATA_LAST_TOOL_STATUS = "last_tool_status"
DATA_LAST_TOOL_DURATION_MS = "last_tool_duration_ms"
DATA_LAST_TOOL_INVOKED_AT = "last_tool_invoked_at"
DATA_LAST_TOOL_ERROR = "last_tool_error"
DATA_LAST_TOOL_RESULT_PREVIEW = "last_tool_result_preview"

# Platforms
PLATFORMS = ["sensor", "binary_sensor", "conversation"]

# Events
EVENT_MESSAGE_RECEIVED = f"{DOMAIN}_message_received"
EVENT_TOOL_INVOKED = f"{DOMAIN}_tool_invoked"

# Services
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_CLEAR_HISTORY = "clear_history"
SERVICE_INVOKE_TOOL = "invoke_tool"

# Attributes
ATTR_MESSAGE = "message"
ATTR_SESSION_ID = "session_id"
ATTR_ATTACHMENTS = "attachments"
ATTR_MODEL = "model"
ATTR_TIMESTAMP = "timestamp"
ATTR_TOOL = "tool"
ATTR_ACTION = "action"
ATTR_ARGS = "args"
ATTR_SESSION_KEY = "session_key"
ATTR_DRY_RUN = "dry_run"
ATTR_MESSAGE_CHANNEL = "message_channel"
ATTR_ACCOUNT_ID = "account_id"
ATTR_OK = "ok"
ATTR_RESULT = "result"
ATTR_ERROR = "error"
ATTR_DURATION_MS = "duration_ms"

# API endpoints
# The OpenClaw gateway exposes only the OpenAI-compatible endpoints.
# /api/status and /api/sessions do not exist — the gateway returns its SPA
# home page (text/html) for any unrecognised route.
API_MODELS = "/v1/models"
API_CHAT_COMPLETIONS = "/v1/chat/completions"
API_TOOLS_INVOKE = "/tools/invoke"
