"""The OpenClaw integration.

Sets up the OpenClaw integration: API client, coordinator, platforms, and services.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.components import websocket_api

try:
    from homeassistant.components.lovelace.const import LOVELACE_DATA
except ImportError:  # pragma: no cover
    LOVELACE_DATA = "lovelace"

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OpenClawApiClient, OpenClawApiError
from .const import (
    ATTR_ATTACHMENTS,
    ATTR_MESSAGE,
    ATTR_MODEL,
    ATTR_SESSION_ID,
    ATTR_TIMESTAMP,
    CONF_ADDON_CONFIG_PATH,
    CONF_GATEWAY_HOST,
    CONF_GATEWAY_PORT,
    CONF_GATEWAY_TOKEN,
    CONF_USE_SSL,
    CONF_CONTEXT_MAX_CHARS,
    CONF_CONTEXT_STRATEGY,
    CONF_ENABLE_TOOL_CALLS,
    CONF_INCLUDE_EXPOSED_CONTEXT,
    CONF_WAKE_WORD,
    CONF_WAKE_WORD_ENABLED,
    CONF_ALWAYS_VOICE_MODE,
    CONF_ALLOW_BRAVE_WEBSPEECH,
    CONF_VOICE_PROVIDER,
    CONTEXT_STRATEGY_TRUNCATE,
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_CONTEXT_STRATEGY,
    DEFAULT_ENABLE_TOOL_CALLS,
    DEFAULT_INCLUDE_EXPOSED_CONTEXT,
    DEFAULT_WAKE_WORD,
    DEFAULT_WAKE_WORD_ENABLED,
    DEFAULT_ALWAYS_VOICE_MODE,
    DEFAULT_ALLOW_BRAVE_WEBSPEECH,
    DEFAULT_VOICE_PROVIDER,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    OPENCLAW_CONFIG_REL_PATH,
    PLATFORMS,
    SERVICE_CLEAR_HISTORY,
    SERVICE_SEND_MESSAGE,
)
from .coordinator import OpenClawCoordinator
from .exposure import apply_context_policy, build_exposed_entities_context

_LOGGER = logging.getLogger(__name__)

_MAX_CHAT_HISTORY = 200

# Path to the chat card JS inside the integration package (custom_components/openclaw/www/)
_CARD_FILENAME = "openclaw-chat-card.js"
_CARD_PATH = Path(__file__).parent / "www" / _CARD_FILENAME
# URL at which the card JS is served (registered via register_static_path)
_CARD_STATIC_URL = f"/openclaw/{_CARD_FILENAME}"
# Versioned URL used for Lovelace resource registration to avoid stale browser cache
_CARD_URL = f"{_CARD_STATIC_URL}?v=0.1.32"

OpenClawConfigEntry = ConfigEntry


# Service call schemas
SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_SESSION_ID): cv.string,
        vol.Optional(ATTR_ATTACHMENTS): vol.All(cv.ensure_list, [cv.string]),
    }
)

CLEAR_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_SESSION_ID): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Set up OpenClaw from a config entry.

    Creates the API client, coordinator, and forwards setup to platforms.
    """
    session = async_get_clientsession(hass)

    client = OpenClawApiClient(
        host=entry.data[CONF_GATEWAY_HOST],
        port=entry.data[CONF_GATEWAY_PORT],
        token=entry.data[CONF_GATEWAY_TOKEN],
        use_ssl=entry.data.get(CONF_USE_SSL, False),
        session=session,
    )

    coordinator = OpenClawCoordinator(hass, client)

    # Store the addon config path for token re-reads
    addon_config_path = entry.data.get(CONF_ADDON_CONFIG_PATH)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "addon_config_path": addon_config_path,
        "entry": entry,
    }

    # First data fetch — if it fails the coordinator marks entities unavailable
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once, idempotent)
    _async_register_services(hass)
    _async_register_websocket_api(hass)

    # Register the frontend card resource
    hass.async_create_task(_async_register_frontend(hass))

    # Listen for addon restart events to re-read token
    if addon_config_path:
        _async_setup_token_refresh(hass, entry, client, addon_config_path)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpenClawConfigEntry) -> bool:
    """Unload an OpenClaw config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)

    return unload_ok


# ── Token refresh on reconnect ────────────────────────────────────────────────

def _async_setup_token_refresh(
    hass: HomeAssistant,
    entry: ConfigEntry,
    client: OpenClawApiClient,
    addon_config_path: str,
) -> None:
    """Set up a listener that re-reads the gateway token if auth fails.

    The addon may regenerate the token on restart. When we detect an auth
    failure during polling, we re-read the token from the shared filesystem
    and update the config entry + client transparently.
    """
    import json as _json

    async def _try_refresh_token() -> bool:
        """Re-read token from filesystem and update client if changed."""
        config_file = Path(addon_config_path) / OPENCLAW_CONFIG_REL_PATH

        def _read() -> str | None:
            if not config_file.exists():
                return None
            try:
                cfg = _json.loads(config_file.read_text(encoding="utf-8"))
                return cfg.get("gateway", {}).get("auth", {}).get("token")
            except Exception:  # noqa: BLE001
                return None

        new_token = await hass.async_add_executor_job(_read)
        if new_token and new_token != entry.data.get(CONF_GATEWAY_TOKEN):
            _LOGGER.info("Gateway token changed — updating config entry")
            new_data = {**entry.data, CONF_GATEWAY_TOKEN: new_token}
            hass.config_entries.async_update_entry(entry, data=new_data)
            # Update the live client in-place
            client.update_token(new_token)
            return True
        return False

    # Expose refresh function for the coordinator to call on auth errors
    hass.data[DOMAIN][entry.entry_id]["refresh_token"] = _try_refresh_token


# ── Frontend registration ─────────────────────────────────────────────────────

async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register static path + Lovelace resource for the chat card.

    Called as a fire-and-forget task from async_setup_entry.
    Wrapped entirely in try/except so it can NEVER crash the integration.
    """
    frontend_done_key = f"{DOMAIN}_frontend_registered"
    frontend_task_key = f"{DOMAIN}_frontend_registration_task"

    if hass.data.get(frontend_done_key):
        return

    existing_task = hass.data.get(frontend_task_key)
    if existing_task and not existing_task.done():
        return

    async def _register_with_retries() -> None:
        for _ in range(60):
            url = await _async_register_static_path(hass)
            if url and await _async_add_lovelace_resource(hass, url):
                hass.data[frontend_done_key] = True
                return
            await asyncio.sleep(5)

        _LOGGER.warning(
            "Could not auto-register OpenClaw chat card resource after retries. "
            "Add it manually in Dashboard resources: %s",
            _CARD_URL,
        )

    task = hass.async_create_task(_register_with_retries())
    hass.data[frontend_task_key] = task

    def _clear_task(_fut: asyncio.Future) -> None:
        hass.data.pop(frontend_task_key, None)

    task.add_done_callback(_clear_task)

    async def _on_ha_started(_event) -> None:
        if hass.data.get(frontend_done_key):
            return
        await _register_with_retries()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)


