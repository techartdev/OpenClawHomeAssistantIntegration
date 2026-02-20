# Changelog

All notable changes to the OpenClaw Home Assistant Integration will be documented in this file.

## [0.1.23] - 2026-02-20

### Fixed
- Improved handling for repeated `SpeechRecognition` `network` failures in Brave-like browsers.
- Added clear in-card status when browser speech backend appears blocked, and stopped endless retry loops in that case.
- Kept automatic locale fallback retry for transient speech-service issues.

## [0.1.22] - 2026-02-20

### Fixed
- Improved speech-recognition language handling by normalizing language tags (e.g. `bg` → `bg-BG`).
- Added automatic fallback retry with browser locale on `SpeechRecognition` `network` errors.
- Updated versioned card resource URL to force clients to load the latest voice handling logic.

## [0.1.21] - 2026-02-20

### Fixed
- Added automatic cleanup of duplicate/legacy OpenClaw Lovelace resources (`/local/...`, unversioned `/openclaw/...`, `/hacsfiles/...`) so only the current versioned resource is kept.
- Prevents loading multiple OpenClaw card generations (`v0.2.0` + `v0.2.1`) at the same time.

## [0.1.20] - 2026-02-20

### Changed
- Added versioned card resource URL (`/openclaw/openclaw-chat-card.js?v=...`) to reduce stale frontend caching issues.
- Added runtime source diagnostics (`import.meta.url`) in card console output to verify which script file is actually loaded.
- Updated root loader shim to import versioned card bundle URL.

## [0.1.19] - 2026-02-20

### Changed
- Made `custom_components/openclaw/www/openclaw-chat-card.js` the single source of truth for card implementation.
- Replaced root `www/openclaw-chat-card.js` with a tiny loader shim that imports `/openclaw/openclaw-chat-card.js`.
- Removed manual-maintenance duplication between two full card script files.

## [0.1.18] - 2026-02-20

### Fixed
- Voice input now requires wake word only for continuous voice mode, not for manual mic usage.
- Added in-card voice status feedback (listening, wake-word wait, sending, error) to make microphone behavior visible.
- Improved handling for unsupported speech-recognition browsers with explicit UI status.

## [0.1.17] - 2026-02-20

### Fixed
- Improved chat history recovery after leaving and returning to dashboard.
- Card now retries backend history sync when websocket is not yet ready.
- History merge now updates when message count is unchanged but latest message content/timestamp differs.

## [0.1.16] - 2026-02-20

### Added
- Added configurable wake-word support in integration options.
- Added optional always-on voice mode in integration options.
- Added websocket settings endpoint (`openclaw/get_settings`) used by the chat card to apply integration-level voice settings.

### Changed
- Chat card voice recognition now supports two modes:
  - Manual voice input without wake word
  - Continuous listening with required wake word

## [0.1.15] - 2026-02-20

### Added
- Added integration options for prompt/context behavior:
  - Include exposed-entities context
  - Max context characters
  - Context overflow strategy (`truncate` or `clear`)
  - Enable tool calls (`execute_service` / `execute_services`)

### Changed
- Service and conversation requests now apply configurable context policy before sending prompts.
- Optional tool-call execution now mirrors Extended OpenAI-style service tool usage and feeds execution results back into a follow-up model response.

## [0.1.14] - 2026-02-20

### Fixed
- Fixed Assist exposure context lookup to use Home Assistant's conversation assistant identifier (`conversation`) instead of `assist`, which could result in empty exposed-entity context.
- Added backend in-memory chat history and websocket endpoint (`openclaw/get_history`) so card responses are recoverable after leaving and returning to the dashboard.
- Normalized default session handling to `default` for service calls/events/history, avoiding session mismatch drops.

### Changed
- Chat card now syncs history from backend on mount/initialization to restore missed assistant messages.

## [0.1.13] - 2026-02-20

### Added
- Added native Home Assistant Assist entity exposure support to OpenClaw requests.
- OpenClaw now includes context for entities exposed in **Settings → Voice assistants → Expose**.

