from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "custom_components.openclaw.conversation"
MODULE_PATH = REPO_ROOT / "custom_components" / "openclaw" / "conversation.py"


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event_type: str, event_data: dict[str, Any]) -> None:
        self.events.append((event_type, event_data))


class FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.bus = FakeBus()
        self._last_chat_log: FakeChatLog | None = None


@dataclass
class FakeConfigEntry:
    entry_id: str
    title: str
    data: dict[str, Any]
    options: dict[str, Any]


@dataclass
class FakeContext:
    user_id: str | None = None


@dataclass
class FakeConversationInput:
    text: str
    context: FakeContext
    conversation_id: str | None
    device_id: str | None
    satellite_id: str | None
    language: str
    agent_id: str
    extra_system_prompt: str | None = None


@dataclass
class FakeConversationResult:
    response: Any
    conversation_id: str | None = None
    continue_conversation: bool = False


@dataclass
class FakeAssistantContent:
    agent_id: str
    content: str | None = None


class FakeIntentResponse:
    def __init__(self, language: str) -> None:
        self.language = language
        self.speech: str = ""
        self.error: tuple[str, str] | None = None

    def async_set_speech(self, speech: str) -> None:
        self.speech = speech

    def async_set_error(self, code: str, message: str) -> None:
        self.error = (code, message)


class FakeConversationEntity:
    _attr_supports_streaming = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.entity_id: str | None = None

    @property
    def supports_streaming(self) -> bool:
        return self._attr_supports_streaming

    async def async_added_to_hass(self) -> None:
        return None

    async def async_will_remove_from_hass(self) -> None:
        return None


class FakeAbstractConversationAgent:
    pass


class FakeChatLog:
    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        self.deltas: list[dict[str, Any]] = []
        self.added: list[FakeAssistantContent] = []
        self.continue_conversation = False

    async def async_add_delta_content_stream(
        self,
        agent_id: str,
        stream,
    ):
        full_response = ""
        async for delta in stream:
            self.deltas.append(delta)
            if content := delta.get("content"):
                full_response += content

        if full_response:
            assistant_content = FakeAssistantContent(
                agent_id=agent_id,
                content=full_response,
            )
            self.added.append(assistant_content)
            yield assistant_content

    def async_add_assistant_content_without_tools(
        self,
        content: FakeAssistantContent,
    ) -> None:
        self.added.append(content)


class FakeCoordinator:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}
        self.updated = False

    def update_last_activity(self) -> None:
        self.updated = True