async def _async_register_static_path(hass: HomeAssistant) -> str | None:
    """Register the packaged chat-card JS as a static path when HTTP is ready."""
    static_key = f"{DOMAIN}_static_registered"
    if hass.data.get(static_key):
        return _CARD_URL

    if not _CARD_PATH.exists():
        _LOGGER.warning("Chat card JS not found at %s", _CARD_PATH)
        return None

    if hass.http is None:
        return None

    try:
        from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

        await hass.http.async_register_static_paths(
            [StaticPathConfig(_CARD_STATIC_URL, str(_CARD_PATH), cache_headers=True)]
        )
    except (ImportError, AttributeError):
        hass.http.register_static_path(_CARD_STATIC_URL, str(_CARD_PATH), True)

    hass.data[static_key] = True
    _LOGGER.debug("Registered static path: %s", _CARD_STATIC_URL)
    return _CARD_URL


async def _async_add_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Add the card URL to Lovelace's resource store if not already present."""
    # Lovelace stores resources in hass.data[LOVELACE_DATA].resources on
    # modern Home Assistant versions (fallback to legacy dict key below).
    # Resource collection supports:
    #   .async_items()          → list of {"id", "res_type", "url"} dicts
    #   .async_create_item(data) → persists a new resource
    lovelace_data = hass.data.get(LOVELACE_DATA) or hass.data.get("lovelace")
    if not lovelace_data:
        return False

    if isinstance(lovelace_data, dict):
        resource_collection = lovelace_data.get("resources")
    else:
        resource_collection = getattr(lovelace_data, "resources", None)

    if resource_collection is None:
        return False

    try:
        existing_items = list(resource_collection.async_items())

        desired_path = urlsplit(url).path
        legacy_paths = {
            "/openclaw/openclaw-chat-card.js",
            "/local/openclaw-chat-card.js",
            "/hacsfiles/openclaw/openclaw-chat-card.js",
        }

        to_remove: list[str] = []
        for item in existing_items:
            item_id = item.get("id")
            item_url = item.get("url")
            if not item_id or not item_url:
                continue
            item_path = urlsplit(item_url).path
            if item_path in legacy_paths and item_url != url:
                to_remove.append(item_id)

        for item_id in to_remove:
            await resource_collection.async_delete_item(item_id)
            _LOGGER.info("Removed legacy/duplicate OpenClaw Lovelace resource id=%s", item_id)

        existing_urls = {item["url"] for item in resource_collection.async_items()}
        if url in existing_urls:
            _LOGGER.debug("Lovelace resource already registered: %s", url)
            return True

        await resource_collection.async_create_item(
            {"res_type": "module", "url": url}
        )
        _LOGGER.info(
            "Auto-registered Lovelace resource: %s — the chat card is ready to use.",
            url,
        )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not auto-register Lovelace resource '%s': %s. "
            "Add it manually: Settings → Dashboards → Resources.",
            url,
            err,
        )
        return False


