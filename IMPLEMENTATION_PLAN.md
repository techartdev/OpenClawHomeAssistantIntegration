# OpenClaw Integration — Implementation Plan

## 1. Overview

This document describes the architecture and phased implementation plan for the
**OpenClaw Integration** — a native Home Assistant custom integration that acts as
a satellite companion to the existing **OpenClaw Assistant** addon.

### Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Chat card (text, streaming, files, voice) embedded in HA dashboard | P0 |
| 2 | Sensor / binary-sensor entities for status, model, sessions | P0 |
| 3 | Bidirectional addon ↔ integration communication (zero manual setup) | P0 |
| 4 | Native HA conversation agent (Assist / Voice PE) | P1 |
| 5 | Service calls & events for automations | P1 |
| 6 | Media player entity for TTS output | P2 |

---

## 2. Existing Addon — Key Facts

| Property | Value |
|----------|-------|
| Slug | `openclaw_assistant_dev` |
| Gateway port | `18789` (configurable via `gateway_port`) |
| Auth | Token-based (`gateway.auth.token` in `openclaw.json`) |
| Config file | `/config/.openclaw/openclaw.json` (addon container) |
| OpenAI-compatible endpoint | `POST /v1/chat/completions` (opt-in via `enable_openai_api`) |
| Gateway bind | `127.0.0.1` (loopback) or `0.0.0.0` (lan) |
| Node process | `openclaw gateway run` |
| Ingress port | `48099` (nginx) |

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Home Assistant Core                    │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Sensors /   │  │ Conversation │  │  Services /    │  │
│  │  Binary      │  │ Agent        │  │  Events        │  │
│  │  Sensors     │  │ (Assist/VPE) │  │                │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘  │
│         │                 │                   │           │
│         └────────┬────────┴───────────────────┘           │
│                  │                                        │
│          ┌───────▼────────┐                               │
│          │  OpenClawAPI   │  (api.py — HTTP client)       │
│          │  Client        │                               │
│          └───────┬────────┘                               │
│                  │ HTTP / SSE                              │
├──────────────────┼────────────────────────────────────────┤
│                  │                                        │
│  ┌───────────────▼──────────────────────────────┐         │
│  │         OpenClaw Gateway  (addon)            │         │
│  │                                              │         │
│  │  /v1/chat/completions   (SSE streaming)      │         │
│  │  /api/status            (JSON)               │         │
│  │  /api/sessions          (JSON)               │         │
│  │  /api/models            (JSON)               │         │
│  └──────────────────────────────────────────────┘         │
│                                                           │
│              OpenClaw Assistant Addon Container            │
└───────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│           Lovelace Dashboard                │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │       openclaw-chat-card               │ │
│  │  ┌──────────────────────────────────┐  │ │
│  │  │  Message history (markdown)      │  │ │
│  │  │  Typing indicator                │  │ │
│  │  │  File / image attachments        │  │ │
│  │  │  Voice input button              │  │ │
│  │  │  Voice mode toggle               │  │ │
│  │  └──────────────────────────────────┘  │ │
│  └────────────────────────────────────────┘ │
│       ▲                                     │
│       │  HA WebSocket API                   │
│       │  (openclaw.send_message service)    │
│       │  + event subscriptions              │
└───────┼─────────────────────────────────────┘
        │
        ▼
   Home Assistant Core (services / events)