### Changed
- Service chat (`openclaw.send_message`) and conversation agent (streaming + fallback) now pass exposed-entities context as a system prompt.

## [0.1.12] - 2026-02-20

### Fixed
- Improved response parsing for nested/modern OpenAI-compatible payloads (including `output` / nested `content` shapes), which could previously result in missing UI replies.
- Applied the same recursive extraction strategy to both service-based chat responses and Assist conversation fallback parsing.

## [0.1.11] - 2026-02-20

### Fixed
- Chat card no longer waits forever when the gateway returns a non-`choices[0].message.content` response shape.
- `openclaw.send_message` now extracts assistant text from multiple OpenAI-compatible formats (`choices`, `output_text`, `response`, `message`, `content`, `answer`).
- Added fallback event emission on API errors so the frontend always receives a response and exits the typing state.

## [0.1.10] - 2026-02-20

### Fixed
- Made custom card registration idempotent (`customElements.get(...)` guards) to prevent duplicate-load exceptions that can block card discovery.
- Prevented duplicate `window.customCards` entries for `openclaw-chat-card`.
- Synced registration hardening in both packaged and root `www/` card scripts.

## [0.1.9] - 2026-02-20

### Fixed
- Updated Lovelace resource registration to use Home Assistant 2026.2 storage API (`hass.data[LOVELACE_DATA].resources`) with legacy fallback.
- Prevented silent resource-registration failure caused by reading the old `hass.data["lovelace"]` key only.

### Changed
- Updated `hacs.json` minimum Home Assistant version to `2026.2.0`.

## [0.1.8] - 2026-02-20

### Fixed
- Removed false-positive config-flow warning for `enable_openai_api=false` when Supervisor options are missing or use a different schema.
- Frontend auto-registration no longer gets stuck after an early startup failure.
- Card resource registration now retries for longer and can recover on integration reload.

### Changed
- Frontend registration task is now de-duplicated while running and marked complete only after successful Lovelace resource creation.

## [0.1.7] - 2026-02-20

### Fixed
- Resolved chat card startup race where Lovelace resources were attempted before HTTP/Lovelace were ready, causing `Custom element not found: openclaw-chat-card`.
- Frontend registration now retries and waits for Home Assistant startup readiness before giving up.
- Static JS path registration is now idempotent and only marked successful after the path is actually registered.

### Added
- Added MIT license file at repository root (`LICENSE`).

## [0.1.6] - 2025-01-01

### Fixed
- Integration "Not loaded" state caused by `hass.http.register_static_path()` being called in `async_setup` before the HTTP server is ready
- Removed `async_setup` and the synchronous `_async_register_static_path` helper
- `_async_register_frontend` is now a proper `async` function, safe to fire-and-forget from `async_setup_entry`
- Supports both the HA 2024.11+ `async_register_static_paths` / `StaticPathConfig` API and the legacy `register_static_path` API with automatic fallback to `/local/` URL
- Frontend registration errors are caught and logged as warnings — they can never crash the integration load

---

## [0.1.5] - 2026-02-20

### Added
- **Automatic Lovelace resource registration** — the chat card JS is now served
  directly from inside the integration package (`custom_components/openclaw/www/`)
  via a registered static HTTP path at `/openclaw/openclaw-chat-card.js`. The
  integration also adds it to Lovelace's resource store automatically on first
  setup. No manual "Add resource" step is required.
- `async_setup()` registered so the static path is available before any config
  entry setup runs.
- `lovelace` added to `after_dependencies` so Lovelace is ready when we attempt
  to register the resource.

### Changed
- `openclaw-chat-card.js` is now shipped inside `custom_components/openclaw/www/`
  (in addition to the top-level `www/` for backward compatibility with HACS installs
  that copy files to `config/www/`).
- If programmatic Lovelace registration fails (e.g. Lovelace not loaded), a clear
  warning with manual fallback instructions is logged instead of silently doing nothing.