# ── Service registration ──────────────────────────────────────────────────────

@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register openclaw.send_message and openclaw.clear_history services."""

    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        return

    async def handle_send_message(call: ServiceCall) -> None:
        """Handle the openclaw.send_message service call."""
        message: str = call.data[ATTR_MESSAGE]
        session_id: str = call.data.get(ATTR_SESSION_ID) or "default"

        entry_data = _get_first_entry_data(hass)
        if not entry_data:
            _LOGGER.error("No OpenClaw integration configured")
            return

        client: OpenClawApiClient = entry_data["client"]
        coordinator: OpenClawCoordinator = entry_data["coordinator"]
        entry: ConfigEntry = entry_data["entry"]
        options = entry.options

        try:
            include_context = options.get(
                CONF_INCLUDE_EXPOSED_CONTEXT,
                DEFAULT_INCLUDE_EXPOSED_CONTEXT,
            )
            max_chars = int(
                options.get(CONF_CONTEXT_MAX_CHARS, DEFAULT_CONTEXT_MAX_CHARS)
            )
            strategy = options.get(CONF_CONTEXT_STRATEGY, DEFAULT_CONTEXT_STRATEGY)
            if strategy not in {"clear", CONTEXT_STRATEGY_TRUNCATE}:
                strategy = DEFAULT_CONTEXT_STRATEGY

            raw_context = (
                build_exposed_entities_context(hass, assistant="conversation")
                if include_context
                else None
            )
            system_prompt = apply_context_policy(raw_context, max_chars, strategy)

            _append_chat_history(hass, session_id, "user", message)
            response = await client.async_send_message(
                message=message,
                session_id=session_id,
                system_prompt=system_prompt,
            )

            if options.get(CONF_ENABLE_TOOL_CALLS, DEFAULT_ENABLE_TOOL_CALLS):
                tool_results = await _async_execute_tool_calls(hass, response)
                if tool_results:
                    response = await client.async_send_message(
                        message=(
                            "Tool execution results:\n"
                            + "\n".join(f"- {line}" for line in tool_results)
                            + "\nRespond to the user based on these results."
                        ),
                        session_id=session_id,
                        system_prompt=system_prompt,
                    )

            assistant_message = _extract_assistant_message(response)
            model_used = response.get("model", "unknown")

            if not assistant_message:
                assistant_message = "Response received, but no readable message content was found."
                _LOGGER.warning(
                    "OpenClaw response had no parseable assistant message. Keys: %s",
                    list(response.keys()),
                )

            _append_chat_history(hass, session_id, "assistant", assistant_message)
            hass.bus.async_fire(
                EVENT_MESSAGE_RECEIVED,
                {
                    ATTR_MESSAGE: assistant_message,
                    ATTR_SESSION_ID: session_id,
                    ATTR_MODEL: model_used,
                    ATTR_TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                },
            )
            coordinator.update_last_activity()

        except OpenClawApiError as err:
            _LOGGER.error("Failed to send message to OpenClaw: %s", err)
            _append_chat_history(hass, session_id, "assistant", f"OpenClaw error: {err}")
            hass.bus.async_fire(
                EVENT_MESSAGE_RECEIVED,
                {
                    ATTR_MESSAGE: f"OpenClaw error: {err}",
                    ATTR_SESSION_ID: session_id,
                    ATTR_MODEL: "unknown",
                    ATTR_TIMESTAMP: datetime.now(timezone.utc).isoformat(),
                },
            )

    async def handle_clear_history(call: ServiceCall) -> None:
        """Handle the openclaw.clear_history service call."""
        session_id: str | None = call.data.get(ATTR_SESSION_ID)
        _LOGGER.info("Clear history requested (session=%s)", session_id or "all")
        store = _get_chat_history_store(hass)
        if session_id:
            store.pop(session_id, None)
        else:
            store.clear()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        handle_send_message,
        schema=SEND_MESSAGE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_HISTORY,
        handle_clear_history,
        schema=CLEAR_HISTORY_SCHEMA,
    )


def _get_first_entry_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Return entry data dict for the first configured OpenClaw entry."""
    domain_data: dict = hass.data.get(DOMAIN, {})
    for entry_id, entry_data in domain_data.items():
        if isinstance(entry_data, dict) and "client" in entry_data:
            return entry_data
    return None