```

### 3.1 Auto-Discovery (Zero-Config)

The integration discovers the addon with **no manual setup** using two mechanisms:

1. **Supervisor API** — at config-flow time the integration calls
   `GET /addons/openclaw_assistant_dev/info` via the HA Supervisor client.  
   This gives us: addon state, network ports, options.

2. **Shared filesystem** — the addon mounts `/addon_configs/<slug>` which maps
   to `/config` inside the container. The integration can read  
   `openclaw.json` to get the gateway auth token, mode, and port.

**Net effect:** the user clicks "Add Integration → OpenClaw" and everything
connects automatically — no token or URL entry required.

### 3.2 Communication Protocol

| Direction | Transport | Endpoint / Mechanism |
|-----------|-----------|----------------------|
| Integration → Chat | HTTP POST + SSE stream | `/v1/chat/completions` (OpenAI compat) |
| Integration → Status | HTTP GET (polled every 30 s) | `/api/status` |
| Integration → Sessions | HTTP GET (polled every 60 s) | `/api/sessions` |
| Integration → Models | HTTP GET (on startup + hourly) | `/v1/models` |
| Addon → HA (events) | HA REST API (long-lived token) | `POST /api/events/openclaw_*` |
| Frontend → Integration | HA WebSocket API | service calls + event subscriptions |

### 3.3 Latency Budget (Voice Mode)

| Step | Target | Notes |
|------|--------|-------|
| STT (browser/HA) | ≤ 500 ms | WebSpeech API or Whisper via HA |
| Network to OpenClaw | ≤ 100 ms | localhost or LAN |
| OpenClaw inference | ≤ 1500 ms | First token via SSE stream |
| TTS | ≤ 500 ms | HA `tts.speak` or browser SpeechSynthesis |
| **Total** | **≤ 2600 ms** | Under 3 s target |

---

## 4. File Structure

```
openclaw_integration/
├── IMPLEMENTATION_PLAN.md          ← this file
├── hacs.json                       ← HACS metadata
├── README.md
│
├── custom_components/
│   └── openclaw/
│       ├── __init__.py             ← integration setup, coordinator
│       ├── manifest.json           ← HA integration manifest
│       ├── config_flow.py          ← auto-discovery config flow
│       ├── const.py                ← constants, defaults
│       ├── api.py                  ← OpenClaw gateway HTTP client
│       ├── coordinator.py          ← DataUpdateCoordinator for polling
│       ├── sensor.py               ← sensor entities
│       ├── binary_sensor.py        ← binary sensor entities
│       ├── conversation.py         ← native conversation agent
│       ├── services.py             ← service call handlers
│       ├── services.yaml           ← service definitions
│       ├── strings.json            ← English UI strings
│       └── translations/
│           └── en.json             ← English translations
│
└── www/
    └── openclaw-chat-card.js       ← Lovelace custom card (Lit)
