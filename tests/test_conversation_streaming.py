"""Regression coverage for native Assist streaming without HA runtime deps."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from typing import Any


REPO_ROOT = Path(__file__).parents[1]
MODULE_NAME = "custom_components.openclaw.conversation"
MODULE_PATH = REPO_ROOT / "custom_components" / "openclaw" / "conversation.py"


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def async_fire(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))


class FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.bus = FakeBus()
        self.last_chat_log: FakeChatLog | None = None


@dataclass
class FakeEntry:
    entry_id: str = "entry-1"
    title: str = "OpenClaw"
    data: dict[str, Any] = None  # type: ignore[assignment]
    options: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.data = self.data or {"agent_id": "main"}
        self.options = self.options or {}


@dataclass
class FakeContext:
    user_id: str | None = "user-123"


@dataclass
class FakeInput:
    text: str
    conversation_id: str | None = "conv-1"
    context: FakeContext = None  # type: ignore[assignment]
    device_id: str | None = None
    language: str = "en"

    def __post_init__(self) -> None:
        self.context = self.context or FakeContext()


class FakeIntentResponse:
    def __init__(self, language: str) -> None:
        self.language = language
        self.speech = ""
        self.error: tuple[str, str] | None = None

    def async_set_speech(self, speech: str) -> None:
        self.speech = speech

    def async_set_error(self, code: str, message: str) -> None:
        self.error = (code, message)


@dataclass
class FakeResult:
    response: FakeIntentResponse
    conversation_id: str | None = None
    continue_conversation: bool = False


@dataclass
class FakeAssistantContent:
    agent_id: str
    content: str | None = None


class FakeChatLog:
    def __init__(self, conversation_id: str | None) -> None:
        self.conversation_id = conversation_id or "generated-id"
        self.deltas: list[dict[str, str]] = []
        self.contents: list[FakeAssistantContent] = []
        self.continue_conversation = False

    async def async_add_delta_content_stream(self, agent_id: str, stream):
        text = ""
        async for delta in stream:
            self.deltas.append(delta)
            text += delta.get("content", "")
        if text:
            content = FakeAssistantContent(agent_id, text)
            self.contents.append(content)
            yield content

    def async_add_assistant_content_without_tools(
        self, content: FakeAssistantContent
    ) -> None:
        self.contents.append(content)


class FakeConversationEntity:
    _attr_supports_streaming = False

    async def async_added_to_hass(self) -> None:
        return None

    async def async_will_remove_from_hass(self) -> None:
        return None

    async def async_process(self, user_input: FakeInput) -> FakeResult:
        chat_log = FakeChatLog(user_input.conversation_id)
        self.hass.last_chat_log = chat_log
        return await self._async_handle_message(user_input, chat_log)


class FakeCoordinator:
    def __init__(self) -> None:
        self.data = {"model": "model-x"}
        self.updated = False

    def update_last_activity(self) -> None:
        self.updated = True


class FakeClient:
    def __init__(self, chunks: list[str] | None = None, response: str = "") -> None:
        self.chunks = chunks or []
        self.response = response
        self.stream_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []

    async def async_stream_message(self, **kwargs: Any):
        self.stream_calls.append(kwargs)
        for chunk in self.chunks:
            yield chunk

    async def async_send_message(self, **kwargs: Any) -> dict[str, str]:
        self.send_calls.append(kwargs)
        return {"text": self.response}


def _install_stubs() -> None:
    for name in list(sys.modules):
        if name == "homeassistant" or name.startswith("homeassistant."):
            sys.modules.pop(name)
        if name == "custom_components" or name.startswith("custom_components.openclaw"):
            sys.modules.pop(name)

    conversation = types.ModuleType("homeassistant.components.conversation")
    conversation.MATCH_ALL = "*"
    conversation.ConversationEntity = FakeConversationEntity
    conversation.AbstractConversationAgent = type("AbstractConversationAgent", (), {})
    conversation.ConversationInput = FakeInput
    conversation.ConversationResult = FakeResult
    conversation.ChatLog = FakeChatLog
    conversation.AssistantContent = FakeAssistantContent
    conversation.async_set_agent = lambda hass, entry, agent: None
    conversation.async_unset_agent = lambda hass, entry: None
    conversation.async_get_chat_log = object()
    conversation.async_get_result_from_chat_log = lambda user_input, chat_log: FakeResult(
        FakeIntentResponse(user_input.language), chat_log.conversation_id, chat_log.continue_conversation
    )
    original_result = conversation.async_get_result_from_chat_log

    def result_from_chat_log(user_input, chat_log):
        result = original_result(user_input, chat_log)
        result.response.async_set_speech(chat_log.contents[-1].content if chat_log.contents else "")
        return result

    conversation.async_get_result_from_chat_log = result_from_chat_log

    intent = types.ModuleType("homeassistant.helpers.intent")
    intent.IntentResponse = FakeIntentResponse
    intent.IntentResponseErrorCode = types.SimpleNamespace(UNKNOWN="unknown")

    api = types.ModuleType("custom_components.openclaw.api")
    api.OpenClawApiClient = FakeClient
    api.OpenClawApiError = type("OpenClawApiError", (Exception,), {})

    const = types.ModuleType("custom_components.openclaw.const")
    for key, value in {
        "ATTR_MESSAGE": "message", "ATTR_MODEL": "model", "ATTR_SESSION_ID": "session_id",
        "ATTR_TIMESTAMP": "timestamp", "CONF_ASSIST_SESSION_ID": "assist_session_id",
        "CONF_AGENT_ID": "agent_id", "CONF_CONTEXT_MAX_CHARS": "context_max_chars",
        "CONF_CONTEXT_STRATEGY": "context_strategy", "CONF_INCLUDE_EXPOSED_CONTEXT": "include_exposed_context",
        "CONF_VOICE_AGENT_ID": "voice_agent_id", "DEFAULT_ASSIST_SESSION_ID": "",
        "DEFAULT_AGENT_ID": "main", "DEFAULT_CONTEXT_MAX_CHARS": 13000,
        "DEFAULT_CONTEXT_STRATEGY": "truncate", "DEFAULT_INCLUDE_EXPOSED_CONTEXT": True,
        "DATA_MODEL": "model", "DOMAIN": "openclaw", "EVENT_MESSAGE_RECEIVED": "openclaw_message_received",
    }.items():
        setattr(const, key, value)

    helpers = types.ModuleType("custom_components.openclaw.helpers")
    helpers.extract_text_recursive = lambda value: value.get("text") if isinstance(value, dict) else value
    helpers.scope_agent_session_id = lambda base, agent: f"agent:{agent}:{base}" if agent and not base.startswith(f"agent:{agent}:") else base

    packages = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.config_entries": types.ModuleType("homeassistant.config_entries"),
        "homeassistant.core": types.ModuleType("homeassistant.core"),
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity_platform": types.ModuleType("homeassistant.helpers.entity_platform"),
        "custom_components": types.ModuleType("custom_components"),
        "custom_components.openclaw": types.ModuleType("custom_components.openclaw"),
    }
    packages["homeassistant.config_entries"].ConfigEntry = FakeEntry
    packages["homeassistant.core"].HomeAssistant = FakeHass
    packages["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    packages["custom_components"].__path__ = [str(REPO_ROOT / "custom_components")]
    packages["custom_components.openclaw"].__path__ = [str(REPO_ROOT / "custom_components" / "openclaw")]
    sys.modules.update(packages)
    sys.modules["homeassistant.components.conversation"] = conversation
    sys.modules["homeassistant.helpers.intent"] = intent
    sys.modules["custom_components.openclaw.api"] = api
    sys.modules["custom_components.openclaw.const"] = const
    coordinator = types.ModuleType("custom_components.openclaw.coordinator")
    coordinator.OpenClawCoordinator = FakeCoordinator
    sys.modules["custom_components.openclaw.coordinator"] = coordinator
    exposure = types.ModuleType("custom_components.openclaw.exposure")
    exposure.apply_context_policy = lambda raw, max_chars, strategy: raw
    exposure.build_exposed_entities_context = lambda hass, assistant: None
    sys.modules["custom_components.openclaw.exposure"] = exposure
    sys.modules["custom_components.openclaw.helpers"] = helpers


def _load_module():
    _install_stubs()
    spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _agent(module, client: FakeClient):
    hass = FakeHass()
    entry = FakeEntry()
    coordinator = FakeCoordinator()
    hass.data["openclaw"] = {entry.entry_id: {"client": client, "coordinator": coordinator}}
    agent = module.OpenClawConversationAgent(hass, entry)
    agent.entity_id = "conversation.openclaw"
    return agent, hass, coordinator


class ConversationStreamingTests(unittest.TestCase):
    def test_streams_openclaw_deltas_into_native_chat_log(self) -> None:
        module = _load_module()
        agent, hass, coordinator = _agent(module, FakeClient(["Hello ", "world"]))

        result = asyncio.run(agent.async_process(FakeInput("Hi")))

        self.assertEqual(result.response.speech, "Hello world")
        self.assertEqual(hass.last_chat_log.deltas, [{"role": "assistant"}, {"content": "Hello "}, {"content": "world"}])
        self.assertEqual(hass.bus.events[0][1]["session_id"], "agent:main:conv-1")
        self.assertTrue(coordinator.updated)

    def test_uses_non_streaming_response_when_stream_is_empty(self) -> None:
        module = _load_module()
        agent, hass, _ = _agent(module, FakeClient([], "Fallback reply"))

        result = asyncio.run(agent.async_process(FakeInput("Hi")))

        self.assertEqual(result.response.speech, "Fallback reply")
        self.assertEqual(len(agent.hass.data["openclaw"]["entry-1"]["client"].send_calls), 1)
        self.assertEqual(hass.last_chat_log.contents[-1].content, "Fallback reply")

    def test_legacy_core_path_keeps_a_non_streaming_result(self) -> None:
        module = _load_module()
        delattr(module.conversation, "async_get_result_from_chat_log")
        agent, _, _ = _agent(module, FakeClient(["Legacy reply"]))

        result = asyncio.run(agent.async_process(FakeInput("Hi")))

        self.assertEqual(result.response.speech, "Legacy reply")


if __name__ == "__main__":
    unittest.main()
