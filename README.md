# OpenClaw Integration for Home Assistant (Fork)

> **Forked from [techartdev/OpenClawHomeAssistantIntegration](https://github.com/techartdev/OpenClawHomeAssistantIntegration)** with additional features for room-aware voice responses, improved entity context, and community PR merges.

---

## Fork Changes

This fork adds the following on top of the upstream integration:

### Room-Aware Voice Responses
- Resolves the originating voice satellite's area from the HA device/area registry
- Injects `[Voice command from: <room>]` into the system prompt so the agent knows which room you're in
- Sends `x-openclaw-area` and `x-openclaw-device-id` headers for structured access
- "Turn off the lights" and "what's the temperature in here?" target the correct room automatically

### Richer Entity Context
- Entity context now includes area assignments, useful state attributes (brightness, temperature, volume, media info), and current date/time
- Significantly improves device control accuracy for LLM-based agents

### Merged Community PRs
- **PR #9** (dalehamel) -- opt-in debug logging for API request tracing
- **PR #10** (dalehamel) -- sticky sessions and agent routing fix (resolves upstream Issue #8)
- **PR #11** (L0rz) -- `continue_conversation` for Voice PE follow-up dialog

### Code Quality
- Shared utility module (`utils.py`) -- extracted duplicated methods
- Granular error codes -- `FAILED_TO_HANDLE` for connection/auth errors instead of `UNKNOWN`
- API client retry logic for transient connection failures
- Improved session management logging

---

## Installation via HACS

1. Open **HACS -> Integrations**
2. Click the **three-dot menu** -> **Custom repositories**
3. Add repository URL: `https://github.com/DarrenBenson/OpenClawHomeAssistantIntegration`
4. Category: **Integration**
5. Click **Add**, then **Download**
6. Restart Home Assistant
7. Go to **Settings -> Devices & Services -> Add Integration -> OpenClaw**

---

## What It Includes

- **Conversation agent** (`openclaw`) in Assist / Voice Assistants
- **Lovelace chat card** (`custom:openclaw-chat-card`) with message history, typing indicator, optional voice input, wake-word handling
- **Services:** `openclaw.send_message`, `openclaw.clear_history`, `openclaw.invoke_tool`
- **Events:** `openclaw_message_received`, `openclaw_tool_invoked`
- **Sensors / status entities** for model and connection state, including tool telemetry

---

## Requirements

- Home Assistant Core `2025.1.0+`
- An **OpenClaw gateway** with `enable_openai_api` enabled -- either:
  - The [OpenClaw Assistant addon](https://github.com/techartdev/OpenClawHomeAssistant) running on the same HA instance, **or**
  - Any standalone [OpenClaw](https://github.com/openclaw/openclaw) installation reachable over the network

> **No addon required.** If you have OpenClaw running anywhere -- on a separate server, a VPS, a Docker container, or another machine on your LAN -- this integration can connect to it via the manual configuration flow.

---

## Connection Modes

### Local addon (auto-discovery)

If the OpenClaw Assistant addon is installed on the **same** Home Assistant instance, the integration auto-discovers it -- no manual config needed.

### Remote or standalone OpenClaw instance (manual config)

Connect to **any reachable OpenClaw gateway**. You need:

1. `enable_openai_api` enabled on the OpenClaw instance
2. Network reachability from HA
3. The gateway auth token (`openclaw config get gateway.auth.token`)

| Scenario | Host | Port | SSL | Verify SSL |
|---|---|---|---|---|
| Standalone (LAN) | Remote IP | 18789 | No | -- |
| `lan_https` (addon HTTPS proxy) | Remote IP | 18789 | Yes | No |
| Reverse proxy (Let's Encrypt) | Domain | 443 | Yes | Yes |
| Tailscale | Tailscale IP | 18789 | No | -- |

---

## Integration Options

Open **Settings -> Devices & Services -> OpenClaw -> Configure**.

### Context
- **Include exposed entities context** -- sends entity states to the agent
- **Max context characters** -- limit context size
- **Context strategy** -- `truncate` or `clear` when exceeding max length

### Agent Routing
- **Agent ID** -- default OpenClaw agent (e.g. `main`)
- **Voice agent ID** -- agent for voice pipeline requests (e.g. `voice`)
- **Assist session ID override** -- fixed session key for voice (e.g. `ha-voice-assist`)

### Debug
- **Debug logging** -- log agent ID, session ID, and area for each request

### Voice (Lovelace card)
- **Wake word enabled/word** -- for continuous voice mode in the card
- **Voice input provider** -- `browser` (Web Speech) or `assist_stt` (HA STT)

---

## Services

### `openclaw.send_message`

```yaml
service: openclaw.send_message
data:
  message: "Turn on the living room lights"
  session_id: "living-room-session"
```

### `openclaw.clear_history`

```yaml
service: openclaw.clear_history
data:
  session_id: "living-room-session"
```

### `openclaw.invoke_tool`

```yaml
service: openclaw.invoke_tool
data:
  tool: sessions_list
  action: json
  args: {}
  session_key: main
```

---

## Events

### `openclaw_message_received`

```yaml
trigger:
  - platform: event
    event_type: openclaw_message_received
action:
  - service: notify.mobile_app_phone
    data:
      message: "{{ trigger.event.data.message }}"
```

### `openclaw_tool_invoked`

```yaml
trigger:
  - platform: event
    event_type: openclaw_tool_invoked
condition:
  - condition: template
    value_template: "{{ trigger.event.data.ok == false }}"
action:
  - service: notify.mobile_app_phone
    data:
      message: "Tool {{ trigger.event.data.tool }} failed: {{ trigger.event.data.error }}"
```

---

## Dashboard Card

Registered automatically by the integration.

```yaml
type: custom:openclaw-chat-card
title: OpenClaw Chat
height: 500px
show_timestamps: true
show_voice_button: true
show_clear_button: true
session_id: default
```

---

## Troubleshooting

- **Card doesn't appear:** Restart HA, hard refresh browser cache
- **Voice not working:** Check browser mic permissions and voice provider setting
- **Tool sensors show Unknown:** Normal until first `openclaw.invoke_tool` call
- **400 Bad Request (HTTPS):** Enable "Use SSL" and disable "Verify SSL" for `lan_https` mode

---

## Upstream

This fork tracks [techartdev/OpenClawHomeAssistantIntegration](https://github.com/techartdev/OpenClawHomeAssistantIntegration). Upstream PRs are merged when compatible.

## Licence

MIT. See [LICENSE](LICENSE).
