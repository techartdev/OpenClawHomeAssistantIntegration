"""Sensor entities for the OpenClaw integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DATA_GATEWAY_VERSION,
    DATA_LAST_TOOL_DURATION_MS,
    DATA_LAST_TOOL_ERROR,
    DATA_LAST_TOOL_INVOKED_AT,
    DATA_LAST_TOOL_NAME,
    DATA_LAST_TOOL_RESULT_PREVIEW,
    DATA_LAST_TOOL_STATUS,
    DATA_LAST_ACTIVITY,
    DATA_MODEL,
    DATA_PROVIDER,
    DATA_SESSION_COUNT,
    DATA_SESSIONS,
    DATA_STATUS,
    DATA_UPTIME,
    DOMAIN,
)
from .coordinator import OpenClawCoordinator

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key=DATA_STATUS,
        translation_key="status",
        name="OpenClaw Status",
        icon="mdi:robot",
    ),
    SensorEntityDescription(
        key=DATA_LAST_ACTIVITY,
        translation_key="last_activity",
        name="OpenClaw Last Activity",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
    ),
    SensorEntityDescription(
        key=DATA_SESSION_COUNT,
        translation_key="session_count",
        name="OpenClaw Session Count",
        icon="mdi:forum",
        native_unit_of_measurement="sessions",
    ),
    SensorEntityDescription(
        key=DATA_MODEL,
        translation_key="model",
        name="OpenClaw Model",
        icon="mdi:brain",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_NAME,
        translation_key="last_tool_name",
        name="OpenClaw Last Tool",
        icon="mdi:tools",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_STATUS,
        translation_key="last_tool_status",
        name="OpenClaw Last Tool Status",
        icon="mdi:check-decagram",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_DURATION_MS,
        translation_key="last_tool_duration_ms",
        name="OpenClaw Last Tool Duration",
        icon="mdi:speedometer",
        native_unit_of_measurement="ms",
    ),
    SensorEntityDescription(
        key=DATA_LAST_TOOL_INVOKED_AT,
        translation_key="last_tool_invoked_at",
        name="OpenClaw Last Tool Invoked",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenClaw sensors from a config entry."""
    coordinator: OpenClawCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        OpenClawSensor(coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    ]

    async_add_entities(entities)


class OpenClawSensor(CoordinatorEntity[OpenClawCoordinator], SensorEntity):
    """Sensor entity for OpenClaw data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OpenClawCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OpenClaw Assistant",
            "manufacturer": "OpenClaw",
            "model": "OpenClaw Gateway",
            "sw_version": coordinator.data.get(DATA_GATEWAY_VERSION) if coordinator.data else None,
        }

    @property
    def native_value(self) -> str | int | datetime | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes based on sensor type."""
        if not self.coordinator.data:
            return None

        key = self.entity_description.key
        data = self.coordinator.data

        if key == DATA_STATUS:
            return {
                "gateway_version": data.get(DATA_GATEWAY_VERSION),
                "uptime": data.get(DATA_UPTIME),
            }

        if key == DATA_SESSION_COUNT:
            sessions = data.get(DATA_SESSIONS, [])
            return {
                "sessions": [s.get("id", "unknown") for s in sessions[:10]],
            }

        if key == DATA_MODEL:
            return {
                "provider": data.get(DATA_PROVIDER),
            }

        if key == DATA_LAST_ACTIVITY:
            return {
                "last_message_preview": None,  # TODO: populate from last message
            }

        if key in {DATA_LAST_TOOL_NAME, DATA_LAST_TOOL_STATUS, DATA_LAST_TOOL_DURATION_MS}:
            return {
                "error": data.get(DATA_LAST_TOOL_ERROR),
                "result_preview": data.get(DATA_LAST_TOOL_RESULT_PREVIEW),
                "invoked_at": data.get(DATA_LAST_TOOL_INVOKED_AT),
            }

        return None
