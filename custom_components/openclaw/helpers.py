"""Shared helper utilities for the OpenClaw integration."""

from __future__ import annotations

from typing import Any


def scope_agent_session_id(base_id: str, agent_id: str | None) -> str:
    """Namespace a session key for an OpenClaw agent without double-prefixing."""
    if not agent_id or base_id.startswith(f"agent:{agent_id}:"):
        return base_id
    return f"agent:{agent_id}:{base_id}"


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
