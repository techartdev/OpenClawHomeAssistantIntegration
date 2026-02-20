"""The OpenClaw integration.

Sets up the OpenClaw integration: API client, coordinator, platforms, and services.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
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
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    OPENCLAW_CONFIG_REL_PATH,
    PLATFORMS,
    SERVICE_CLEAR_HISTORY,
    SERVICE_SEND_MESSAGE,
)
from .coordinator import OpenClawCoordinator

_LOGGER = logging.getLogger(__name__)

# Path to the chat card JS inside the integration package (custom_components/openclaw/www/)
_CARD_FILENAME = "openclaw-chat-card.js"
_CARD_PATH = Path(__file__).parent / "www" / _CARD_FILENAME
# URL at which the card JS will be served (registered via register_static_path)
_CARD_URL = f"/openclaw/{_CARD_FILENAME}"

type OpenClawConfigEntry = ConfigEntry


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Global integration setup — runs once before any config entries.

    Registers the static HTTP path for the chat card so the JS file is served
    directly from inside the integration package, regardless of whether the
    user installed via HACS or manually.
    """
    _async_register_static_path(hass)
    return True

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
    }

    # First data fetch — if it fails the coordinator marks entities unavailable
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services (once, idempotent)
    _async_register_services(hass)

    # Register the frontend card resource
    _async_register_frontend(hass)

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

@callback
def _async_register_static_path(hass: HomeAssistant) -> None:
    """Register the integration's www/ folder as a static HTTP path.

    After this the card JS is always available at /openclaw/openclaw-chat-card.js
    regardless of how the integration was installed (HACS or manual).
    """
    static_key = f"{DOMAIN}_static_registered"
    if hass.data.get(static_key):
        return
    hass.data[static_key] = True

    if not _CARD_PATH.exists():
        _LOGGER.warning(
            "Chat card JS not found at %s — frontend resource will not be available",
            _CARD_PATH,
        )
        return

    hass.http.register_static_path(
        f"/openclaw/{_CARD_FILENAME}",
        str(_CARD_PATH),
        cache_headers=True,
    )
    _LOGGER.debug("Registered static path: /openclaw/%s", _CARD_FILENAME)


@callback
def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the Lovelace custom card resource (called once per setup).

    Adds the card URL to Lovelace's resource list so it loads on every
    dashboard automatically. No manual step required.
    """
    frontend_key = f"{DOMAIN}_frontend_registered"
    if hass.data.get(frontend_key):
        return
    hass.data[frontend_key] = True

    # Ensure static path is registered (may have been missed if async_setup
    # didn't run, e.g. during a config entry reload).
    _async_register_static_path(hass)

    hass.async_create_task(_async_add_lovelace_resource(hass, _CARD_URL))


async def _async_add_lovelace_resource(hass: HomeAssistant, url: str) -> None:
    """Add the card URL to Lovelace's resource store if not already present."""
    # Lovelace stores resources in hass.data["lovelace"]["resources"].
    # It is a ResourceStorageCollection with:
    #   .async_items()          → list of {"id", "res_type", "url"} dicts
    #   .async_create_item(data) → persists a new resource
    lovelace_data = hass.data.get("lovelace")
    if not lovelace_data:
        _LOGGER.debug(
            "Lovelace not loaded; resource '%s' must be added manually if needed",
            url,
        )
        return

    resource_collection = lovelace_data.get("resources")
    if resource_collection is None:
        _LOGGER.debug("Lovelace resource store not available")
        return

    try:
        existing_urls = {item["url"] for item in resource_collection.async_items()}
        if url in existing_urls:
            _LOGGER.debug("Lovelace resource already registered: %s", url)
            return

        await resource_collection.async_create_item(
            {"res_type": "module", "url": url}
        )
        _LOGGER.info(
            "Auto-registered Lovelace resource: %s — the chat card is ready to use.",
            url,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not auto-register Lovelace resource '%s': %s. "
            "Add it manually: Settings → Dashboards → Resources.",
            url,
            err,
        )


# ── Service registration ──────────────────────────────────────────────────────

@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register openclaw.send_message and openclaw.clear_history services."""

    if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        return

    async def handle_send_message(call: ServiceCall) -> None:
        """Handle the openclaw.send_message service call."""
        message: str = call.data[ATTR_MESSAGE]
        session_id: str | None = call.data.get(ATTR_SESSION_ID)

        entry_data = _get_first_entry_data(hass)
        if not entry_data:
            _LOGGER.error("No OpenClaw integration configured")
            return

        client: OpenClawApiClient = entry_data["client"]
        coordinator: OpenClawCoordinator = entry_data["coordinator"]

        try:
            response = await client.async_send_message(
                message=message,
                session_id=session_id,
            )

            choices = response.get("choices", [])
            if choices:
                assistant_message = (
                    choices[0].get("message", {}).get("content", "")
                )
                model_used = response.get("model", "unknown")

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

    async def handle_clear_history(call: ServiceCall) -> None:
        """Handle the openclaw.clear_history service call."""
        session_id: str | None = call.data.get(ATTR_SESSION_ID)
        _LOGGER.info("Clear history requested (session=%s)", session_id or "all")
        # TODO: Implement when gateway exposes a session-clear endpoint

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
