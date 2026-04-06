"""OpenClaw conversation agent for Home Assistant Assist pipeline.

Registers OpenClaw as a native conversation agent so it can be used
with Assist, Voice PE, and any HA voice satellite.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Any, AsyncIterator

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import chat_session, intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    async_add_entities([OpenClawConversationAgent(hass, entry)])


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload the conversation agent."""
    return True


class OpenClawConversationAgent(
    conversation.ConversationEntity,
    conversation.AbstractConversationAgent,
):
    """Conversation agent that routes messages through OpenClaw.

    Enables OpenClaw to appear as a selectable agent in the Assist pipeline,
    allowing use with Voice PE, satellites, and the built-in HA Assist dialog.
    """

    _attr_supports_streaming = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the conversation agent."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title or "OpenClaw"

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
        backend_conversation_id = self._resolve_conversation_id(
            user_input,
            resolved_agent_id,
        )

        try:
            full_response, result = await self._async_process_with_chat_log(
                user_input=user_input,
                client=client,
                backend_conversation_id=backend_conversation_id,
                message=message,
                agent_id=resolved_agent_id,
                system_prompt=system_prompt,
                model=active_model,
            )
        except OpenClawApiError as err:
            _LOGGER.error("OpenClaw conversation error: %s", err)

            # Try token refresh if we have the capability
            refresh_fn = entry_data.get("refresh_token")
            if refresh_fn:
                refreshed = await refresh_fn()
                if refreshed:
                    try:
                        full_response, result = await self._async_process_with_chat_log(
                            user_input=user_input,
                            client=client,
                            backend_conversation_id=backend_conversation_id,
                            message=message,
                            agent_id=resolved_agent_id,
                            system_prompt=system_prompt,
                            model=active_model,
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
                ATTR_SESSION_ID: backend_conversation_id,
                ATTR_MODEL: (
                    coordinator.data.get(DATA_MODEL) if coordinator.data else None
                ),
                ATTR_TIMESTAMP: datetime.now(timezone.utc).isoformat(),
            },
        )
        coordinator.update_last_activity()
        return result

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
        """Get a non-streaming response from OpenClaw."""
        response = await client.async_send_message(
            message=message,
            session_id=conversation_id,
            model=model,
            system_prompt=system_prompt,
            agent_id=agent_id,
            extra_headers=_VOICE_REQUEST_HEADERS,
        )
        return extract_text_recursive(response) or ""

    async def _async_process_with_chat_log(
        self,
        user_input: conversation.ConversationInput,
        client: OpenClawApiClient,
        backend_conversation_id: str,
        message: str,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> tuple[str, conversation.ConversationResult]:
        """Write the assistant response into the Home Assistant chat log."""
        chat_log_conversation_id = user_input.conversation_id or backend_conversation_id

        with (
            chat_session.async_get_chat_session(
                self.hass,
                chat_log_conversation_id,
            ) as session,
            conversation.async_get_chat_log(
                self.hass,
                session,
                user_input,
            ) as chat_log,
        ):
            full_response = await self._async_populate_chat_log(
                chat_log=chat_log,
                client=client,
                message=message,
                conversation_id=backend_conversation_id,
                agent_id=agent_id,
                system_prompt=system_prompt,
                model=model,
            )
            result = conversation.async_get_result_from_chat_log(user_input, chat_log)
            result.continue_conversation = (
                self._should_continue(full_response) or result.continue_conversation
            )
            return full_response, result

    async def _async_populate_chat_log(
        self,
        chat_log: conversation.ChatLog,
        client: OpenClawApiClient,
        message: str,
        conversation_id: str,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> str:
        """Populate the HA chat log from streaming or fallback responses."""
        try:
            full_response = await self._async_stream_response_to_chat_log(
                chat_log=chat_log,
                client=client,
                message=message,
                conversation_id=conversation_id,
                agent_id=agent_id,
                system_prompt=system_prompt,
                model=model,
            )
            if full_response:
                return full_response
        except OpenClawApiError as err:
            _LOGGER.warning(
                "OpenClaw streaming failed, falling back to non-streaming response: %s",
                err,
            )

        full_response = await self._get_response(
            client=client,
            message=message,
            conversation_id=conversation_id,
            agent_id=agent_id,
            system_prompt=system_prompt,
            model=model,
        )
        self._add_final_response_to_chat_log(chat_log, full_response)
        return full_response

    async def _async_stream_response_to_chat_log(
        self,
        chat_log: conversation.ChatLog,
        client: OpenClawApiClient,
        message: str,
        conversation_id: str,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> str:
        """Stream OpenClaw deltas into the HA chat log."""
        full_response_parts: list[str] = []
        async for content in chat_log.async_add_delta_content_stream(
            self._chat_log_agent_id,
            self._async_openclaw_delta_stream(
                client=client,
                message=message,
                conversation_id=conversation_id,
                agent_id=agent_id,
                system_prompt=system_prompt,
                model=model,
            ),
        ):
            if isinstance(content, conversation.AssistantContent) and content.content:
                full_response_parts.append(content.content)
        return "".join(full_response_parts)

    async def _async_openclaw_delta_stream(
        self,
        client: OpenClawApiClient,
        message: str,
        conversation_id: str,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Map OpenClaw SSE chunks to the delta format expected by HA."""
        yield {"role": "assistant"}

        async for chunk in client.async_stream_message(
            message=message,
            session_id=conversation_id,
            model=model,
            system_prompt=system_prompt,
            agent_id=agent_id,
            extra_headers=_VOICE_REQUEST_HEADERS,
        ):
            if chunk:
                yield {"content": chunk}

    @property
    def _chat_log_agent_id(self) -> str:
        """Return the assistant identifier used for HA chat log messages."""
        return self.entity_id or self.entry.entry_id

    def _add_final_response_to_chat_log(
        self,
        chat_log: conversation.ChatLog,
        full_response: str,
    ) -> None:
        """Append a non-streaming final assistant message to the chat log."""
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(
                agent_id=self._chat_log_agent_id,
                content=full_response or None,
            )
        )

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
        # (allow trailing punctuation like quotes or parens)
        if re.search(r"\?\s*['\")\]]*\s*$", text):
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