## [0.1.4] - 2026-02-20

### Fixed
- **Connection probe no longer uses `/v1/models`** — the OpenClaw gateway does
  not implement that endpoint (only `/v1/chat/completions` is registered when
  `enable_openai_api` is enabled). Unrecognised routes fall through to the SPA
  catch-all and return HTML, which caused every connection check to fail with
  `openai_api_disabled` even when the API was actually enabled.
- `async_check_connection()` now POSTs to `/v1/chat/completions` with an empty
  messages body. The gateway's auth middleware validates the token first, then
  the endpoint returns a JSON error for the invalid body — proving server is
  reachable, API is enabled, and the token is accepted. No LLM call is made.
- Coordinator polling now uses `async_check_alive()` (lightweight base-URL GET)
  for connectivity, with `async_get_models()` as a best-effort call that is
  silently ignored if the endpoint doesn't exist.

### Added
- New `async_check_alive()` method — simple HTTP GET to the gateway base URL to
  confirm the gateway process is running (does not verify auth or API status).

## [0.1.3] - 2026-02-20

### Fixed
- `async_check_connection()` no longer silently swallows `OpenClawApiError`.
  Previously any API-level error (e.g. gateway returning HTML) was caught and
  converted to a generic "Cannot connect" message with no indication of the
  real cause. The error is now propagated to the config flow.
- Config flow now catches `OpenClawApiError` separately and shows a clear,
  actionable error message: **"openai_api_disabled"** — pointing the user to
  enable `enable_openai_api` in the addon settings and restart.
- Auto-discovery now logs a `WARNING` when `enable_openai_api` is `false` in
  the addon options, making the issue visible in the HA log before setup fails.

### Changed
- The `enable_openai_api` addon option (default `false`) must be `true` for the
  integration to connect. The `/v1/models` probe endpoint requires the
  OpenAI-compatible API layer to be active.

## [0.1.2] - 2026-02-20

### Fixed
- Removed non-existent `/api/status` and `/api/sessions` gateway endpoints that caused
  the integration to receive HTML pages instead of JSON, resulting in `ContentTypeError`
  on every poll and a failed config flow connection check.
- `async_check_connection()` now probes `/v1/models` (the only reliable GET endpoint on
  the gateway) instead of the missing `/api/status`.

### Changed
- `DataUpdateCoordinator` now performs a single `/v1/models` request per poll cycle
  instead of three separate requests (`/api/status`, `/api/sessions`, `/v1/models`).
- `DATA_GATEWAY_VERSION`, `DATA_UPTIME`, `DATA_SESSION_COUNT`, and `DATA_SESSIONS`
  report unavailable values (`None` / `0` / `[]`) since the gateway does not expose
  dedicated status or session endpoints.
- Removed `_model_poll_counter` (no longer needed with a unified poll).

### Added
- Integration icon and logo (sourced from the OpenClaw Assistant add-on).

## [0.1.1] - 2026-02-20

### Fixed
- Added content-type guard in `_request()`: when the gateway returns a non-JSON
  response (e.g. HTML redirect/login page), a clear `OpenClawApiError` is now raised
  instead of an unhandled `aiohttp.ContentTypeError`.

## [0.1.0] - 2026-02-20

### Added
- Initial release of the OpenClaw Home Assistant Integration.
- Config flow with automatic add-on discovery and manual host/port/token entry.
- `sensor` platform: Status, Last Activity, Session Count, Active Model.
- `binary_sensor` platform: Gateway Connected.
- `conversation` platform: native HA Assist / Voice PE agent backed by the
  OpenClaw gateway `/v1/chat/completions` endpoint (SSE streaming supported).
- `DataUpdateCoordinator` polling the gateway on a configurable interval (default 30 s).
- Service calls: `openclaw.send_message`, `openclaw.clear_history`.
- Lovelace `openclaw-chat-card` custom card (`www/openclaw-chat-card.js`).
- HACS-compatible repository structure (`hacs.json`).
