# OpenClaw Home Assistant Integration — Full Documentation

This guide is a complete setup and usage manual for OpenClaw in Home Assistant.


## 1) What this integration does

OpenClaw connects Home Assistant to your OpenClaw Gateway and gives you:
- A native **Assist conversation agent** (`openclaw`)
- A built-in **chat card** for dashboards
- **Voice input modes** (browser voice and Home Assistant STT)
- **Automation services and events**
- **Status and telemetry sensors**

---

## 2) Before you begin

## Required
- Home Assistant Core **2025.1.0+**
- OpenClaw Assistant addon installed and running, or standalone OpenClaw instance running and available over network
- A valid gateway auth token/password configured in the OpenClaw addon

## Recommended
- HACS installed (for easiest updates)
- Modern browser (Chrome/Edge/Firefox/Safari)
- Microphone permission allowed in browser for your Home Assistant URL, if you want to use voice features

## Important gateway setting
OpenClaw’s OpenAI-compatible endpoint is required by this integration.
In addon settings, confirm chat completions endpoint support is enabled (for your gateway version/settings model).
If you run OpenClaw standalone set `gateway.http.endpoints.chatCompletions.enabled` to `true`

If this endpoint is disabled, chat and connection checks can fail even when the addon is running.

---

## 3) Installation

## Option A — HACS (recommended)
1. Open **HACS → Integrations**.
2. Use the **⋮ menu** (top-right) → **Custom repositories**.
3. Add repository URL: `https://github.com/techartdev/OpenClawHomeAssistantIntegration`
4. Category: **Integration**.
5. Install **OpenClaw**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & Services → Add Integration**.
8. Add **OpenClaw**.

## Option B — Manual installation
1. Copy `custom_components/openclaw` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Add integration from **Settings → Devices & Services**.

---

## 4) Initial setup flow

When adding the integration, it attempts:
1. **Auto-discovery** (if Supervisor/addon metadata is available)
2. **Manual setup** fallback (host/port/token)

If auto-discovery succeeds:
- Confirm discovered host/port
- Submit

If manual setup is needed:
- Enter gateway host
- Enter gateway port
- Enter auth token/password value expected by gateway
- Enable SSL only if your gateway endpoint is HTTPS

After setup, Home Assistant creates OpenClaw entities and services automatically.

---

## 5) Dashboard chat card

The chat card is auto-registered by the integration. You can add it from dashboard card picker.

### Card behavior
- Restores chat history for active session
- Shows typing/thinking indicator
- Supports text and voice interactions
- Shows gateway connection badge in header (`Online`, `Offline`, or `Unknown`)

### Session behavior in the card
- Card uses a session id (default session if not overridden)
- Keep the same session id to continue conversations
- Different session ids isolate conversations
- You can add different chat cards on different dashboards and set different session id, this way you keep them as separate conversations

---

## 6) Voice features (important)

OpenClaw supports two voice input providers:

## A) Browser voice provider
- Uses browser speech recognition APIs, free and doesn't need voice integrations installed in HA
- Supports:
  - Manual mic capture
  - Continuous voice mode
  - Optional wake-word gating

Best for users who want continuous conversational voice mode.

## B) Home Assistant STT provider (`assist_stt`)
- Uses Home Assistant STT pipeline endpoint
- Designed for **manual** voice capture (press mic, speak, transcribe)
- Requires an STT engine configured in Home Assistant Voice settings

### Continuous mode + assist_stt
If continuous voice mode is enabled while provider is `assist_stt`, the card uses browser speech for continuous listening.
This is expected behavior in current architecture. Assist STT does not support continuous audio.

### Wake word setting
- `Wake word enabled` controls whether continuous mode requires wake phrase before sending recognized speech.
- If disabled, continuous mode can send finalized recognized phrases directly.
- Wake-word logic applies to continuous mode behavior, not manual one-shot mic usage.

### Browser notes
- Brave may produce speech backend errors depending on environment/policies.
- Chrome/Edge are often more consistent for browser speech APIs.

---

## 7) Integration options (Configure screen)

Path: **Settings → Devices & Services → OpenClaw → Configure**

### Context options
- **Include exposed entities context**
  - Adds context from entities exposed to voice assistant.
- **Max context characters**
  - Safety limit for injected context size.
- **Context strategy**
  - `truncate`: keep beginning up to max
  - `clear`: drop context when too large

### Tool-call option
- **Enable tool calls (execute services)**
  - Allows supported tool-call responses to execute Home Assistant services.
  - Keep disabled if you prefer read-only assistant behavior.

### Voice options
- **Wake word enabled**
- **Wake word**
- **Allow Web Speech in Brave (experimental)** (currently may not work, but voice support in Brave is expected in future)
- **Voice input provider** (`browser` or `assist_stt`)

Note: Legacy always-on voice option is removed.

---

## 8) Home Assistant Assist integration

OpenClaw registers as a native Assist conversation agent. This means that you can select OpenClaw as agent in the HA Assist feature and the Assist dialog.

To use:
1. Open Voice Assistants settings.
2. Select OpenClaw as the conversation agent where desired.
3. Ensure exposed entities and pipeline language settings are configured as expected.

If responses are unexpected:
- Check selected conversation agent
- Check exposed entities list
- Confirm pipeline STT/TTS language settings

---

