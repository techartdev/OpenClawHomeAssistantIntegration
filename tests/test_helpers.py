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


if __name__ == "__main__":
    unittest.main()
