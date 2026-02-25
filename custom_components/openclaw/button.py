"""Button entities for the OpenClaw integration.

Provides dashboard-friendly buttons for common actions:
- Clear History — clears in-memory conversation history
- Sync History — triggers backend history re-sync
- Run Diagnostics — fires a connectivity check against the gateway
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OpenClawApiClient
from .const import DOMAIN
from .coordinator import OpenClawCoordinator

_LOGGER = logging.getLogger(__name__)

BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="clear_history",
        translation_key="clear_history",
        name="OpenClaw Clear History",
        icon="mdi:delete-sweep",
    ),
    ButtonEntityDescription(
        key="sync_history",
        translation_key="sync_history",
        name="OpenClaw Sync History",
        icon="mdi:sync",
    ),
    ButtonEntityDescription(
        key="run_diagnostics",
        translation_key="run_diagnostics",
        name="OpenClaw Run Diagnostics",
        icon="mdi:stethoscope",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenClaw button entities from a config entry."""
    entry_data: dict = hass.data[DOMAIN][entry.entry_id]
    coordinator: OpenClawCoordinator = entry_data["coordinator"]
    client: OpenClawApiClient = entry_data["client"]

    entities = [
        OpenClawButton(coordinator, client, description, entry, hass)
        for description in BUTTON_DESCRIPTIONS
    ]
    async_add_entities(entities)


class OpenClawButton(CoordinatorEntity[OpenClawCoordinator], ButtonEntity):
    """Button entity for OpenClaw actions."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OpenClawCoordinator,
        client: OpenClawApiClient,
        description: ButtonEntityDescription,
        entry: ConfigEntry,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._client = client
        self._entry = entry
        self._hass = hass
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OpenClaw Assistant",
            "manufacturer": "OpenClaw",
            "model": "OpenClaw Gateway",
        }

    async def async_press(self) -> None:
        """Handle button press."""
        key = self.entity_description.key

        if key == "clear_history":
            store_key = f"{DOMAIN}_chat_history"
            store = self._hass.data.get(store_key)
            if isinstance(store, dict):
                store.clear()
            _LOGGER.info("OpenClaw chat history cleared via button")

        elif key == "sync_history":
            await self.coordinator.async_request_refresh()
            _LOGGER.info("OpenClaw history sync triggered via button")

        elif key == "run_diagnostics":
            try:
                alive = await self._client.async_check_alive()
                if alive:
                    _LOGGER.info("OpenClaw diagnostics: gateway is reachable")
                else:
                    _LOGGER.warning("OpenClaw diagnostics: gateway did not respond")
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("OpenClaw diagnostics failed: %s", err)
            await self.coordinator.async_request_refresh()
