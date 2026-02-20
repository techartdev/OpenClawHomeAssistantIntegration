"""Config flow for the OpenClaw integration.

Supports two discovery methods:
1. Supervisor API + filesystem scan — auto-detects the addon in HAOS/Supervised
2. Manual entry — user provides gateway host, port, and token
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OpenClawApiClient, OpenClawApiError, OpenClawAuthError, OpenClawConnectionError
from .const import (
    ADDON_CONFIGS_ROOT,
    ADDON_SLUG,
    ADDON_SLUG_FRAGMENTS,
    CONF_ADDON_CONFIG_PATH,
    CONF_GATEWAY_HOST,
    CONF_GATEWAY_PORT,
    CONF_GATEWAY_TOKEN,
    CONF_USE_SSL,
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    DOMAIN,
    OPENCLAW_CONFIG_REL_PATH,
)

_LOGGER = logging.getLogger(__name__)


# ── Filesystem helpers ────────────────────────────────────────────────────────

def _find_addon_config_dir() -> Path | None:
    """Scan /addon_configs/ for the OpenClaw addon directory.

    The Supervisor prepends a repository-specific hash to the addon slug:
        /addon_configs/<hash>_<addon_name>/
    e.g. /addon_configs/0bfc167e_openclaw_assistant/

    We cannot predict the hash, so we scan for directories whose name
    ends with one of the known slug fragments.

    Returns:
        Path to the addon config dir, or None if not found.
    """
    root = Path(ADDON_CONFIGS_ROOT)
    if not root.is_dir():
        return None

    # Exact slug match first (works if there's no hash prefix)
    exact = root / ADDON_SLUG
    if exact.is_dir():
        return exact

    # Scan for <hash>_<fragment> pattern
    try:
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name.lower()
            for fragment in ADDON_SLUG_FRAGMENTS:
                if name.endswith(f"_{fragment}") or name == fragment:
                    _LOGGER.debug("Discovered addon config dir: %s", entry)
                    return entry
    except PermissionError:
        _LOGGER.debug("No permission to scan %s", root)

    return None


def _read_gateway_token_from_path(config_dir: Path) -> str | None:
    """Read the gateway auth token from openclaw.json inside a config dir.

    Args:
        config_dir: The addon's mapped config directory.

    Returns:
        Token string if found, else None.
    """
    config_file = config_dir / OPENCLAW_CONFIG_REL_PATH
    if not config_file.exists():
        _LOGGER.debug("openclaw.json not found at %s", config_file)
        return None

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        token = config.get("gateway", {}).get("auth", {}).get("token")
        if token:
            _LOGGER.debug("Found gateway token in %s", config_file)
            return token
        _LOGGER.debug("No gateway.auth.token in %s", config_file)
    except (json.JSONDecodeError, IOError, KeyError) as err:
        _LOGGER.debug("Error reading %s: %s", config_file, err)

    return None


def _read_gateway_port_from_path(config_dir: Path) -> int | None:
    """Read the gateway port from openclaw.json.

    Useful as a fallback when the Supervisor API is not available.
    """
    config_file = config_dir / OPENCLAW_CONFIG_REL_PATH
    if not config_file.exists():
        return None
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        return config.get("gateway", {}).get("port")
    except (json.JSONDecodeError, IOError):
        return None


# ── Discovery helpers ─────────────────────────────────────────────────────────

async def _async_try_discover_addon(hass: HomeAssistant) -> dict[str, Any] | None:
    """Try to discover the OpenClaw addon via Supervisor API + filesystem.

    Steps:
      1. Query Supervisor API for addon state & options (if available).
      2. Scan /addon_configs/ to find the actual directory (hash-prefixed).
      3. Read the gateway auth token from the discovered config directory.

    Returns:
        Dict with connection details if found, else None.
    """
    addon_state: str | None = None
    addon_options: dict[str, Any] = {}

    # ── Step 1: Supervisor API (optional — gives us state & port) ────
    try:
        if "hassio" in hass.data:
            from homeassistant.components.hassio import async_get_addon_info

            addon_info = await async_get_addon_info(hass, ADDON_SLUG)
            if addon_info:
                addon_state = addon_info.get("state")
                addon_options = addon_info.get("options", {})
                _LOGGER.debug(
                    "Supervisor reports addon state=%s, options=%s",
                    addon_state,
                    {k: v for k, v in addon_options.items() if "token" not in k.lower()},
                )
            else:
                _LOGGER.debug("Addon %s not found via Supervisor API", ADDON_SLUG)
        else:
            _LOGGER.debug("Supervisor not available — will try filesystem only")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Supervisor API call failed: %s", err)

    # If Supervisor says the addon is not running, don't bother scanning
    if addon_state is not None and addon_state != "started":
        _LOGGER.info(
            "Addon discovered but not running (state=%s). Start it first.", addon_state
        )
        return None

    # Warn early if the OpenAI-compatible API is disabled — /v1/models will return
    # HTML and the connection probe will fail with a misleading error.
    if not addon_options.get("enable_openai_api", False):
        _LOGGER.warning(
            "Addon option 'enable_openai_api' is false. "
            "The integration requires this to be enabled. "
            "Enable it in the addon configuration and restart the addon."
        )

    # ── Step 2: Find the addon config directory on the filesystem ────
    config_dir = await hass.async_add_executor_job(_find_addon_config_dir)
    if not config_dir:
        _LOGGER.debug("Could not find addon config directory under %s", ADDON_CONFIGS_ROOT)
        return None

    # ── Step 3: Read the gateway token ────────────────────────────────
    token = await hass.async_add_executor_job(_read_gateway_token_from_path, config_dir)
    if not token:
        _LOGGER.info(
            "Found addon config at %s but could not read gateway token. "
            "Has the addon been started and onboarded?",
            config_dir,
        )
        return None

    # ── Build discovered config ───────────────────────────────────────
    # Prefer Supervisor-reported port, fall back to openclaw.json, then default
    port = addon_options.get("gateway_port")
    if port is None:
        port = await hass.async_add_executor_job(
            _read_gateway_port_from_path, config_dir
        )
    if port is None:
        port = DEFAULT_GATEWAY_PORT

    return {
        CONF_GATEWAY_HOST: DEFAULT_GATEWAY_HOST,
        CONF_GATEWAY_PORT: port,
        CONF_GATEWAY_TOKEN: token,
        CONF_USE_SSL: False,
        CONF_ADDON_CONFIG_PATH: str(config_dir),
    }


async def _async_validate_connection(
    hass: HomeAssistant,
    host: str,
    port: int,
    token: str,
    use_ssl: bool = False,
) -> bool:
    """Validate that we can connect and authenticate to the gateway."""
    session = async_get_clientsession(hass)
    client = OpenClawApiClient(
        host=host,
        port=port,
        token=token,
        use_ssl=use_ssl,
        session=session,
    )
    return await client.async_check_connection()


# ── Config flow ───────────────────────────────────────────────────────────────

class OpenClawConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenClaw."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step.

        Tries auto-discovery first, then falls back to manual entry.
        """
        # Prevent duplicate entries
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Try auto-discovery
        discovered = await _async_try_discover_addon(self.hass)
        if discovered:
            self._discovered = discovered
            return await self.async_step_confirm()

        # No addon found or token unreadable — show manual entry form
        return await self.async_step_manual()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm auto-discovered addon connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._discovered is not None
            try:
                connected = await _async_validate_connection(
                    self.hass,
                    self._discovered[CONF_GATEWAY_HOST],
                    self._discovered[CONF_GATEWAY_PORT],
                    self._discovered[CONF_GATEWAY_TOKEN],
                    self._discovered.get(CONF_USE_SSL, False),
                )
            except OpenClawAuthError:
                connected = False
                errors["base"] = "invalid_auth"
            except OpenClawConnectionError:
                connected = False
                errors["base"] = "cannot_connect"
            except OpenClawApiError as err:
                connected = False
                errors["base"] = "openai_api_disabled"
                _LOGGER.warning("Gateway API error during connection check: %s", err)

            if connected:
                return self.async_create_entry(
                    title="OpenClaw Assistant",
                    data=self._discovered,
                )
            if not errors:
                errors["base"] = "cannot_connect"

        assert self._discovered is not None
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "addon_name": "OpenClaw Assistant",
                "host": self._discovered[CONF_GATEWAY_HOST],
                "port": str(self._discovered[CONF_GATEWAY_PORT]),
                "config_path": self._discovered.get(CONF_ADDON_CONFIG_PATH, "unknown"),
            },
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual configuration entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_GATEWAY_HOST]
            port = user_input[CONF_GATEWAY_PORT]
            token = user_input[CONF_GATEWAY_TOKEN]
            use_ssl = user_input.get(CONF_USE_SSL, False)

            try:
                connected = await _async_validate_connection(
                    self.hass, host, port, token, use_ssl
                )
            except OpenClawAuthError:
                errors["base"] = "invalid_auth"
                connected = False
            except OpenClawConnectionError:
                errors["base"] = "cannot_connect"
                connected = False
            except OpenClawApiError as err:
                errors["base"] = "openai_api_disabled"
                connected = False
                _LOGGER.warning("Gateway API error during connection check: %s", err)

            if connected:
                return self.async_create_entry(
                    title="OpenClaw Assistant",
                    data={
                        CONF_GATEWAY_HOST: host,
                        CONF_GATEWAY_PORT: port,
                        CONF_GATEWAY_TOKEN: token,
                        CONF_USE_SSL: use_ssl,
                    },
                )
            if "base" not in errors:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_GATEWAY_HOST, default=DEFAULT_GATEWAY_HOST
                    ): str,
                    vol.Required(
                        CONF_GATEWAY_PORT, default=DEFAULT_GATEWAY_PORT
                    ): vol.All(int, vol.Range(min=1, max=65535)),
                    vol.Required(CONF_GATEWAY_TOKEN): str,
                    vol.Optional(CONF_USE_SSL, default=False): bool,
                }
            ),
            errors=errors,
        )
