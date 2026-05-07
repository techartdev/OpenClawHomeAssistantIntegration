"""OpenClaw conversation agent for Home Assistant Assist pipeline.

Registers OpenClaw as a native conversation agent so it can be used
with Assist, Voice PE, and any HA voice satellite.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import intent

from .api import OpenClawApiClient, OpenClawApiError
from .const import (
    ATTR_MESSAGE,
    ATTR_MODEL,
    ATTR_SESSION_ID,
    ATTR_TIMESTAMP,
    CONF_ASSIST_SESSION_ID,
    CONF_AGENT_ID,
    CONF_CONTEXT_MAX_CHARS,
    CONF_CONTEXT_STRATEGY,
    CONF_INCLUDE_EXPOSED_CONTEXT,
    CONF_VOICE_AGENT_ID,
    DEFAULT_ASSIST_SESSION_ID,
    DEFAULT_AGENT_ID,
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_CONTEXT_STRATEGY,
    DEFAULT_INCLUDE_EXPOSED_CONTEXT,
    DATA_MODEL,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
)
from .coordinator import OpenClawCoordinator
from .exposure import apply_context_policy, build_exposed_entities_context
from .helpers import extract_text_recursive

_LOGGER = logging.getLogger(__name__)

_VOICE_REQUEST_HEADERS = {
    "x-openclaw-source": "voice",
    "x-ha-voice": "true",
    "x-openclaw-message-channel": "voice",
}


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
        assistant_id = "conversation"
        options = self.entry.options
        voice_agent_id = self._normalize_optional_text(
            options.get(CONF_VOICE_AGENT_ID)
        )
        configured_agent_id = self._normalize_optional_text(
            options.get(
                CONF_AGENT_ID,
                self.entry.data.get(CONF_AGENT_ID, DEFAULT_AGENT_ID),
            )
        )
        resolved_agent_id = voice_agent_id or configured_agent_id
        conversation_id = self._resolve_conversation_id(user_input, resolved_agent_id)
        active_model = self._normalize_optional_text(options.get("active_model"))
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
                resolved_agent_id,
                system_prompt,
                active_model,
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
                            resolved_agent_id,
                            system_prompt,
                            active_model,
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

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(full_response)

        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=conversation_id,
            continue_conversation=self._should_continue(full_response),
        )

    def _resolve_conversation_id(
        self,
        user_input: conversation.ConversationInput,
        agent_id: str | None,
    ) -> str:
        """Return conversation id from HA with conservative agent namespacing."""
        configured_session_id = self._normalize_optional_text(
            self.entry.options.get(
                CONF_ASSIST_SESSION_ID,
                DEFAULT_ASSIST_SESSION_ID,
            )
        )
        if configured_session_id:
            return configured_session_id

        agent_suffix = self._normalize_optional_text(agent_id)

        if user_input.conversation_id:
            if agent_suffix:
                return f"{user_input.conversation_id}:{agent_suffix}"
            return user_input.conversation_id

        context = getattr(user_input, "context", None)
        user_id = getattr(context, "user_id", None)
        if user_id:
            base_id = f"assist_user_{user_id}"
            return f"{base_id}:{agent_suffix}" if agent_suffix else base_id

        device_id = getattr(user_input, "device_id", None)
        if device_id:
            base_id = f"assist_device_{device_id}"
            return f"{base_id}:{agent_suffix}" if agent_suffix else base_id

        return f"assist_default:{agent_suffix}" if agent_suffix else "assist_default"

    def _normalize_optional_text(self, value: Any) -> str | None:
        """Return a stripped string or None for blank values."""
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    async def _get_response(
        self,
        client: OpenClawApiClient,
        message: str,
        conversation_id: str,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> str:
        """Get a response from OpenClaw, trying streaming first."""
        full_response = ""
        async for chunk in client.async_stream_message(
            message=message,
            session_id=conversation_id,
            model=model,
            system_prompt=system_prompt,
            agent_id=agent_id,
            extra_headers=_VOICE_REQUEST_HEADERS,
        ):
            full_response += chunk

        if full_response:
            return full_response

        response = await client.async_send_message(
            message=message,
            session_id=conversation_id,
            model=model,
            system_prompt=system_prompt,
            agent_id=agent_id,
            extra_headers=_VOICE_REQUEST_HEADERS,
        )
        return extract_text_recursive(response) or ""

    @staticmethod
    def _should_continue(response: str) -> bool:
        """Determine if the conversation should continue after this response.

        Returns True when the assistant's reply ends with a question or
        an explicit prompt for follow-up, so that Voice PE and other
        satellites automatically re-listen without requiring a wake word.

        The heuristic checks for:
        - Trailing question marks (including after closing quotes/parens)
        - Common conversational follow-up patterns in English and German
        """
        if not response:
            return False

        text = response.strip()

        # Check if the response ends with a question mark
        # (allow trailing punctuation like quotes, parens, or emoji)
        if re.search(r"\?\s*[\"'»)\]]*\s*$", text):
            return True

        # Common follow-up patterns (EN + DE)
        lower = text.lower()
        follow_up_patterns = (
            "what do you think",
            "would you like",
            "do you want",
            "shall i",
            "should i",
            "can i help",
            "anything else",
            "let me know",
            "was meinst du",
            "möchtest du",
            "willst du",
            "soll ich",
            "kann ich",
            "noch etwas",
            "sonst noch",
        )
        for pattern in follow_up_patterns:
            if pattern in lower:
                return True

        return False

    def _error_result(
        self,
        user_input: conversation.ConversationInput,
        error_message: str,
    ) -> conversation.ConversationResult:
        """Build an error ConversationResult."""
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_error(
            intent.IntentResponseErrorCode.UNKNOWN,
            error_message,
        )
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
        )
