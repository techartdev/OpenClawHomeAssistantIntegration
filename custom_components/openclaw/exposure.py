"""Helpers for Assist entity exposure context."""

from __future__ import annotations

from collections import Counter

from homeassistant.components.homeassistant import async_should_expose
from homeassistant.core import HomeAssistant


def build_exposed_entities_context(
    hass: HomeAssistant,
    assistant: str | None = "assist",
    max_entities: int = 250,
) -> str | None:
    """Build a compact prompt block of entities exposed to an assistant.

    Uses Home Assistant's built-in expose rules (Settings -> Voice assistants -> Expose).
    """
    assistant_id = assistant or "assist"

    exposed_states = [
        state
        for state in hass.states.async_all()
        if async_should_expose(hass, assistant_id, state.entity_id)
    ]

    if not exposed_states:
        return None

    exposed_states.sort(key=lambda state: state.entity_id)
    domain_counts = Counter(state.domain for state in exposed_states)

    lines: list[str] = [
        "Home Assistant live context (entities exposed to this assistant):",
        f"- total_exposed_entities: {len(exposed_states)}",
        "- domain_counts:",
    ]
    lines.extend(f"  - {domain}: {count}" for domain, count in sorted(domain_counts.items()))
    lines.append("- entities:")

    for state in exposed_states[:max_entities]:
        friendly_name = state.name or state.entity_id
        lines.append(
            f"  - id: {state.entity_id}; name: {friendly_name}; state: {state.state}"
        )

    if len(exposed_states) > max_entities:
        lines.append(
            f"  - ... {len(exposed_states) - max_entities} additional exposed entities omitted"
        )

    lines.append(
        "Use only these exposed entities when answering or controlling Home Assistant."
    )

    return "\n".join(lines)
