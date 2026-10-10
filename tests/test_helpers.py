"""Lightweight regression tests for dependency-free integration helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_HELPERS_PATH = Path(__file__).parents[1] / "custom_components" / "openclaw" / "helpers.py"
_SPEC = importlib.util.spec_from_file_location("openclaw_helpers", _HELPERS_PATH)
assert _SPEC and _SPEC.loader
helpers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(helpers)


class ScopeAgentSessionIdTests(unittest.TestCase):
    """Protect the OpenClaw agent session-key contract."""

    def test_prefixes_a_conversation_for_the_target_agent(self) -> None:
        self.assertEqual(
            helpers.scope_agent_session_id("assist_user_123", "home"),
            "agent:home:assist_user_123",
        )

    def test_does_not_prefix_without_an_agent(self) -> None:
        self.assertEqual(
            helpers.scope_agent_session_id("assist_default", None),
            "assist_default",
        )

    def test_is_idempotent_for_an_already_scoped_key(self) -> None:
        self.assertEqual(
            helpers.scope_agent_session_id("agent:home:assist_user_123", "home"),
            "agent:home:assist_user_123",
        )


class AssistBaseSessionIdTests(unittest.TestCase):
    """Keep the signed-in HA user in the key when HA sends a conversation id."""

    def test_user_and_conversation_are_both_kept(self) -> None:
        self.assertEqual(
            helpers.assist_base_session_id("01m4hf34nxm64w74ab60v9pbrc", "abc", "dev1"),
            "assist_user_abc:01m4hf34nxm64w74ab60v9pbrc",
        )

    def test_follow_up_turn_is_not_prefixed_twice(self) -> None:
        self.assertEqual(
            helpers.assist_base_session_id("assist_user_abc:01m4", "abc", None),
            "assist_user_abc:01m4",
        )
        self.assertEqual(
            helpers.assist_base_session_id("agent:home:assist_user_abc:01m4", "abc", None),
            "agent:home:assist_user_abc:01m4",
        )

    def test_user_without_conversation(self) -> None:
        self.assertEqual(
            helpers.assist_base_session_id(None, "abc", "dev1"),
            "assist_user_abc",
        )

    def test_conversation_id_without_a_user(self) -> None:
        self.assertEqual(
            helpers.assist_base_session_id("01m4hf34nxm64w74ab60v9pbrc", None, "dev1"),
            "01m4hf34nxm64w74ab60v9pbrc",
        )

    def test_device_without_user_or_conversation(self) -> None:
        self.assertEqual(
            helpers.assist_base_session_id(None, None, "dev1"),
            "assist_device_dev1",
        )

    def test_default_when_nothing_is_known(self) -> None:
        self.assertEqual(
            helpers.assist_base_session_id(None, None, None),
            "assist_default",
        )

    def test_scoped_follow_up_stays_stable(self) -> None:
        first = helpers.scope_agent_session_id(
            helpers.assist_base_session_id("01m4", "abc", None), "home"
        )
        again = helpers.scope_agent_session_id(
            helpers.assist_base_session_id(first, "abc", None), "home"
        )
        self.assertEqual(first, "agent:home:assist_user_abc:01m4")
        self.assertEqual(again, first)


class ResolveActiveModelTests(unittest.TestCase):
    """Protect an explicit HA model choice across coordinator refreshes."""

    def test_prefers_persisted_selection_over_gateway_inventory_default(self) -> None:
        self.assertEqual(
            helpers.resolve_active_model("gpt-5", ["claude", "gpt-5"], "claude"),
            "gpt-5",
        )

    def test_falls_back_to_gateway_default_when_selection_is_unavailable(self) -> None:
        self.assertEqual(
            helpers.resolve_active_model("retired", ["claude", "gpt-5"], "claude"),
            "claude",
        )

    def test_falls_back_to_first_available_model_without_gateway_default(self) -> None:
        self.assertEqual(
            helpers.resolve_active_model(None, ["claude", "gpt-5"], None),
            "claude",
        )


class SslRequestParameterTests(unittest.TestCase):
    """Protect self-signed HTTPS support for lan_https installations."""

    def test_disables_verification_only_for_https_when_requested(self) -> None:
        self.assertFalse(helpers.ssl_request_parameter(True, False))

    def test_keeps_default_verification_for_https(self) -> None:
        self.assertIsNone(helpers.ssl_request_parameter(True, True))

    def test_does_not_set_an_ssl_override_for_plain_http(self) -> None:
        self.assertIsNone(helpers.ssl_request_parameter(False, False))


if __name__ == "__main__":
    unittest.main()