class FakeClient:
    def __init__(
        self,
        *,
        stream_chunks: list[str] | None = None,
        response: dict[str, Any] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.stream_chunks = stream_chunks or []
        self.response = response or {"text": ""}
        self.stream_error = stream_error
        self.stream_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []

    async def async_stream_message(self, **kwargs: Any):
        self.stream_calls.append(kwargs)
        if self.stream_error is not None:
            raise self.stream_error

        for chunk in self.stream_chunks:
            yield chunk

    async def async_send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.send_calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _extract_text_recursive(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("output_text", "text", "content", "message", "response", "answer"):
            nested = value.get(key)
            if nested:
                return _extract_text_recursive(nested)
    return None


def _install_stub_modules() -> None:
    for name in list(sys.modules):
        if name == "homeassistant" or name.startswith("homeassistant."):
            sys.modules.pop(name)
        if name == "custom_components" or name.startswith("custom_components.openclaw"):
            sys.modules.pop(name)

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    helpers = types.ModuleType("homeassistant.helpers")

    conversation_module = types.ModuleType("homeassistant.components.conversation")
    conversation_module.MATCH_ALL = "*"
    conversation_module.ConversationEntity = FakeConversationEntity
    conversation_module.AbstractConversationAgent = FakeAbstractConversationAgent
    conversation_module.ConversationInput = FakeConversationInput
    conversation_module.ConversationResult = FakeConversationResult
    conversation_module.ChatLog = FakeChatLog
    conversation_module.AssistantContent = FakeAssistantContent
    conversation_module.async_set_agent = lambda hass, entry, agent: None
    conversation_module.async_unset_agent = lambda hass, entry: None

    @contextmanager
    def async_get_chat_log(hass: FakeHass, session, user_input):
        chat_log = FakeChatLog(session.conversation_id)
        hass._last_chat_log = chat_log
        yield chat_log

    def async_get_result_from_chat_log(user_input: FakeConversationInput, chat_log: FakeChatLog):
        response = FakeIntentResponse(user_input.language)
        last_content = chat_log.added[-1].content if chat_log.added else ""
        response.async_set_speech(last_content or "")
        return FakeConversationResult(
            response=response,
            conversation_id=chat_log.conversation_id,
            continue_conversation=chat_log.continue_conversation,
        )

    conversation_module.async_get_chat_log = async_get_chat_log
    conversation_module.async_get_result_from_chat_log = async_get_result_from_chat_log

    chat_session_module = types.ModuleType("homeassistant.helpers.chat_session")

    @contextmanager
    def async_get_chat_session(hass: FakeHass, conversation_id: str | None):
        yield types.SimpleNamespace(
            conversation_id=conversation_id or "generated-conversation-id"
        )

    chat_session_module.async_get_chat_session = async_get_chat_session

    intent_module = types.ModuleType("homeassistant.helpers.intent")
    intent_module.IntentResponse = FakeIntentResponse
    intent_module.IntentResponseErrorCode = types.SimpleNamespace(UNKNOWN="unknown")

    entity_platform_module = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform_module.AddEntitiesCallback = object

    config_entries_module = types.ModuleType("homeassistant.config_entries")
    config_entries_module.ConfigEntry = FakeConfigEntry

    core_module = types.ModuleType("homeassistant.core")
    core_module.HomeAssistant = FakeHass

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]

    openclaw_package = types.ModuleType("custom_components.openclaw")
    openclaw_package.__path__ = [str(REPO_ROOT / "custom_components" / "openclaw")]

    api_module = types.ModuleType("custom_components.openclaw.api")

    class OpenClawApiError(Exception):
        pass

    class OpenClawApiClient:
        pass

    api_module.OpenClawApiError = OpenClawApiError
    api_module.OpenClawApiClient = OpenClawApiClient

    const_module = types.ModuleType("custom_components.openclaw.const")
    const_values = {
        "ATTR_MESSAGE": "message",
        "ATTR_MODEL": "model",
        "ATTR_SESSION_ID": "session_id",
        "ATTR_TIMESTAMP": "timestamp",
        "CONF_ASSIST_SESSION_ID": "assist_session_id",
        "CONF_AGENT_ID": "agent_id",
        "CONF_CONTEXT_MAX_CHARS": "context_max_chars",
        "CONF_CONTEXT_STRATEGY": "context_strategy",
        "CONF_INCLUDE_EXPOSED_CONTEXT": "include_exposed_context",
        "CONF_VOICE_AGENT_ID": "voice_agent_id",
        "DEFAULT_ASSIST_SESSION_ID": "",
        "DEFAULT_AGENT_ID": "main",
        "DEFAULT_CONTEXT_MAX_CHARS": 13000,
        "DEFAULT_CONTEXT_STRATEGY": "truncate",
        "DEFAULT_INCLUDE_EXPOSED_CONTEXT": True,
        "DATA_MODEL": "model",
        "DOMAIN": "openclaw",
        "EVENT_MESSAGE_RECEIVED": "openclaw_message_received",
    }
    for key, value in const_values.items():
        setattr(const_module, key, value)

    coordinator_module = types.ModuleType("custom_components.openclaw.coordinator")
    coordinator_module.OpenClawCoordinator = FakeCoordinator

    exposure_module = types.ModuleType("custom_components.openclaw.exposure")
    exposure_module.apply_context_policy = lambda raw, max_chars, strategy: raw
    exposure_module.build_exposed_entities_context = lambda hass, assistant: None

    helpers_module = types.ModuleType("custom_components.openclaw.helpers")
    helpers_module.extract_text_recursive = _extract_text_recursive

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.conversation"] = conversation_module
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.chat_session"] = chat_session_module
    sys.modules["homeassistant.helpers.intent"] = intent_module
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform_module
    sys.modules["homeassistant.config_entries"] = config_entries_module
    sys.modules["homeassistant.core"] = core_module
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.openclaw"] = openclaw_package
    sys.modules["custom_components.openclaw.api"] = api_module
    sys.modules["custom_components.openclaw.const"] = const_module
    sys.modules["custom_components.openclaw.coordinator"] = coordinator_module
    sys.modules["custom_components.openclaw.exposure"] = exposure_module
    sys.modules["custom_components.openclaw.helpers"] = helpers_module


def _load_conversation_module():
    _install_stub_modules()
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def conversation_module():
    return _load_conversation_module()


def _make_agent(conversation_module, *, client: FakeClient, options: dict[str, Any] | None = None):
    hass = FakeHass()
    entry = FakeConfigEntry(
        entry_id="entry-1",
        title="OpenClaw",
        data={"agent_id": "main"},
        options=options or {},
    )
    coordinator = FakeCoordinator({"model": "model-x"})
    hass.data[conversation_module.DOMAIN] = {
        entry.entry_id: {
            "client": client,
            "coordinator": coordinator,
        }
    }
    agent = conversation_module.OpenClawConversationAgent(hass, entry)
    agent.entity_id = "conversation.openclaw"
    return agent, hass, coordinator


def _make_user_input(*, text: str, conversation_id: str | None = "conv-1"):
    return FakeConversationInput(
        text=text,
        context=FakeContext(user_id="user-123"),
        conversation_id=conversation_id,
        device_id=None,
        satellite_id=None,
        language="en",
        agent_id="openclaw",
    )


def test_async_process_streams_into_chat_log(conversation_module) -> None:
    client = FakeClient(stream_chunks=["Ala ", "ma ", "kota"])
    agent, hass, coordinator = _make_agent(conversation_module, client=client)

    result = asyncio.run(agent.async_process(_make_user_input(text="Hello there")))

    assert result.response.speech == "Ala ma kota"
    assert result.conversation_id == "conv-1"
    assert coordinator.updated is True
    assert client.send_calls == []
    assert client.stream_calls[0]["session_id"] == "conv-1:main"
    assert hass._last_chat_log is not None
    assert hass._last_chat_log.deltas == [
        {"role": "assistant"},
        {"content": "Ala "},
        {"content": "ma "},
        {"content": "kota"},
    ]
    assert hass.bus.events[0][1]["session_id"] == "conv-1:main"


def test_async_process_falls_back_when_stream_is_empty(conversation_module) -> None:
    client = FakeClient(stream_chunks=[], response={"text": "Fallback reply"})
    agent, hass, _ = _make_agent(conversation_module, client=client)

    result = asyncio.run(agent.async_process(_make_user_input(text="Hello there")))

    assert result.response.speech == "Fallback reply"
    assert len(client.send_calls) == 1
    assert hass._last_chat_log is not None
    assert hass._last_chat_log.added[-1].content == "Fallback reply"


def test_agent_advertises_streaming_support(conversation_module) -> None:
    agent, _, _ = _make_agent(conversation_module, client=FakeClient())

    assert agent.supports_streaming is True
    assert agent._attr_supports_streaming is True


def test_entity_agent_skips_legacy_agent_registration(conversation_module) -> None:
    agent, hass, _ = _make_agent(conversation_module, client=FakeClient())
    calls: list[str] = []

    def _set_agent(*args: Any, **kwargs: Any) -> None:
        calls.append("set")

    def _unset_agent(*args: Any, **kwargs: Any) -> None:
        calls.append("unset")

    conversation_module.conversation.async_set_agent = _set_agent
    conversation_module.conversation.async_unset_agent = _unset_agent

    asyncio.run(agent.async_added_to_hass())
    assert (
        hass.data[conversation_module.DOMAIN][agent.entry.entry_id]["conversation_entity_id"]
        == "conversation.openclaw"
    )
    asyncio.run(agent.async_will_remove_from_hass())

    assert calls == []
    assert (
        "conversation_entity_id"
        not in hass.data[conversation_module.DOMAIN][agent.entry.entry_id]
    )


def test_conversation_id_resolution_keeps_agent_namespace(conversation_module) -> None:
    agent, _, _ = _make_agent(conversation_module, client=FakeClient())
    user_input = _make_user_input(text="Hello there", conversation_id="session-42")

    assert agent._resolve_conversation_id(user_input, "assistant-a") == "session-42:assistant-a"


def test_question_replies_keep_continue_conversation(conversation_module) -> None:
    client = FakeClient(stream_chunks=["Need anything else?"])
    agent, _, _ = _make_agent(conversation_module, client=client)

    result = asyncio.run(agent.async_process(_make_user_input(text="Hello there")))

    assert result.continue_conversation is True
