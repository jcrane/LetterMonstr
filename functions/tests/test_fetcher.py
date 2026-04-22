"""Regression tests for IMAP response parsing in EmailFetcher.

Origin: production crash `AttributeError: 'int' object has no attribute
'decode'` at fetcher.py:160 when imaplib.fetch() returns a bytes-only
entry instead of a (envelope, body) tuple.
"""

from src.mail_handling.fetcher import _extract_rfc822_bytes


class TestExtractRfc822Bytes:
    def test_normal_tuple_shape(self):
        """Standard imaplib response: [(envelope, body), closing_paren]."""
        body = b"From: a@b.com\r\nSubject: hi\r\n\r\nHello"
        msg_data = [(b"1 (RFC822 {36}", body), b")"]
        assert _extract_rfc822_bytes(msg_data) == body

    def test_bytes_only_response_returns_none(self):
        """Edge case that caused the production crash."""
        msg_data = [b"1 (UID 123 RFC822 {0} )"]
        assert _extract_rfc822_bytes(msg_data) is None

    def test_mixed_response_picks_tuple(self):
        """Some responses have flag updates interleaved with the body."""
        body = b"real message body"
        msg_data = [b"1 FETCH (FLAGS (\\Seen))", (b"1 (RFC822 {17}", body)]
        assert _extract_rfc822_bytes(msg_data) == body

    def test_empty_response_returns_none(self):
        assert _extract_rfc822_bytes([]) is None
        assert _extract_rfc822_bytes(None) is None

    def test_tuple_with_non_bytes_body_returns_none(self):
        msg_data = [(b"1 (RFC822 {0}", None)]
        assert _extract_rfc822_bytes(msg_data) is None

    def test_bytearray_body_is_accepted(self):
        body = bytearray(b"bytearray body")
        msg_data = [(b"1 (RFC822 {14}", body)]
        result = _extract_rfc822_bytes(msg_data)
        assert result == bytes(body)
        assert isinstance(result, bytes)
