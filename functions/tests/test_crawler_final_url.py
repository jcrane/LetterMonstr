"""Verify the crawler stores the GET-final URL and dedup preserves article URLs."""

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


PAGE_HTML = """
<html><head><title>Real Article Title</title></head>
<body><article><p>This is the genuine article body with enough text to be
considered meaningful content for the summarizer to work with.</p></article></body>
</html>
"""


class TestFetchPageFinalUrl:
    def test_crawl_stores_get_final_url(self, crawler):
        public_ip = [(2, 1, 6, "", ("93.184.216.34", 443))]

        head_resp = MagicMock()
        head_resp.url = "https://example.com/intermediate"

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = PAGE_HTML
        get_resp.url = "https://example.com/final/real-article"

        with patch("socket.getaddrinfo", return_value=public_ip), \
             patch("requests.head", return_value=head_resp), \
             patch("requests.get", return_value=get_resp), \
             patch("time.sleep"):
            result = crawler.crawl([{"url": "https://example.com/start/article", "title": "t"}])

        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/final/real-article"

    def test_fetch_page_returns_html_and_url(self, crawler):
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.text = PAGE_HTML
        get_resp.url = "https://example.com/final"
        with patch("requests.get", return_value=get_resp):
            html, final = crawler._fetch_page("https://example.com/start")
        assert "Real Article Title" in html
        assert final == "https://example.com/final"

    def test_fetch_page_non_200_returns_none_pair(self, crawler):
        get_resp = MagicMock()
        get_resp.status_code = 404
        get_resp.url = "https://example.com/missing"
        with patch("requests.get", return_value=get_resp):
            html, final = crawler._fetch_page("https://example.com/missing")
        assert html is None and final is None


class TestDedupMergesArticles:
    def test_merge_preserves_urls_from_dropped_duplicate(self):
        from src.summarize.processor import ContentProcessor
        proc = ContentProcessor({"ad_keywords": []})

        short_with_url = {
            "source": "Tech Daily",
            "content": "Short body about the AI breakthrough.",
            "articles": [{"title": "AI", "url": "https://ex.com/ai-breakthrough", "content": "c"}],
        }
        long_without_url = {
            "source": "Tech Daily",
            "content": "A much longer body about the same AI breakthrough " * 20,
            "articles": [],
        }

        out = proc._deduplicate_items([short_with_url, long_without_url])
        assert len(out) == 1
        urls = [a["url"] for a in out[0].get("articles", [])]
        assert "https://ex.com/ai-breakthrough" in urls
        # The longer body should have won as the kept content.
        assert out[0]["content"].startswith("A much longer body")
