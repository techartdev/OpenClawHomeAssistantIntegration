"""Shared helper utilities for the OpenClaw integration."""

from __future__ import annotations

import re
from typing import Any


def scope_agent_session_id(base_id: str, agent_id: str | None) -> str:
    """Namespace a session key for an OpenClaw agent without double-prefixing."""
    if not agent_id or base_id.startswith(f"agent:{agent_id}:"):
        return base_id
    return f"agent:{agent_id}:{base_id}"


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


# --- Speech (TTS) text normalisation -----------------------------------------
#
# Assist passes ``intent_response.speech`` straight to text-to-speech, so any
# markdown left in an assistant reply is read out literally
# ("asterisk asterisk bold text asterisk asterisk"). The helpers below remove
# the markup but keep the words, numbers and emoji. The chat card and the
# ``openclaw_message_received`` event keep receiving the raw response.

_MARKDOWN_LINE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ``` / ~~~ code fence lines
    (re.compile(r"^[ \t]{0,3}(?:```|~~~)[^\n]*$", re.MULTILINE), ""),
    # # headings
    (re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE), ""),
    # > block quotes
    (re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE), ""),
    # bullets (-, *, +) and numbered lists (1. / 1))
    (re.compile(r"^[ \t]{0,3}(?:[-*+]|\d{1,3}[.)])[ \t]+", re.MULTILINE), ""),
)

_MARKDOWN_INLINE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # [text](url) and ![alt](url) -> keep the visible text
    (re.compile(r"!?\[([^\[\]]*)\]\([^()]*\)"), r"\1"),
    # `code` / ``code`` -> keep the content
    (re.compile(r"`{1,2}([^`]+)`{1,2}"), r"\1"),
    # **bold** (may span line breaks in streamed replies)
    (re.compile(r"(?<!\*)\*\*(?!\s)(.+?)(?<!\s)\*\*(?!\*)", re.DOTALL), r"\1"),
    # __bold__
    (re.compile(r"(?<![\w_])__(?![\s_])(.+?)(?<![\s_])__(?![\w_])", re.DOTALL), r"\1"),
    # *italic* / _italic_, guarded so maths such as 3*4 is left intact
    (re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", re.DOTALL), r"\1"),
    (re.compile(r"(?<![\w_])_(?![\s_])(.+?)(?<![\s_])_(?![\w_])", re.DOTALL), r"\1"),
    # ~~strikethrough~~
    (re.compile(r"~~(?!\s)(.+?)(?<!\s)~~", re.DOTALL), r"\1"),
)

# A leftover emphasis run (markup without a closing pair) would still be spoken
# as "asterisk asterisk". Single * and _ are deliberately left alone.
_MARKDOWN_LEFTOVER_RE = re.compile(r"\*{2,}")


def strip_markdown_for_speech(text: str) -> str:
    """Return ``text`` with markdown markup removed, ready for text-to-speech.

    Only formatting is dropped: words, punctuation, numbers and emoji survive.
    """
    if not text:
        return text

    cleaned = text
    for pattern, replacement in _MARKDOWN_LINE_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _MARKDOWN_INLINE_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = _MARKDOWN_LEFTOVER_RE.sub("", cleaned)

    # Removing markup can leave trailing spaces and empty lines behind.
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() or text.strip()