## 9) Services you can use in automations

## `openclaw.send_message`
Use this to send text to OpenClaw from scripts/automations.

Use cases:
- Trigger assistant checks on schedule
- Ask model to summarize state
- Start guided routines

Automation example (scheduled morning summary):

```yaml
alias: OpenClaw Morning Summary
trigger:
  - platform: time
    at: "08:00:00"
action:
  - service: openclaw.send_message
    data:
      message: "Give me a short morning summary for home status and weather."
      session_id: "daily-briefing"
mode: single
```

## `openclaw.clear_history`
Clears stored integration-side history for a specific session (or default/all depending call).

Use cases:
- Reset context for new workflow
- Recover from stale context

Automation example (clear context every night):

```yaml
alias: OpenClaw Clear Night Session
trigger:
  - platform: time
    at: "23:59:00"
action:
  - service: openclaw.clear_history
    data:
      session_id: "daily-briefing"
mode: single
```

## `openclaw.invoke_tool`
Directly invokes one OpenClaw gateway tool through `/tools/invoke`.

Typical fields in UI:
- Tool name
- Action
- Args object
- Session key
- Optional channel/account routing hints

Use cases:
- Admin/diagnostic tool calls
- Session list retrieval
- Controlled operations exposed by gateway policy

Automation example (diagnostic sessions list on startup):

```yaml
alias: OpenClaw Sessions Diagnostic On Start
trigger:
  - platform: homeassistant
    event: start
action:
  - service: openclaw.invoke_tool
    data:
      tool: sessions_list
      action: json
      args: {}
      session_key: main
mode: single
```

Security note:
Tool availability is still controlled by gateway policy and deny-lists.

---

## 10) Events for automations

## `openclaw_message_received`
Fires when OpenClaw sends a response.

Useful for:
- Notifications
- Logging
- Chained automations

Automation example (notify on every assistant reply):

```yaml
alias: OpenClaw Reply Notification
trigger:
  - platform: event
    event_type: openclaw_message_received
action:
  - service: notify.mobile_app_my_phone
    data:
      message: "OpenClaw: {{ trigger.event.data.message }}"
mode: queued
```

## `openclaw_tool_invoked`
Fires after `openclaw.invoke_tool` completes.

Includes success/failure metadata and timing info, useful for:
- Alerting on failed tool runs
- Telemetry dashboards
- Automation branching based on `ok/error`

Automation example (alert on tool failure):

```yaml
alias: OpenClaw Tool Failure Alert
trigger:
  - platform: event
    event_type: openclaw_tool_invoked
condition:
  - condition: template
    value_template: "{{ trigger.event.data.ok == false }}"
action:
  - service: persistent_notification.create
    data:
      title: "OpenClaw Tool Failed"
      message: >-
        Tool: {{ trigger.event.data.tool }}
        Error: {{ trigger.event.data.error }}
        Duration: {{ trigger.event.data.duration_ms }} ms
mode: queued
```

---

## 11) Entities and sensors

## Core status entities
- **Connected** (binary sensor)
- **Status** (`online`/`offline`)
- **Last Activity**
- **Model**
- **Session Count**

## Tool telemetry sensors
- **Last Tool**
- **Last Tool Status**
- **Last Tool Duration**
- **Last Tool Invoked**

### Why some sensors may show `Unknown`
- `Last Tool*` sensors remain `Unknown` until at least one tool invocation completes.
- `Session Count` can remain `0` if tool policy blocks `sessions_list` over HTTP invoke endpoint.

---

## 12) Troubleshooting

## Integration cannot connect
Check:
- Addon is running
- Host/port/token are correct
- Gateway auth mode matches what you entered
- Chat completions endpoint is enabled in gateway settings

## Chat responses missing on card
Check:
- Dashboard loaded latest card resource (hard refresh)
- `openclaw_message_received` event firing
- Session id consistency between message source and card

## Voice issues
Check:
- Browser mic permission for Home Assistant URL
- Correct provider selected (`browser` vs `assist_stt`)
- STT engine configured in HA voice settings (for `assist_stt`)
- Browser compatibility (try Chrome/Edge if Brave is unstable)

## Conversation context seems reset
Check:
- Same session id is used across turns
- Gateway session routing is active
- Gateway policy/routing not forcing isolated sessions

---

## 13) Best practices

- Keep one session id per topic/workflow.
- Use separate sessions for unrelated automations.
- Keep tool calls permissioned and minimal.
- Prefer explicit automations for critical actions.
- Review logs after upgrades and hard-refresh dashboard resources.

---

## 14) Operational checklist (quick)

After install/update:
1. Restart Home Assistant
2. Hard refresh dashboard browser tab
3. Verify OpenClaw entities are available
4. Send one text chat test
5. Test voice provider you plan to use
6. If using tools, run one `invoke_tool` test and verify telemetry sensors/events

---

## 15) Audience-specific quick paths

## Non-technical path
- Install via HACS
- Add integration
- Add card
- Use text first
- Enable voice after basic chat works

## Technical path
- Validate gateway endpoint behavior and auth mode
- Validate session routing behavior
- Build automations with service calls/events
- Use telemetry sensors for health and troubleshooting

---

If you want this guide split into separate files later (Install, Voice, Automation, Troubleshooting), you can keep this `DOCS.md` as the master index and link each specialized document from it.