```

---

## 5. Phased Implementation

### Phase 1 — Foundation (MVP)

**Goal:** Integration installs, auto-discovers addon, exposes sensors.

| Task | File(s) | Description |
|------|---------|-------------|
| 1.1 | `manifest.json` | Integration metadata, dependencies |
| 1.2 | `const.py` | Domain, default ports, config keys |
| 1.3 | `api.py` | `OpenClawApiClient` — HTTP client to gateway |
| 1.4 | `config_flow.py` | Auto-discovery via Supervisor + shared config |
| 1.5 | `coordinator.py` | `DataUpdateCoordinator` polling status/sessions/model |
| 1.6 | `__init__.py` | Integration setup, platforms, coordinator init |
| 1.7 | `sensor.py` | `openclaw_status`, `openclaw_last_activity`, `openclaw_session_count`, `openclaw_model` |
| 1.8 | `binary_sensor.py` | `openclaw_connected` |
| 1.9 | `strings.json`, `translations/en.json` | UI text |
| 1.10 | `hacs.json` | HACS configuration |

**Acceptance criteria:**
- `Add Integration → OpenClaw` works with zero config
- All 5 entities appear and update
- Integration reconnects gracefully when addon restarts

### Phase 2 — Services, Events & Conversation Agent

**Goal:** Automations can send/receive messages; Assist pipeline works.

| Task | File(s) | Description |
|------|---------|-------------|
| 2.1 | `services.yaml`, `services.py` | `openclaw.send_message`, `openclaw.clear_history` |
| 2.2 | `__init__.py` (update) | Fire `openclaw_message_received` HA event on response |
| 2.3 | `conversation.py` | Register as `conversation` agent |
| 2.4 | `api.py` (update) | SSE streaming support (`async for` over response chunks) |
| 2.5 | Testing | Verify Assist Text/Voice pipeline end-to-end |

**Acceptance criteria:**
- `openclaw.send_message` callable from automations
- `openclaw_message_received` event fires and can trigger automations
- OpenClaw appears in Assist agent picker
- Voice PE works: wake word → STT → OpenClaw → TTS → speaker

### Phase 3 — Chat Card (Frontend)

**Goal:** Full chat UI as a Lovelace custom card.

| Task | File(s) | Description |
|------|---------|-------------|
| 3.1 | `openclaw-chat-card.js` | Base card shell (Lit element, card config) |
| 3.2 | (continued) | Message history with timestamps, markdown rendering |
| 3.3 | (continued) | Streaming response display (typing indicator) |
| 3.4 | (continued) | File/image attachment support (upload via service) |
| 3.5 | (continued) | Voice input (WebSpeech/MediaRecorder → send audio) |
| 3.6 | (continued) | Voice mode toggle (continuous listen → auto-respond with TTS) |
| 3.7 | `__init__.py` (update) | Register card as Lovelace resource |
| 3.8 | Card editor | Visual card configuration editor |

**Acceptance criteria:**
- Card renders chat history with markdown
- Real-time streaming of AI responses
- File upload works in both directions
- Voice input captures and sends audio
- Voice mode maintains continuous conversation

### Phase 4 — Media Player & Polish

**Goal:** Native TTS output, wake word integration, production hardening.

| Task | File(s) | Description |
|------|---------|-------------|
| 4.1 | `media_player.py` | Media player entity for TTS output routing |
| 4.2 | | Wake word detection integration |
| 4.3 | | WebSocket connection management (token refresh, reconnect) |
| 4.4 | | Error handling, rate limiting, connection pooling |
| 4.5 | | Performance profiling (voice latency budget) |
| 4.6 | | Documentation and HACS submission |

---

## 6. Entity Reference

### Sensors

| Entity ID | Class | State | Attributes |
|-----------|-------|-------|------------|
| `sensor.openclaw_status` | — | `online` / `offline` / `processing` | `gateway_version`, `uptime` |
| `sensor.openclaw_last_activity` | `timestamp` | ISO 8601 datetime | `last_message_preview` |
| `sensor.openclaw_session_count` | — | integer (active count) | `sessions` (list of IDs) |
| `sensor.openclaw_model` | — | model name string | `provider`, `context_window` |

### Binary Sensors

| Entity ID | Class | State |
|-----------|-------|-------|
| `binary_sensor.openclaw_connected` | `connectivity` | `on` / `off` |

### Services

| Service | Fields | Description |
|---------|--------|-------------|
| `openclaw.send_message` | `message` (str), `session_id` (str, optional), `attachments` (list, optional) | Send a message to OpenClaw |
| `openclaw.clear_history` | `session_id` (str, optional) | Clear conversation history |

### Events

| Event | Data | Description |
|-------|------|-------------|
| `openclaw_message_received` | `message`, `session_id`, `model`, `timestamp` | Fired when OpenClaw sends a response |

---

## 7. Key Technical Decisions

### 7.1 Why HTTP+SSE instead of WebSocket?

- The addon already exposes an **OpenAI-compatible** HTTP endpoint with SSE streaming
- No additional gateway code needed on the addon side
- SSE is simpler to manage (no bi-directional state, automatic reconnect)
- WebSocket can be added later for real-time push features

### 7.2 Why Supervisor API for discovery?

- Available in all HAOS / Supervised installs (target audience)
- Provides addon state, network config, and options without filesystem access
- Filesystem fallback (`/addon_configs/`) handles edge cases

### 7.3 Why register as a conversation agent?

- Native Assist integration = works with Voice PE, S3 satellite, etc.
- No need for third-party HACS integrations (Extended OpenAI Conversation)
- Event-driven: HA handles STT/TTS pipeline, we just process text

### 7.4 Frontend card communication

- Card uses HA WebSocket API (already authenticated)
- Calls `openclaw.send_message` service
- Subscribes to `openclaw_message_received` events
- No separate WebSocket to gateway needed (avoids CORS, auth issues)

---

## 8. Challenges & Mitigations

| Challenge | Mitigation |
|-----------|------------|
| Gateway not reachable (loopback bind) | Integration runs in same host; `127.0.0.1` works. Document `lan` mode for remote setups. |
| Token rotation / mismatch | Re-read `openclaw.json` on connection failure; config flow stores token in HA config entry |
| Voice latency > 3s | Use SSE streaming (first token fast), browser-side SpeechSynthesis for TTS, Whisper locally for STT |
| Addon not installed | Config flow gracefully fails with a message directing user to install the addon first |
| HACS distribution | Standard HACS custom integration + Lovelace card resources |
| Large file uploads | Chunk uploads through service call; gateway handles multipart |

---

## 9. Dependencies

### Python (integration)

| Package | Purpose | In HA? |
|---------|---------|--------|
| `aiohttp` | HTTP client for gateway API | ✅ built-in |
| `homeassistant` | HA core APIs | ✅ built-in |

### JavaScript (frontend card)

| Library | Purpose | Bundled? |
|---------|---------|----------|
| `lit` | Web component framework | ✅ available via HA |
| `marked` | Markdown rendering | Bundle in card JS |

No additional pip dependencies required — the integration uses only HA built-ins.

---

## 10. Testing Strategy

| Level | Tool | Coverage |
|-------|------|----------|
| Unit | `pytest` + `pytest-homeassistant-custom-component` | API client, coordinator, config flow |
| Integration | HA dev container with addon mock | End-to-end entity updates, service calls |
| Frontend | Manual + Playwright | Card rendering, streaming, voice |

---

## 11. Timeline Estimate

| Phase | Duration | Milestone |
|-------|----------|-----------|
| Phase 1 | 1–2 weeks | Sensors visible, auto-discovery works |
| Phase 2 | 1–2 weeks | Conversation agent in Assist, services/events |
| Phase 3 | 2–3 weeks | Chat card MVP (text + streaming + files) |
| Phase 4 | 2–3 weeks | Voice mode, media player, polish |

**Total estimated: 6–10 weeks to full feature set.**