def _extract_text_recursive(value: Any, depth: int = 0) -> str | None:
    """Recursively extract assistant text from nested response payloads."""
    if depth > 8:
        return None

    if isinstance(value, str):
        text = value.strip()
        return text or None

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            extracted = _extract_text_recursive(item, depth + 1)
            if extracted:
                parts.append(extracted)
        if parts:
            return "\n".join(parts)
        return None

    if isinstance(value, dict):
        priority_keys = (
            "output_text",
            "text",
            "content",
            "message",
            "response",
            "answer",
            "choices",
            "output",
            "delta",
        )

        for key in priority_keys:
            if key not in value:
                continue
            extracted = _extract_text_recursive(value.get(key), depth + 1)
            if extracted:
                return extracted

        for nested_value in value.values():
            extracted = _extract_text_recursive(nested_value, depth + 1)
            if extracted:
                return extracted

    return None


def _extract_assistant_message(response: dict[str, Any]) -> str | None:
    """Extract assistant text from modern/legacy OpenAI-compatible responses."""
    return _extract_text_recursive(response)


def _extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract OpenAI-style tool calls from a response payload."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return []

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return []

    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []

    valid_calls: list[dict[str, Any]] = []
    for call in tool_calls:
        if isinstance(call, dict):
            valid_calls.append(call)
    return valid_calls


