"""OpenClaw conversation agent for Home Assistant Assist pipeline.

Registers OpenClaw as a native conversation agent so it can be used
with Assist, Voice PE, and any HA voice satellite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
import logging
import re
from typing import Any

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.helpers import intent

from .api import OpenClawApiClient, OpenClawApiError, OpenClawConnectionError, OpenClawAuthError
from .const import (
    ATTR_MESSAGE,
    ATTR_MODEL,
    ATTR_SESSION_ID,
    ATTR_TIMESTAMP,
    CONF_AGENT_ID,
    CONF_CONTEXT_MAX_CHARS,
    CONF_CONTEXT_STRATEGY,
    CONF_DEBUG_LOGGING,
    CONF_INCLUDE_EXPOSED_CONTEXT,
    CONF_VOICE_AGENT_ID,
    DEFAULT_AGENT_ID,
    DEFAULT_CONTEXT_MAX_CHARS,
    DEFAULT_CONTEXT_STRATEGY,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_INCLUDE_EXPOSED_CONTEXT,
    DATA_MODEL,
    DOMAIN,
    EVENT_MESSAGE_RECEIVED,
    DATA_ASSIST_SESSIONS,
    DATA_ASSIST_SESSION_STORE,
    ASSIST_SESSION_STORE_KEY,
)
from .coordinator import OpenClawCoordinator
from .exposure import apply_context_policy, build_exposed_entities_context
from .utils import extract_text_recursive, normalize_optional_text

_LOGGER = logging.getLogger(__name__)

_VOICE_REQUEST_HEADERS = {
    "x-openclaw-source": "voice",
    "x-ha-voice": "true",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the OpenClaw conversation agent."""
    # Load persisted assist sessions
    store = Store(hass, 1, ASSIST_SESSION_STORE_KEY)
    stored = await store.async_load() or {}
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][DATA_ASSIST_SESSIONS] = stored
    hass.data[DOMAIN][DATA_ASSIST_SESSION_STORE] = store

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
        voice_agent_id = normalize_optional_text(
            options.get(CONF_VOICE_AGENT_ID)
        )
        configured_agent_id = normalize_optional_text(
            options.get(
                CONF_AGENT_ID,
                self.entry.data.get(CONF_AGENT_ID, DEFAULT_AGENT_ID),
            )
        )
        resolved_agent_id = voice_agent_id or configured_agent_id
        conversation_id = self._resolve_conversation_id(user_input, resolved_agent_id)
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

        # Resolve the originating device's area for room-aware responses
        device_area_context = self._resolve_device_area(user_input)

        system_prompt = "\n\n".join(
            part
            for part in (device_area_context, exposed_context, extra_system_prompt)
            if part
        ) or None

        # Add device/area headers when available
        device_id = getattr(user_input, "device_id", None)
        if device_id or device_area_context:
            voice_headers = dict(_VOICE_REQUEST_HEADERS)
            if device_id:
                voice_headers["x-openclaw-device-id"] = device_id
            if device_area_context:
                area_name = device_area_context.removeprefix("[Voice command from: ").removesuffix("]")
                voice_headers["x-openclaw-area"] = area_name
        else:
            voice_headers = None

        if options.get(CONF_DEBUG_LOGGING, DEFAULT_DEBUG_LOGGING):
            _LOGGER.info(
                "OpenClaw Assist routing: agent=%s session=%s area=%s",
                resolved_agent_id or "main",
                conversation_id,
                voice_headers.get("x-openclaw-area", "unknown") if voice_headers else "none",
            )

        try:
            full_response = await self._get_response(
                client,
                message,
                conversation_id,
                resolved_agent_id,
                system_prompt,
                voice_headers,
            )
        except OpenClawApiError as err:
            _LOGGER.error("OpenClaw conversation error: %s", err)
            error_code = self._map_error_code(err)

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
                            voice_headers,
                        )
                    except OpenClawApiError as retry_err:
                        return self._error_result(
                            user_input,
                            f"Error communicating with OpenClaw: {retry_err}",
                            self._map_error_code(retry_err),
                        )
                else:
                    return self._error_result(
                        user_input,
                        f"Error communicating with OpenClaw: {err}",
                        error_code,
                    )
            else:
                return self._error_result(
                    user_input,
                    f"Error communicating with OpenClaw: {err}",
                    error_code,
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

    def _resolve_conversation_id(self, user_input: conversation.ConversationInput, agent_id: str | None) -> str:
        """Return a stable, agent-scoped session key persisted across HA restarts."""
        domain_store = self.hass.data.setdefault(DOMAIN, {})
        session_cache = domain_store.setdefault(DATA_ASSIST_SESSIONS, {})
        cache_key = agent_id or "main"
        cached_session = session_cache.get(cache_key)
        if cached_session:
            return cached_session

        new_session = f"agent:{cache_key}:assist_{uuid4().hex[:12]}"
        session_cache[cache_key] = new_session

        store = domain_store.get(DATA_ASSIST_SESSION_STORE)
        if store:
            self.hass.async_create_task(store.async_save(session_cache))

        return new_session

    def _resolve_device_area(
        self, user_input: conversation.ConversationInput
    ) -> str | None:
        """Resolve the area name for the device that initiated the conversation.

        Returns a short context string like '[Voice command from: Study]'
        so the agent knows which room the user is in.
        """
        device_id = getattr(user_input, "device_id", None)
        if not device_id:
            return None

        try:
            dev_reg = dr.async_get(self.hass)
            device_entry = dev_reg.async_get(device_id)
            if not device_entry or not device_entry.area_id:
                return None

            area_reg = ar.async_get(self.hass)
            area_entry = area_reg.async_get_area(device_entry.area_id)
            if not area_entry:
                return None

            return f"[Voice command from: {area_entry.name}]"
        except Exception:
            _LOGGER.debug("Could not resolve area for device %s", device_id)
            return None

    async def _get_response(
        self,
        client: OpenClawApiClient,
        message: str,
        conversation_id: str,
        agent_id: str | None = None,
        system_prompt: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        """Get a response from OpenClaw, trying streaming first."""
        headers = extra_headers or _VOICE_REQUEST_HEADERS
        model_override = f"openclaw:{agent_id}" if agent_id else None

        # Try streaming (lower TTFB for voice pipeline)
        full_response = ""
        async for chunk in client.async_stream_message(
            message=message,
            session_id=conversation_id,
            model=model_override,
            system_prompt=system_prompt,
            agent_id=agent_id,
            extra_headers=headers,
        ):
            full_response += chunk

        if full_response:
            return full_response

        # Fallback to non-streaming
        response = await client.async_send_message(
            message=message,
            session_id=conversation_id,
            model=model_override,
            system_prompt=system_prompt,
            agent_id=agent_id,
            extra_headers=headers,
        )
        extracted = extract_text_recursive(response)
        return extracted or ""

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
        if re.search(r"\?\s*[\"'\u201c\u201d\u00bb)\]]*\s*$", text):
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

    @staticmethod
    def _map_error_code(err: OpenClawApiError) -> intent.IntentResponseErrorCode:
        """Map OpenClaw exceptions to HA intent error codes."""
        if isinstance(err, (OpenClawConnectionError, OpenClawAuthError)):
            return intent.IntentResponseErrorCode.FAILED_TO_HANDLE
        return intent.IntentResponseErrorCode.UNKNOWN

    def _error_result(
        self,
        user_input: conversation.ConversationInput,
        error_message: str,
        error_code: intent.IntentResponseErrorCode = intent.IntentResponseErrorCode.UNKNOWN,
    ) -> conversation.ConversationResult:
        """Build an error ConversationResult."""
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_error(
            error_code,
            error_message,
        )
        return conversation.ConversationResult(
            response=intent_response,
            conversation_id=user_input.conversation_id,
        )
