# Changelog

All notable changes to the OpenClaw Home Assistant Integration will be documented in this file.

## [0.1.44] - 2026-02-21

### Fixed
- Fixed chat-card settings sync to always read latest integration options instead of a potentially stale cached config entry.
- Wake-word disable now applies reliably after unchecking in integration options.
- Browser voice listening status now only shows wake-word requirement when wake word is actually enabled.

## [0.1.43] - 2026-02-21

### Fixed
- Improved Home Assistant Assist conversation continuity by using stable fallback session IDs when `conversation_id` is missing.
- Assist now falls back to per-user (`assist_user_*`) or per-device (`assist_device_*`) session keys instead of a single generic default.

## [0.1.42] - 2026-02-21

### Added
- Added integration option `browser_voice_language` (shown when `voice_provider` is `browser`) to explicitly control browser STT/TTS language.

### Fixed
- Browser voice provider now applies integration-configured browser voice language for both listening and spoken replies.
- Voice replies are no longer spoken for one-shot/manual voice sends unless continuous voice mode is actively running.

## [0.1.41] - 2026-02-20

### Fixed
- Fixed voice-mode option sync so wake-word enabled/disabled changes are reloaded before toggling voice mode.
- Removed legacy always-on voice mode behavior that could force sticky voice-mode state.
- Added live gateway connection badge to the chat card header using existing OpenClaw status entities.

### Changed
- Removed "Always-on voice mode" option from integration options UI and translations.

## [0.1.40] - 2026-02-20

### Added
- Added OpenClaw Gateway tools endpoint integration (`POST /tools/invoke`) in the API client.
- Added new Home Assistant service `openclaw.invoke_tool` with support for tool/action/args/session routing fields.
- Added new event `openclaw_tool_invoked` for automation hooks on tool execution results.
- Added tool telemetry sensors: last tool name, status, duration, and invocation timestamp.

### Changed
- Coordinator now performs a best-effort `sessions_list` tool invocation to populate session count/list when available.

## [0.1.39] - 2026-02-20

### Fixed
- Aligned gateway chat requests with OpenClaw session behavior by sending OpenAI `user` with the stable session ID.
- Added `x-openclaw-session-key` request header for explicit session routing on OpenClaw gateways.
- Improves multi-turn continuity where `/v1/chat/completions` would otherwise default to stateless per-request sessions.
- Removed per-request chat-history replay to avoid unnecessary prompt growth when gateway session memory is active.

## [0.1.37] - 2026-02-20

### Fixed
- Improved conversation continuity by sending `session_id` in chat completion JSON payloads (in addition to `X-Session-Id` header), for both regular and streaming requests.
- Reduces cases where the gateway treats each message as a new conversation when custom headers are ignored upstream.

## [0.1.36] - 2026-02-20

### Fixed
- Voice mode now auto-falls back to browser speech when `voice_provider` is `assist_stt`, instead of blocking continuous mode with an error message.
- Reduced duplicated assistant replies in the chat card by deduplicating repeated `openclaw_message_received` payloads.

## [0.1.35] - 2026-02-20

### Fixed
- Improved chat-card reliability when using voice send flow by re-subscribing to `openclaw_message_received` after card reconnects.
- Added backend history-sync fallback after message send so user/assistant messages still appear when an event is missed.

## [0.1.34] - 2026-02-20

### Changed
- Assist STT microphone capture now uses `AudioWorkletNode` when available, with automatic fallback to `ScriptProcessorNode` for older browsers.
- Reduced browser deprecation noise by avoiding `ScriptProcessorNode` on modern browser engines.

### Documentation
- Expanded README voice documentation with practical guidance for `voice_provider` (`browser` vs `assist_stt`) and provider-specific troubleshooting.

### Changed
- Lowered declared HACS minimum Home Assistant Core version to `2025.1.0` after compatibility hardening updates.

## [0.1.33] - 2026-02-20

### Fixed
- Reduced `415 Unsupported Media Type` failures for `assist_stt` by fetching STT provider capabilities and negotiating metadata before upload.
- Assist STT now auto-matches provider-supported language values (for example `bg` vs `bg-BG`) when submitting transcription audio.
- Assist STT now aligns upload metadata sample rate/channels with provider-supported values when available.

## [0.1.32] - 2026-02-20

### Added
- Added configurable voice input provider option: `browser` or `assist_stt`.
- Chat card now supports Home Assistant STT transcription mode (`assist_stt`) for manual mic input.

### Changed
- Voice provider is now exposed through integration settings websocket payload and card configuration handling.
- Continuous voice mode remains available only for browser voice provider.

## [0.1.31] - 2026-02-20

### Fixed
- Fixed Assist pipeline crash during intent recognition on some Home Assistant versions:
  - Replaced `conversation.IntentResponse` / `conversation.IntentResponseErrorCode` usage with `homeassistant.helpers.intent` equivalents in the OpenClaw conversation agent.
  - Resolves `AttributeError: module 'homeassistant.components.conversation' has no attribute 'IntentResponse'`.

## [0.1.30] - 2026-02-20

### Fixed
- Treated `SpeechRecognition` `no-speech` as a normal listening condition instead of an error.
- Reduced voice error noise by avoiding retry scheduling for `no-speech` events.
- Added clearer in-card status text for silence/no-speech scenarios.

## [0.1.29] - 2026-02-20

### Fixed
- Voice language selection now prioritizes the preferred Assist pipeline language (`assist_pipeline/pipeline/list`) instead of only using Home Assistant UI language.
- Added separate TTS language resolution so spoken replies follow Assist pipeline TTS language when available.
- Retained safe fallbacks to integration/UI/browser language when Assist pipeline data is unavailable.

## [0.1.28] - 2026-02-20

### Fixed
- Treat `SpeechRecognition` `aborted` events as expected stop behavior (no error status/no noisy console error) when voice is intentionally stopped.
- Added a stop-request guard to avoid restart/error churn during recognition shutdown.
- Synchronized release versioning so manifest, frontend loader URL, and backend card resource URL all use the same cache-busting version.

## [0.1.27] - 2026-02-20

### Changed
- Improved backward compatibility for older Home Assistant Core builds by removing Python 3.12-only type alias syntax in integration runtime code.
- Added fallback import handling for `ConfigFlowResult` in config flow type hints.

## [0.1.26] - 2026-02-20

### Added
- Added integration option `allow_brave_webspeech` to **Settings → Devices & Services → OpenClaw → Configure**.
- Frontend card now reads this option via `openclaw/get_settings` and applies it automatically.

### Changed
- Card version bumped to `0.2.6` and cache-busting URL updated to `v=0.1.26`.

## [0.1.25] - 2026-02-20

### Fixed
- Voice input language now prioritizes integration/HA locale settings more reliably (including frontend locale fallback), reducing unwanted fallback to English.
- Voice-mode assistant replies now use improved speech synthesis voice selection for the active language and better voice-loading handling.
- Reworked chat pending-response tracking to support multiple in-flight messages without leaving stuck typing indicators.

## [0.1.24] - 2026-02-20

### Fixed
- Added proactive Brave browser guard for card voice input to avoid recurring `SpeechRecognition` `network` failures.
- Voice is now disabled by default on Brave with a clear status message and opt-in override (`allow_brave_webspeech: true`).
- Reduced noisy console output for `network` speech errors.

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
