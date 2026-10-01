"""Tests for the Claude request/response handling and model-ID upgrades."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _patch_firebase(monkeypatch):
    for mod_name in ("firebase_admin", "firebase_admin.firestore",
                     "google.cloud", "google.cloud.secretmanager"):
        monkeypatch.setitem(__import__("sys").modules, mod_name, MagicMock())


def _generator(response):
    """A SummaryGenerator whose client returns *response* from the stream."""
    from src.summarize.generator import SummaryGenerator
    gen = SummaryGenerator({
        "anthropic_api_key": "",
        "model": "claude-sonnet-5-5",
        "max_tokens": 1000,
        "temperature": 0.0,
    })
    stream = MagicMock()
    stream.__enter__.return_value.get_final_message.return_value = response
    gen.client = MagicMock()
    gen.client.beta.messages.stream.return_value = stream
    return gen


def _response(blocks, stop_reason="end_turn", stop_details=None):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason,
                           stop_details=stop_details)


PROMPT = {"system": "sys", "user": "hello"}


class TestCallClaudeApi:
    def test_skips_leading_thinking_block(self):
        gen = _generator(_response([
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="<h2>Summary</h2>"),
        ]))
        assert gen._call_claude_api(PROMPT) == "<h2>Summary</h2>"

    def test_joins_multiple_text_blocks(self):
        gen = _generator(_response([
            SimpleNamespace(type="text", text="a"),
            SimpleNamespace(type="text", text="b"),
        ]))
        assert gen._call_claude_api(PROMPT) == "ab"

    def test_refusal_returns_none(self):
        gen = _generator(_response(
            [], stop_reason="refusal",
            stop_details=SimpleNamespace(category="cyber")))
        assert gen._call_claude_api(PROMPT) is None

    def test_no_text_returns_none(self):
        gen = _generator(_response([SimpleNamespace(type="thinking", thinking="")]))
        assert gen._call_claude_api(PROMPT) is None

    def test_request_shape(self):
        gen = _generator(_response([SimpleNamespace(type="text", text="ok")]))
        gen._call_claude_api(PROMPT)
        kwargs = gen.client.beta.messages.stream.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-5-5"
        assert kwargs["output_config"] == {"effort": "medium"}
        assert kwargs["fallbacks"] == "default"
        assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
        # Sampling params and explicit thinking config are rejected by 5.5 models.
        assert "temperature" not in kwargs
        assert "thinking" not in kwargs


class TestUpgradeLegacyModel:
    @pytest.mark.parametrize("old, new", [
        ("claude-opus-4-6", "claude-opus-5-5"),
        ("claude-opus-4-20250514", "claude-opus-5-5"),
        ("claude-sonnet-4-6", "claude-sonnet-5-5"),
        ("claude-sonnet-4-20250514", "claude-sonnet-5-5"),
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("claude-sonnet-5-5", "claude-sonnet-5-5"),
        ("claude-haiku-4-5", "claude-haiku-4-5"),
    ])
    def test_maps_by_family(self, old, new):
        from src.config import _upgrade_legacy_model
        llm = {"model": old}
        _upgrade_legacy_model(llm)
        assert llm["model"] == new

    def test_default_model_is_supported(self):
        from src.config import _ENV_DEFAULTS, SUPPORTED_MODELS
        assert _ENV_DEFAULTS["llm"]["model"][1] in SUPPORTED_MODELS

    def test_ui_offers_exactly_supported_models(self):
        import re
        from pathlib import Path
        from src.config import SUPPORTED_MODELS
        html = (Path(__file__).resolve().parents[2] / "public" / "index.html").read_text()
        select = re.search(r'<select id="llm-model".*?</select>', html, re.S).group(0)
        assert set(re.findall(r'value="([^"]+)"', select)) == SUPPORTED_MODELS
