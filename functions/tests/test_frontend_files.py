"""Smoke tests: verify frontend files exist and contain expected structure."""

from pathlib import Path

import pytest


class TestIndexHtml:
    def test_file_exists(self, project_root):
        assert (project_root / "public" / "index.html").is_file()

    def test_contains_app_div(self, project_root):
        content = (project_root / "public" / "index.html").read_text()
        assert 'id="app"' in content

    def test_contains_main_content(self, project_root):
        content = (project_root / "public" / "index.html").read_text()
        assert 'id="main-content"' in content

    def test_loads_env_config(self, project_root):
        content = (project_root / "public" / "index.html").read_text()
        assert "env-config.js" in content

    def test_loads_app_js(self, project_root):
        content = (project_root / "public" / "index.html").read_text()
        assert "app.js" in content


class TestAppJs:
    def test_file_exists(self, project_root):
        assert (project_root / "public" / "app.js").is_file()

    def test_contains_config_reference(self, project_root):
        content = (project_root / "public" / "app.js").read_text()
        assert "LETTERMONSTR_CONFIG" in content

    def test_contains_auth_listener(self, project_root):
        content = (project_root / "public" / "app.js").read_text()
        assert "onAuthStateChanged" in content

    def test_contains_trigger_summary_url(self, project_root):
        content = (project_root / "public" / "app.js").read_text()
        assert "TRIGGER_SUMMARY_URL" in content


class TestStyleCss:
    def test_file_exists(self, project_root):
        assert (project_root / "public" / "style.css").is_file()

    def test_contains_loading_hidden_rule(self, project_root):
        content = (project_root / "public" / "style.css").read_text()
        assert "#loading[hidden]" in content


class TestEnvConfigTemplate:
    def test_file_exists(self, project_root):
        assert (project_root / "public" / "env-config.template.js").is_file()

    def test_contains_api_key_placeholder(self, project_root):
        content = (project_root / "public" / "env-config.template.js").read_text()
        assert "YOUR_API_KEY" in content
