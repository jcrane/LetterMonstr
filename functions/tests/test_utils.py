"""Smoke tests: verify pure utility functions produce correct output."""

from unittest.mock import patch, MagicMock

import pytest

FIREBASE_MOCKS = {
    "firebase_admin": MagicMock(),
    "firebase_admin.auth": MagicMock(),
    "firebase_admin.firestore": MagicMock(),
    "firebase_functions": MagicMock(),
    "firebase_functions.https_fn": MagicMock(),
    "firebase_functions.options": MagicMock(),
    "google.cloud.secretmanager": MagicMock(),
    "google.cloud": MagicMock(),
}


@pytest.fixture(autouse=True)
def _patch_firebase(monkeypatch):
    for mod_name, mock in FIREBASE_MOCKS.items():
        monkeypatch.setitem(__import__("sys").modules, mod_name, mock)


# --- _generate_content_hash ---

class TestGenerateContentHash:
    def test_returns_hex_string(self):
        from main import _generate_content_hash
        result = _generate_content_hash("Test Subject", "Some content")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest length

    def test_deterministic(self):
        from main import _generate_content_hash
        a = _generate_content_hash("subj", "body")
        b = _generate_content_hash("subj", "body")
        assert a == b

    def test_different_inputs_produce_different_hashes(self):
        from main import _generate_content_hash
        a = _generate_content_hash("subject A", "content A")
        b = _generate_content_hash("subject B", "content B")
        assert a != b


# --- create_claude_prompt ---

class TestCreateClaudePrompt:
    def test_contains_instructions_and_content(self):
        from src.summarize.claude_summarizer import create_claude_prompt
        result = create_claude_prompt("Keep it brief", "Newsletter body here")
        assert "Keep it brief" in result
        assert "Newsletter body here" in result

    def test_returns_string(self):
        from src.summarize.claude_summarizer import create_claude_prompt
        result = create_claude_prompt("inst", "content")
        assert isinstance(result, str)


# --- _coerce_value ---

class TestCoerceValue:
    def test_bool_true_values(self):
        from src.config import _coerce_value
        for raw in ("true", "True", "1", "yes"):
            assert _coerce_value("periodic_fetch", raw) is True

    def test_bool_false_values(self):
        from src.config import _coerce_value
        for raw in ("false", "0", "no", "random"):
            assert _coerce_value("periodic_fetch", raw) is False

    def test_int_coercion(self):
        from src.config import _coerce_value
        assert _coerce_value("imap_port", "993") == 993

    def test_float_coercion(self):
        from src.config import _coerce_value
        assert _coerce_value("temperature", "0.7") == pytest.approx(0.7)

    def test_comma_split(self):
        from src.config import _coerce_value
        result = _coerce_value("folders", "INBOX, Newsletters, Updates")
        assert result == ["INBOX", "Newsletters", "Updates"]

    def test_plain_string_passthrough(self):
        from src.config import _coerce_value
        assert _coerce_value("smtp_server", "smtp.gmail.com") == "smtp.gmail.com"


# --- _filter_firestore_settings ---

class TestFilterFirestoreSettings:
    def test_strips_unknown_sections(self):
        from src.config import _filter_firestore_settings
        raw = {
            "email": {"fetch_email": "a@b.com"},
            "hacker_section": {"evil_key": "payload"},
        }
        filtered = _filter_firestore_settings(raw)
        assert "hacker_section" not in filtered
        assert filtered["email"]["fetch_email"] == "a@b.com"

    def test_strips_unknown_keys_within_section(self):
        from src.config import _filter_firestore_settings
        raw = {
            "llm": {
                "model": "claude-sonnet-4-20250514",
                "unknown_key": "bad_value",
            },
        }
        filtered = _filter_firestore_settings(raw)
        assert "unknown_key" not in filtered["llm"]
        assert filtered["llm"]["model"] == "claude-sonnet-4-20250514"

    def test_allows_all_valid_keys(self):
        from src.config import _filter_firestore_settings, _ENV_DEFAULTS
        raw = {}
        for section, fields in _ENV_DEFAULTS.items():
            raw[section] = {key: f"val_{key}" for key in fields}
        filtered = _filter_firestore_settings(raw)
        for section, fields in _ENV_DEFAULTS.items():
            assert section in filtered
            for key in fields:
                assert key in filtered[section]


# --- _ENV_DEFAULTS schema ---

class TestEnvDefaultsSchema:
    def test_expected_sections_exist(self):
        from src.config import _ENV_DEFAULTS
        for section in ("email", "summary", "llm", "content"):
            assert section in _ENV_DEFAULTS, f"Missing section: {section}"

    def test_email_has_expected_keys(self):
        from src.config import _ENV_DEFAULTS
        expected = {"fetch_email", "imap_server", "imap_port", "folders",
                    "initial_lookback_days", "periodic_fetch",
                    "mark_read_only_after_summary"}
        assert expected.issubset(set(_ENV_DEFAULTS["email"].keys()))

    def test_each_field_is_tuple_of_env_var_and_default(self):
        from src.config import _ENV_DEFAULTS
        for section, fields in _ENV_DEFAULTS.items():
            for key, value in fields.items():
                assert isinstance(value, tuple), f"{section}.{key} should be a tuple"
                assert len(value) == 2, f"{section}.{key} tuple should have 2 elements"
                assert isinstance(value[0], str), f"{section}.{key} env var name should be str"
