"""Binary sensor entities for the OpenClaw integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_CONNECTED, DATA_GATEWAY_VERSION, DOMAIN
from .coordinator import OpenClawCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenClaw binary sensors from a config entry."""
    coordinator: OpenClawCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities([OpenClawConnectedSensor(coordinator, entry)])


class OpenClawConnectedSensor(CoordinatorEntity[OpenClawCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether HA is connected to the OpenClaw gateway."""

    _attr_has_entity_name = True
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self,
        coordinator: OpenClawCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OpenClaw Assistant",
            "manufacturer": "OpenClaw",
            "model": "OpenClaw Gateway",
            "sw_version": coordinator.data.get(DATA_GATEWAY_VERSION) if coordinator.data else None,
        }

    @property
    def is_on(self) -> bool | None:
        """Return True if connected to the gateway."""
        if not self.coordinator.data:
            return False
        return self.coordinator.data.get(DATA_CONNECTED, False)