async def _async_execute_tool_calls(
    hass: HomeAssistant,
    response: dict[str, Any],
) -> list[str]:
    """Execute supported tool calls and return result lines."""
    results: list[str] = []
    tool_calls = _extract_tool_calls(response)

    for call in tool_calls:
        function_data = call.get("function")
        if not isinstance(function_data, dict):
            continue

        function_name = function_data.get("name")
        arguments = function_data.get("arguments")

        if function_name not in {"execute_service", "execute_services"}:
            results.append(f"Skipped unsupported tool '{function_name}'")
            continue

        if not isinstance(arguments, str):
            results.append("Skipped tool call with invalid arguments format")
            continue

        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            results.append("Skipped tool call due to invalid JSON arguments")
            continue

        services_list = parsed.get("list") if isinstance(parsed, dict) else None
        if not isinstance(services_list, list):
            results.append("Skipped tool call without 'list' payload")
            continue

        for item in services_list:
            if not isinstance(item, dict):
                continue
            domain = item.get("domain")
            service = item.get("service")
            service_data = item.get("service_data", {})

            if not isinstance(domain, str) or not isinstance(service, str):
                results.append("Skipped invalid service item (missing domain/service)")
                continue

            if not isinstance(service_data, dict):
                service_data = {}

            try:
                await hass.services.async_call(
                    domain,
                    service,
                    service_data,
                    blocking=True,
                )
                results.append(f"Executed {domain}.{service}")
            except Exception as err:  # noqa: BLE001
                results.append(f"Failed {domain}.{service}: {err}")

    return results


def _get_chat_history_store(hass: HomeAssistant) -> dict[str, list[dict[str, str]]]:
    """Return in-memory per-session chat history store."""
    store_key = f"{DOMAIN}_chat_history"
    store = hass.data.get(store_key)
    if store is None:
        store = {}
        hass.data[store_key] = store
    return store


def _append_chat_history(hass: HomeAssistant, session_id: str, role: str, content: str) -> None:
    """Append a message to in-memory chat history."""
    store = _get_chat_history_store(hass)
    history = store.setdefault(session_id, [])
    history.append(
        {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(history) > _MAX_CHAT_HISTORY:
        del history[:-_MAX_CHAT_HISTORY]


@callback
def _async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register websocket API for chat history retrieval."""
    key = f"{DOMAIN}_ws_registered"
    if hass.data.get(key):
        return
    hass.data[key] = True

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/get_history",
            vol.Optional("session_id"): cv.string,
        }
    )
    @callback
    def websocket_get_history(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Return chat history for a session."""
        session_id = msg.get("session_id") or "default"
        history = _get_chat_history_store(hass).get(session_id, [])
        connection.send_result(msg["id"], {"session_id": session_id, "messages": history})

    websocket_api.async_register_command(hass, websocket_get_history)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): f"{DOMAIN}/get_settings",
        }
    )
    @callback
    def websocket_get_settings(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        """Return frontend-related integration settings."""
        entry_data = _get_first_entry_data(hass)
        options = entry_data.get("entry").options if entry_data and entry_data.get("entry") else {}
        connection.send_result(
            msg["id"],
            {
                CONF_WAKE_WORD_ENABLED: options.get(
                    CONF_WAKE_WORD_ENABLED,
                    DEFAULT_WAKE_WORD_ENABLED,
                ),
                CONF_WAKE_WORD: options.get(CONF_WAKE_WORD, DEFAULT_WAKE_WORD),
                CONF_ALWAYS_VOICE_MODE: options.get(
                    CONF_ALWAYS_VOICE_MODE,
                    DEFAULT_ALWAYS_VOICE_MODE,
                ),
                CONF_ALLOW_BRAVE_WEBSPEECH: options.get(
                    CONF_ALLOW_BRAVE_WEBSPEECH,
                    DEFAULT_ALLOW_BRAVE_WEBSPEECH,
                ),
                CONF_VOICE_PROVIDER: options.get(
                    CONF_VOICE_PROVIDER,
                    DEFAULT_VOICE_PROVIDER,
                ),
                "language": hass.config.language,
            },
        )

    websocket_api.async_register_command(hass, websocket_get_settings)
