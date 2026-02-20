# OpenClaw Integration for Home Assistant

A native Home Assistant integration for communicating with the
[OpenClaw Assistant](https://github.com/techartdev/OpenClawHomeAssistant) addon.

## Features

- **Chat card** — Lovelace card with streaming AI responses, file attachments, and voice mode
- **Sensors** — `openclaw_status`, `openclaw_model`, `openclaw_session_count`, `openclaw_last_activity`, `openclaw_connected`
- **Conversation agent** — appears in Assist & Voice PE as a native agent
- **Service calls** — `openclaw.send_message` for automations
- **Events** — `openclaw_message_received` for triggering automations from AI responses
- **Zero-config** — auto-discovers the addon via Supervisor API, no tokens or URLs to enter

## Installation

### HACS (recommended)

1. Open HACS → Integrations → **+ Explore & Download Repositories**
2. Search for **OpenClaw** and install
3. Restart Home Assistant
4. Go to Settings → Devices & Services → **Add Integration → OpenClaw**

### Manual

1. Copy `custom_components/openclaw/` into your HA `config/custom_components/` directory
2. Copy `www/openclaw-chat-card.js` into `config/www/`
3. Restart Home Assistant
4. Add the integration via Settings → Devices & Services

## Prerequisites

The **OpenClaw Assistant** addon must be installed and running.  
The integration will auto-detect it — no manual configuration needed.

## Chat Card

The chat card is registered automatically when the integration loads — no
manual resource configuration needed. Just add it to any dashboard:

```yaml
type: custom:openclaw-chat-card
```

## Services

### `openclaw.send_message`

Send a message to OpenClaw from an automation or script.

```yaml
service: openclaw.send_message
data:
  message: "What's the weather like today?"
  session_id: "optional-session-id"
```

### `openclaw.clear_history`

```yaml
service: openclaw.clear_history
data:
  session_id: "optional-session-id"
```

## Events

### `openclaw_message_received`

Fired whenever OpenClaw sends a response. Use in automations:

```yaml
trigger:
  - platform: event
    event_type: openclaw_message_received
action:
  - service: notify.mobile_app
    data:
      message: "{{ trigger.event.data.message }}"
```

## License

See [LICENSE](../LICENSE).
