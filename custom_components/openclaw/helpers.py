"""Shared helper utilities for the OpenClaw integration."""

from __future__ import annotations

from typing import Any


def scope_agent_session_id(base_id: str, agent_id: str | None) -> str:
    """Namespace a session key for an OpenClaw agent without double-prefixing."""
    if not agent_id or base_id.startswith(f"agent:{agent_id}:"):
        return base_id
    return f"agent:{agent_id}:{base_id}"


def assist_base_session_id(
    conversation_id: str | None,
    user_id: str | None,
    device_id: str | None,
) -> str:
    """Pick the unscoped Assist session id without dropping the signed-in user.

    The pipeline sends a conversation id on every turn, which used to hide the user.
    """
    if user_id:
        user_base = f"assist_user_{user_id}"
        if not conversation_id:
            return user_base
        if (
            conversation_id.startswith(f"{user_base}:")
            or f":{user_base}:" in conversation_id
        ):
            return conversation_id
        return f"{user_base}:{conversation_id}"
    if conversation_id:
        return conversation_id
    if device_id:
        return f"assist_device_{device_id}"
    return "assist_default"


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
