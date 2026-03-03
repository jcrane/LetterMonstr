"""Smoke tests: verify all project modules import without error."""

import importlib
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
    """Patch Firebase/GCP SDKs so imports don't require credentials."""
    for mod_name, mock in FIREBASE_MOCKS.items():
        monkeypatch.setitem(__import__("sys").modules, mod_name, mock)


@pytest.mark.parametrize("module_path", [
    "src.config",
    "src.firestore_db",
    "src.mail_handling.parser",
    "src.mail_handling.fetcher",
    "src.mail_handling.sender",
    "src.crawl.crawler",
    "src.summarize.processor",
    "src.summarize.generator",
    "src.summarize.claude_summarizer",
])
def test_module_imports(module_path):
    mod = importlib.import_module(module_path)
    assert mod is not None


def test_main_imports():
    import main  # noqa: F811
    assert hasattr(main, "fetch_and_process")
    assert hasattr(main, "generate_and_send_summary")
    assert hasattr(main, "update_secrets")
    assert hasattr(main, "trigger_summary")
