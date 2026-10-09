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


class StripMarkdownForSpeechTests(unittest.TestCase):
    """Protect the speech text that Assist hands to text-to-speech."""

    def test_removes_bold_markup_around_cjk_text(self) -> None:
        self.assertEqual(
            helpers.strip_markdown_for_speech("**卧室三**：23.3℃ / 湿度 61%"),
            "卧室三：23.3℃ / 湿度 61%",
        )

    def test_removes_a_full_reported_response(self) -> None:
        response = (
            "🔹**有完整数据的区域**-**车库**：26.7℃ / 湿度 71%"
            " 两点提醒：1. 阳台湿度报 100%，建议检查探头。"
        )
        cleaned = helpers.strip_markdown_for_speech(response)

        self.assertNotIn("**", cleaned)
        self.assertIn("车库", cleaned)
        self.assertIn("🔹", cleaned)
        self.assertIn("26.7℃", cleaned)

    def test_removes_headings_bullets_and_quotes_at_line_start(self) -> None:
        cleaned = helpers.strip_markdown_for_speech(
            "# 报告\n- 温度 23℃\n* 湿度 61%\n1. 正常\n> 备注"
        )
        self.assertEqual(cleaned, "报告\n温度 23℃\n湿度 61%\n正常\n备注")

    def test_keeps_link_text_and_inline_code_content(self) -> None:
        self.assertEqual(
            helpers.strip_markdown_for_speech("详见 [说明书](https://example.com) 的 `open` 参数"),
            "详见 说明书 的 open 参数",
        )

    def test_leaves_arithmetic_untouched(self) -> None:
        self.assertEqual(helpers.strip_markdown_for_speech("3*4=12"), "3*4=12")

    def test_leaves_plain_text_untouched(self) -> None:
        plain = "车库 26.7 度，湿度 71%。"
        self.assertEqual(helpers.strip_markdown_for_speech(plain), plain)

    def test_handles_empty_input(self) -> None:
        self.assertEqual(helpers.strip_markdown_for_speech(""), "")

    def test_removes_unbalanced_emphasis_runs(self) -> None:
        self.assertEqual(helpers.strip_markdown_for_speech("**未闭合的加粗"), "未闭合的加粗")


if __name__ == "__main__":
    unittest.main()
