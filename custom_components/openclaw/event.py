"""Event entities for the OpenClaw integration.

Provides native HA EventEntity entities for:
- openclaw_message_received — fires on each assistant reply
- openclaw_tool_invoked — fires on each tool invocation result

These complement the raw HA bus events with proper entity-registry entries
that are selectable in the automation UI (no YAML needed).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    EVENT_TOOL_INVOKED,
)

EVENT_DESCRIPTIONS: tuple[EventEntityDescription, ...] = (
    EventEntityDescription(
        key="message_received",
        translation_key="message_received",
        name="OpenClaw Message Received",
        icon="mdi:message-text",
        event_types=["message_received"],
    ),
    EventEntityDescription(
        key="tool_invoked",
        translation_key="tool_invoked",
        name="OpenClaw Tool Invoked",
        icon="mdi:tools",
        event_types=["tool_invoked_ok", "tool_invoked_error"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OpenClaw event entities from a config entry."""
    entities = [
        OpenClawEventEntity(entry, description)
        for description in EVENT_DESCRIPTIONS
    ]
    async_add_entities(entities)

    # Wire HA bus events → entity triggers
    for entity in entities:
        entity.async_start_listening(hass)


class OpenClawEventEntity(EventEntity):
    """Event entity that mirrors HA bus events into the entity registry."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        description: EventEntityDescription,
    ) -> None:
        """Initialize the event entity."""
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OpenClaw Assistant",
            "manufacturer": "OpenClaw",
            "model": "OpenClaw Gateway",
        }
        self._entry_id = entry.entry_id
        self._unsub: callback | None = None

    @callback
    def async_start_listening(self, hass: HomeAssistant) -> None:
        """Subscribe to the matching HA bus event."""
        key = self.entity_description.key

        if key == "message_received":
            bus_event = EVENT_MESSAGE_RECEIVED
        elif key == "tool_invoked":
            bus_event = EVENT_TOOL_INVOKED
        else:
            return

        @callback
        def _handle_event(event) -> None:
            data: dict[str, Any] = dict(event.data or {})
            if key == "message_received":
                self._trigger_event("message_received", data)
            elif key == "tool_invoked":
                ok = data.get("ok", False)
                event_type = "tool_invoked_ok" if ok else "tool_invoked_error"
                self._trigger_event(event_type, data)
            self.async_write_ha_state()

        self._unsub = hass.bus.async_listen(bus_event, _handle_event)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe when entity is removed."""
        if self._unsub:
            self._unsub()
            self._unsub = None
