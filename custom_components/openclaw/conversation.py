"""OpenClaw conversation agent for Home Assistant Assist pipeline.

Registers OpenClaw as a native conversation agent so it can be used
with Assist, Voice PE, and any HA voice satellite.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import OpenClawApiClient, OpenClawApiError
from .const import (
    ATTR_MESSAGE,
    ATTR_MODEL,
    ATTR_SESSION_ID,
    ATTR_TIMESTAMP,
    CONF_CONTEXT_MAX_CHARS,
    CONF_CONTEXT_STRATEGY,
    CONF_INCLUDE_EXPOSED_CONTEXT,
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_CONTEXT_STRATEGY,
    DEFAULT_INCLUDE_EXPOSED_CONTEXT,
    DATA_MODEL,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
)
from .coordinator import OpenClawCoordinator
from .exposure import apply_context_policy, build_exposed_entities_context

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenClaw conversation agent."""
    agent = OpenClawConversationAgent(hass, entry)
    conversation.async_set_agent(hass, entry, agent)


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload the conversation agent."""
    conversation.async_unset_agent(hass, entry)
    return True


class OpenClawConversationAgent(conversation.AbstractConversationAgent):
    """Conversation agent that routes messages through OpenClaw.

    Enables OpenClaw to appear as a selectable agent in the Assist pipeline,
    allowing use with Voice PE, satellites, and the built-in HA Assist dialog.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the conversation agent."""
        self.hass = hass
        self.entry = entry

    @property
    def attribution(self) -> dict[str, str]:
        """Return attribution info."""
        return {"name": "Powered by OpenClaw", "url": "https://openclaw.dev"}

    @property
    def supported_languages(self) -> list[str] | str:
        """Return supported languages.

        OpenClaw handles language via its configured model, so we declare
        support for all languages and let the model handle translation.
        """
        return conversation.MATCH_ALL

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        """Process a user message through OpenClaw.

        Tries streaming first for lower latency (first-token fast).
        Falls back to non-streaming if the stream yields nothing.

        Args:
            user_input: The conversation input from HA Assist.

        Returns:
            ConversationResult with the assistant's response.
        """
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id)
        if not entry_data:
            return self._error_result(
                user_input, "OpenClaw integration not configured"
            )

        client: OpenClawApiClient = entry_data["client"]
        coordinator: OpenClawCoordinator = entry_data["coordinator"]

        message = user_input.text
        conversation_id = user_input.conversation_id or "default"
        assistant_id = "conversation"
        options = self.entry.options
        include_context = options.get(
            CONF_INCLUDE_EXPOSED_CONTEXT,
            DEFAULT_INCLUDE_EXPOSED_CONTEXT,
        )
        max_chars = int(options.get(CONF_CONTEXT_MAX_CHARS, DEFAULT_CONTEXT_MAX_CHARS))
        strategy = options.get(CONF_CONTEXT_STRATEGY, DEFAULT_CONTEXT_STRATEGY)

        raw_context = (
            build_exposed_entities_context(
                self.hass,
                assistant=assistant_id,
            )
            if include_context
            else None
        )
        exposed_context = apply_context_policy(raw_context, max_chars, strategy)
        extra_system_prompt = getattr(user_input, "extra_system_prompt", None)
        system_prompt = "\n\n".join(
            part for part in (exposed_context, extra_system_prompt) if part
        ) or None

        try:
            full_response = await self._get_response(
                client,
                message,
                conversation_id,
                system_prompt,
            )
        except OpenClawApiError as err:
            _LOGGER.error("OpenClaw conversation error: %s", err)

            # Try token refresh if we have the capability
            refresh_fn = entry_data.get("refresh_token")
            if refresh_fn:
                refreshed = await refresh_fn()
                if refreshed:
                    try:
                        full_response = await self._get_response(
                            client,
                            message,
                            conversation_id,
                            system_prompt,
                        )
                    except OpenClawApiError as retry_err:
                        return self._error_result(
                            user_input,
                            f"Error communicating with OpenClaw: {retry_err}",
                        )
                else:
                    return self._error_result(
                        user_input,
                        f"Error communicating with OpenClaw: {err}",
                    )
            else:
                return self._error_result(
                    user_input,
                    f"Error communicating with OpenClaw: {err}",
                )

        # Fire event so automations can react to the response
        self.hass.bus.async_fire(
            EVENT_MESSAGE_RECEIVED,
            {
                ATTR_MESSAGE: full_response,
                ATTR_SESSION_ID: conversation_id,
                ATTR_MODEL: coordinator.data.get(DATA_MODEL) if coordinator.data else None,
                ATTR_TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )
        coordinator.update_last_activity()

        intent_response = conversation.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(full_response)

        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=conversation_id,
        )

    async def _get_response(
        self,
        client: OpenClawApiClient,
        message: str,
        conversation_id: str,
        system_prompt: str | None = None,
    ) -> str:
        """Get a response from OpenClaw, trying streaming first."""
        # Try streaming (lower TTFB for voice pipeline)
        full_response = ""
        async for chunk in client.async_stream_message(
            message=message,
            session_id=conversation_id,
            system_prompt=system_prompt,
        ):
            full_response += chunk

        if full_response:
            return full_response

        # Fallback to non-streaming
        response = await client.async_send_message(
            message=message,
            session_id=conversation_id,
            system_prompt=system_prompt,
        )
        extracted = self._extract_text_recursive(response)
        return extracted or ""

    def _extract_text_recursive(self, value: Any, depth: int = 0) -> str | None:
        """Recursively extract assistant text from nested response payloads."""
        if depth > 8:
            return None

        if isinstance(value, str):
            text = value.strip()
            return text or None

        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                extracted = self._extract_text_recursive(item, depth + 1)
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
                extracted = self._extract_text_recursive(value.get(key), depth + 1)
                if extracted:
                    return extracted

            for nested_value in value.values():
                extracted = self._extract_text_recursive(nested_value, depth + 1)
                if extracted:
                    return extracted

        return None

    def _error_result(
        self,
        user_input: conversation.ConversationInput,
        error_message: str,
    ) -> conversation.ConversationResult:
        """Build an error ConversationResult."""
        intent_response = conversation.IntentResponse(language=user_input.language)
        intent_response.async_set_error(
            conversation.IntentResponseErrorCode.UNKNOWN,
            error_message,
        )
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
        )
