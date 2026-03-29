"""Helpers for Assist entity exposure context."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from homeassistant.components.homeassistant import async_should_expose
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.util import dt as dt_util

# Attributes worth including in entity context (keeps prompt compact)
_USEFUL_ATTRIBUTES = frozenset({
    "brightness", "color_temp", "color_mode", "hvac_mode", "hvac_action",
    "temperature", "current_temperature", "target_temp_high", "target_temp_low",
    "battery_level", "battery", "media_title", "media_artist", "source",
    "volume_level", "is_volume_muted", "preset_mode", "fan_mode",
})


def build_exposed_entities_context(
    hass: HomeAssistant,
    assistant: str | None = "conversation",
    max_entities: int = 250,
) -> str | None:
    """Build a compact prompt block of entities exposed to an assistant.

    Uses Home Assistant's built-in expose rules (Settings -> Voice assistants -> Expose).
    Includes area assignments and useful state attributes for richer LLM context.
    """
    assistant_id = assistant or "conversation"

    def _collect_for(assistant_value: str) -> list:
        return [
            state
            for state in hass.states.async_all()
            if async_should_expose(hass, assistant_value, state.entity_id)
        ]

    exposed_states = _collect_for(assistant_id)

    if not exposed_states and assistant_id != "conversation":
        exposed_states = _collect_for("conversation")

    if not exposed_states:
        return None

    # Build area lookup
    ent_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)
    area_cache: dict[str | None, str] = {}

    def _get_area_name(entity_id: str) -> str | None:
        entry = ent_reg.async_get(entity_id)
        if not entry:
            return None
        area_id = entry.area_id
        if area_id and area_id not in area_cache:
            area_entry = area_reg.async_get_area(area_id)
            area_cache[area_id] = area_entry.name if area_entry else ""
        return area_cache.get(area_id) or None

    exposed_states.sort(key=lambda state: state.entity_id)
    domain_counts = Counter(state.domain for state in exposed_states)

    now = dt_util.now()
    lines: list[str] = [
        f"Current date and time: {now.strftime('%A %d %B %Y, %H:%M %Z')}",
        "",
        "Home Assistant live context (entities exposed to this assistant):",
        f"- total_exposed_entities: {len(exposed_states)}",
        "- domain_counts:",
    ]
    lines.extend(f"  - {domain}: {count}" for domain, count in sorted(domain_counts.items()))
    lines.append("- entities:")

    for state in exposed_states[:max_entities]:
        friendly_name = state.name or state.entity_id
        area_name = _get_area_name(state.entity_id)
        parts = [
            f"id: {state.entity_id}",
            f"name: {friendly_name}",
            f"state: {state.state}",
        ]
        if area_name:
            parts.append(f"area: {area_name}")

        # Include useful attributes (skip empty/None)
        useful_attrs = {
            k: v for k, v in state.attributes.items()
            if k in _USEFUL_ATTRIBUTES and v is not None
        }
        if useful_attrs:
            attrs_str = ", ".join(f"{k}={v}" for k, v in useful_attrs.items())
            parts.append(f"attrs: {attrs_str}")

        lines.append(f"  - {'; '.join(parts)}")

    if len(exposed_states) > max_entities:
        lines.append(
            f"  - ... {len(exposed_states) - max_entities} additional exposed entities omitted"
        )

    lines.append(
        "Use only these exposed entities when answering or controlling Home Assistant."
    )

    return "\n".join(lines)


def apply_context_policy(
    context_text: str | None,
    max_chars: int,
    strategy: str,
) -> str | None:
    """Apply context truncation policy to an optional prompt block."""
    if not context_text:
        return None

    if max_chars <= 0:
        return None

    if len(context_text) <= max_chars:
        return context_text

    if strategy == "clear":
        return None

    marker = "\n[Context truncated to fit configured max length]\n"
    available = max_chars - len(marker)
    if available <= 0:
        return context_text[-max_chars:]
    return marker + context_text[-available:]
