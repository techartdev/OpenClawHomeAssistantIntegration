# OpenClaw Integration — Implementation Plan

## 1. Scope and current state

This plan reflects the actual implementation status as of release `0.1.34`.

### Project goals

| # | Goal | Priority | Status |
|---|------|----------|--------|
| 1 | Stable HA integration with addon auto-discovery | P0 | ✅ Done |
| 2 | Sensors + binary sensor for gateway visibility | P0 | ✅ Done |
| 3 | Native Assist conversation agent | P0 | ✅ Done |
| 4 | Lovelace chat card (text + voice) | P0 | ✅ Done |
| 5 | Voice provider choice (`browser` / `assist_stt`) | P0 | ✅ Done |
| 6 | Production polish and broad compatibility hardening | P1 | 🚧 In progress |
| 7 | Optional native media player/TTS routing entity | P2 | ⏳ Not started |

---

## 2. Architecture (implemented)

### 2.1 Core backend flow

- Integration communicates with OpenClaw gateway over HTTP.
- Primary chat endpoint: `POST /v1/chat/completions` (OpenAI-compatible).
- Coordinator uses lightweight connectivity checks and model probing with graceful fallback.
- Services and conversation agent share response extraction logic for modern OpenAI-compatible payloads.

### 2.2 Frontend flow

- Card sends chat requests via HA services/websocket (`openclaw.send_message`).
- Card receives replies through HA event subscription (`openclaw_message_received`).
- Backend keeps in-memory history and exposes websocket history sync (`openclaw/get_history`).
- Settings endpoint (`openclaw/get_settings`) provides integration-level card options.

### 2.3 Voice modes

- `browser` provider:
  - Uses `SpeechRecognition` / `webkitSpeechRecognition`.
  - Supports manual mic and continuous voice mode (wake-word flow).
- `assist_stt` provider:
  - Captures local mic audio and sends to HA STT API (`/api/stt/<provider>`).
  - Manual one-shot transcription flow.
  - Provider metadata negotiation for language/sample rate/channels to reduce `415` failures.

---

## 3. Repository map (current)

```
OpenClawHomeAssistantIntegration/
├── IMPLEMENTATION_PLAN.md
├── CHANGELOG.md
├── README.md
├── hacs.json
├── custom_components/
│   └── openclaw/
│       ├── __init__.py
│       ├── api.py
│       ├── binary_sensor.py
│       ├── config_flow.py
│       ├── const.py
│       ├── conversation.py
│       ├── coordinator.py
│       ├── exposure.py
│       ├── manifest.json
│       ├── sensor.py
│       ├── services.yaml
│       ├── strings.json
│       ├── translations/en.json
│       └── www/openclaw-chat-card.js
└── www/openclaw-chat-card.js
```

---

## 4. Implemented milestones

### Milestone A — Integration foundation

- Config flow and options flow.
- Gateway API client and coordinator.
- Sensor + binary sensor platforms.
- HACS-ready packaging.

### Milestone B — Assist + automations

- Conversation agent integration.
- Services: `openclaw.send_message`, `openclaw.clear_history`.
- Event emission: `openclaw_message_received`.
- Compatibility fix for intent response handling across HA versions.

### Milestone C — Chat card reliability

- Auto resource registration and cleanup of duplicate/legacy card resources.
- Versioned card URL strategy to avoid stale cache issues.
- Robust response parsing for multiple OpenAI-compatible response shapes.
- Backend chat history sync to restore UI state after navigation/reload.

### Milestone D — Voice hardening

- Wake word and always voice mode options.
- Brave guard with explicit allow override option.
- Language normalization and preferred Assist pipeline language handling.
- Improved TTS voice/language selection.
- Multi-pending response handling to prevent stuck typing state.
- `assist_stt` provider with negotiated STT metadata.
- `AudioWorkletNode` capture first, with `ScriptProcessorNode` fallback.

---

## 5. Current configuration surface

### Integration options

- Prompt/context behavior options.
- Tool-call execution toggle.
- Wake word + always voice mode.
- Brave web speech override.
- Voice provider selector (`browser` or `assist_stt`).

### Card-level behavior

- Can consume integration settings from websocket settings endpoint.
- Optional card config overrides remain available.

---

## 6. Remaining roadmap (next iterations)

### R1 — Voice provider validation and UX polish (next)

1. Validate `assist_stt` against multiple HA STT providers/languages.
2. Improve surfaced error details when `/api/stt/<provider>` returns non-200.
3. Add optional manual recording duration setting for `assist_stt`.
4. Add provider-specific status text for easier user troubleshooting.

### R2 — Compatibility and resilience

1. Continue hardening for older/newer HA Core API differences.
2. Add broader runtime checks for changed Assist pipeline payload shapes.
3. Expand fallback behavior when pipeline metadata is unavailable.

### R3 — Optional enhancements (after stabilization)

1. Evaluate media-player based TTS routing entity.
2. Explore optional continuous flow for HA STT/TTS pipeline mode.
3. Add automated tests around settings websocket payload and card voice state transitions.

---

## 7. Verification checklist before each release

1. Bump and sync versions in:
   - `custom_components/openclaw/manifest.json`
   - `custom_components/openclaw/__init__.py` (`_CARD_URL`)
   - `www/openclaw-chat-card.js` loader shim
2. Restart HA and hard-refresh dashboard.
3. Confirm browser console reports the expected card version.
4. Validate both providers:
   - `browser`: manual + continuous mode
   - `assist_stt`: manual transcription flow
5. Update `CHANGELOG.md` and `README.md` for any new option/behavior.

---

## 8. Minimum supported environment

- Home Assistant Core: `2025.1.0+` (declared HACS minimum; chosen conservatively for broad compatibility).
- Browser: modern Chromium/Firefox/Safari for card UI; voice capability depends on browser APIs and permissions.
