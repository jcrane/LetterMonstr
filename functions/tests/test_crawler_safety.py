"""Smoke tests: verify SSRF protection in WebCrawler._is_safe_url()."""

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


@pytest.fixture()
def crawler(mock_content_config):
    from src.crawl.crawler import WebCrawler
    return WebCrawler(mock_content_config)


class TestIsSafeUrl:
    def test_blocks_cloud_metadata_endpoint(self, crawler):
        assert crawler._is_safe_url("http://metadata.google.internal/computeMetadata/v1/") is False

    def test_blocks_aws_style_metadata(self, crawler):
        assert crawler._is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_blocks_localhost(self, crawler):
        assert crawler._is_safe_url("http://127.0.0.1/secret") is False

    def test_blocks_private_10_range(self, crawler):
        assert crawler._is_safe_url("http://10.0.0.1/internal") is False

    def test_blocks_private_192_168_range(self, crawler):
        assert crawler._is_safe_url("http://192.168.1.1/admin") is False

    def test_allows_public_url(self, crawler):
        public_ip_info = [(2, 1, 6, "", ("93.184.216.34", 443))]
        with patch("socket.getaddrinfo", return_value=public_ip_info):
            assert crawler._is_safe_url("https://example.com") is True

    def test_allows_public_url_with_path(self, crawler):
        public_ip_info = [(2, 1, 6, "", ("142.250.80.46", 443))]
        with patch("socket.getaddrinfo", return_value=public_ip_info):
            assert crawler._is_safe_url("https://www.google.com/search?q=test") is True


class TestCrawlerInstantiation:
    def test_has_expected_attributes(self, crawler):
        assert hasattr(crawler, "_is_safe_url")
        assert hasattr(crawler, "crawl")
        assert hasattr(crawler, "resolve_redirect")

    def test_blocked_hosts_is_frozenset(self):
        from src.crawl.crawler import WebCrawler
        assert isinstance(WebCrawler.BLOCKED_HOSTS, frozenset)
        assert "metadata.google.internal" in WebCrawler.BLOCKED_HOSTS
