# Changelog

All notable changes to the OpenClaw Home Assistant Integration will be documented in this file.

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
