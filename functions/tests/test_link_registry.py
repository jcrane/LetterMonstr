"""Tests for deterministic source-link handling in SummaryGenerator and the
crawler's GET-final-URL capture and dedup metadata merge."""

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
def generator():
    from src.summarize.generator import SummaryGenerator
    # No api_key → client stays None; we never call the API in these tests.
    return SummaryGenerator({
        "anthropic_api_key": "",
        "model": "claude-test",
        "max_tokens": 1000,
        "temperature": 0.0,
    })


def _item(source, body, articles=None):
    return {"source": source, "content": body, "date": "2026-05-24", "articles": articles or []}


class TestSourceRegistry:
    def test_assigns_sequential_markers(self, generator):
        items = [
            _item("Newsletter A", "x" * 200, [
                {"title": "Story One", "url": "https://example.com/a/story-one", "content": "y" * 200},
                {"title": "Story Two", "url": "https://example.com/a/story-two", "content": "z" * 200},
            ]),
        ]
        text, registry = generator._prepare_content_for_summary(items)
        assert set(registry.keys()) == {1, 2}
        assert registry[1]["url"] == "https://example.com/a/story-one"
        assert registry[2]["url"] == "https://example.com/a/story-two"
        assert "[[S1]]" in text and "[[S2]]" in text

    def test_dedupes_repeated_url_to_one_marker(self, generator):
        items = [
            _item("Newsletter A", "x" * 200, [
                {"title": "Story", "url": "https://example.com/a/story", "content": "y" * 200},
                {"title": "Story dup", "url": "https://example.com/a/story/", "content": "q" * 200},
            ]),
        ]
        _, registry = generator._prepare_content_for_summary(items)
        assert set(registry.keys()) == {1}

    def test_excludes_tracking_and_root_urls(self, generator):
        items = [
            _item("Newsletter A", "x" * 200, [
                {"title": "Tracking", "url": "https://links.substack.com/redirect/abc", "content": "y" * 200},
                {"title": "Homepage", "url": "https://example.com/", "content": "z" * 200},
                {"title": "Good", "url": "https://example.com/real/article", "content": "w" * 200},
            ]),
        ]
        _, registry = generator._prepare_content_for_summary(items)
        assert [e["url"] for e in registry.values()] == ["https://example.com/real/article"]

    def test_raw_body_url_is_not_promoted_as_source(self, generator):
        # A raw tracking URL in the body is shown to the model as context, but
        # must never be promoted into the source registry or the old
        # "PRIMARY SOURCE URL" annotation that invited the model to link it.
        body = "Big news today. See https://links.substack.com/redirect/xyz for details. " + "x" * 200
        items = [_item("Newsletter A", body, [
            {"title": "Real", "url": "https://example.com/real/article", "content": "y" * 200},
        ])]
        text, registry = generator._prepare_content_for_summary(items)
        assert "**PRIMARY SOURCE URL" not in text
        assert "[[S1]]" in text
        # Only the crawl-validated article URL is eligible for a link.
        assert [e["url"] for e in registry.values()] == ["https://example.com/real/article"]


class TestExpandMarkers:
    def test_expands_known_marker(self, generator):
        registry = {1: {"url": "https://example.com/article", "title": "Cool Story", "source": "Newsletter A"}}
        out = generator._expand_markers("Summary text. [[S1]]", registry)
        assert '<a href="https://example.com/article" class="read-more">' in out
        assert "Cool Story" in out
        assert "[[S1]]" not in out

    def test_accepts_marker_format_variants(self, generator):
        registry = {
            1: {"url": "https://example.com/1", "title": "", "source": "A"},
            2: {"url": "https://example.com/2", "title": "", "source": "B"},
            3: {"url": "https://example.com/3", "title": "", "source": "C"},
        }
        out = generator._expand_markers("a [[S1]] b [S2] c (s3)", registry)
        assert out.count("<a href=") == 3
        assert 'href="https://example.com/1"' in out
        assert 'href="https://example.com/2"' in out
        assert 'href="https://example.com/3"' in out

    def test_unknown_marker_is_dropped(self, generator):
        registry = {1: {"url": "https://example.com/1", "title": "", "source": "A"}}
        out = generator._expand_markers("known [[S1]] unknown [[S9]]", registry)
        assert out.count("<a href=") == 1
        assert "S9" not in out
        assert "[[" not in out

    def test_adjacent_markers_separated_by_line_break(self, generator):
        registry = {
            1: {"url": "https://example.com/1", "title": "", "source": "A"},
            2: {"url": "https://example.com/2", "title": "", "source": "B"},
        }
        out = generator._expand_markers("Section. [[S1]][[S2]]", registry)
        assert out.count("<a href=") == 2
        assert "</a><br><a " in out

    def test_single_marker_has_no_line_break(self, generator):
        registry = {1: {"url": "https://example.com/1", "title": "", "source": "A"}}
        out = generator._expand_markers("Section. [[S1]]", registry)
        assert "<br>" not in out

    def test_escapes_untrusted_title(self, generator):
        registry = {1: {"url": "https://example.com/x",
                        "title": 'Tom & Jerry <script>', "source": "A"}}
        out = generator._expand_markers("[[S1]]", registry)
        assert "<script>" not in out
        assert "&amp;" in out and "&lt;script&gt;" in out


class TestStripUnvalidatedAnchors:
    def test_strips_hallucinated_anchor_keeps_valid(self, generator):
        html = (
            '<p>Good. <a href="https://example.com/real">Read more</a></p>'
            '<p>Bad. <a href="https://fake.com/hallucinated">Read more</a></p>'
        )
        valid = ["https://example.com/real"]
        out = generator._strip_unvalidated_anchors(html, valid)
        assert 'href="https://example.com/real"' in out
        assert "fake.com" not in out
        assert "Read more" in out  # text preserved as plain text

    def test_matches_ignoring_query_and_trailing_slash(self, generator):
        html = '<a href="https://example.com/real/?utm=1">Read more</a>'
        out = generator._strip_unvalidated_anchors(html, ["https://example.com/real"])
        assert 'href="https://example.com/real/?utm=1"' in out

    def test_empty_valid_set_strips_all(self, generator):
        html = '<a href="https://example.com/x">Read more</a>'
        out = generator._strip_unvalidated_anchors(html, [])
        assert "<a " not in out
        assert "Read more" in out
