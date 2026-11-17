"""Shared helper utilities for the OpenClaw integration."""

from __future__ import annotations

from typing import Any


def scope_agent_session_id(base_id: str, agent_id: str | None) -> str:
    """Namespace a session key for an OpenClaw agent without double-prefixing.

    OpenClaw session keys are canonically lowercase. Home Assistant hands out
    conversation ids as uppercase ULIDs, and an uppercase base id is echoed
    back into the request envelope, refused on the session write, and rewritten
    on the next turn. That rewrite breaks the append-only history the provider
    prompt cache depends on, so every turn re-prefills the whole prompt.
    """
    key = base_id.lower()
    if not agent_id:
        return key
    prefix = f"agent:{agent_id.lower()}:"
    if key.startswith(prefix):
        return key
    return f"{prefix}{key}"


def resolve_active_model(
    preferred_model: str | None,
    available_models: list[str],
    gateway_model: str | None,
) -> str | None:
    """Choose the persisted model when it remains available.

    The gateway's first model is an inventory default, not a replacement for
    a model explicitly selected in Home Assistant.
    """
    if preferred_model and preferred_model in available_models:
        return preferred_model
    if gateway_model and gateway_model in available_models:
        return gateway_model
    return available_models[0] if available_models else None


def ssl_request_parameter(use_ssl: bool, verify_ssl: bool) -> bool | None:
    """Return aiohttp's per-request SSL verification setting."""
    return False if use_ssl and not verify_ssl else None


def extract_text_recursive(value: Any, depth: int = 0) -> str | None:
    """Recursively extract assistant text from nested response payloads."""
    if depth > 8:
        return None

    if isinstance(value, str):
        text = value.strip()
        return text or None

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            extracted = extract_text_recursive(item, depth + 1)
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
            extracted = extract_text_recursive(value.get(key), depth + 1)
            if extracted:
                return extracted

        for nested_value in value.values():
            extracted = extract_text_recursive(nested_value, depth + 1)
            if extracted:
                return extracted

    return None
