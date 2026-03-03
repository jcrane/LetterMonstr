"""
Email parser for LetterMonstr serverless application.

Pure parsing logic — extracts content and links from email data dicts
produced by the fetcher. No database calls.
"""

import re
import json
import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

FORWARDED_MARKERS = ['Fwd:', 'FW:', 'Forwarded:']

TRACKING_DOMAINS = [
    'mail.beehiiv.com',
    'link.mail.beehiiv.com',
    'email.mailchimpapp.com',
    'mailchi.mp',
    'click.convertkit-mail.com',
    'track.constantcontact.com',
    'links.substack.com',
    'tracking.mailerlite.com',
    'sendgrid.net',
    'email.mg.substack.com',
    'tracking.tldrnewsletter.com',
    'beehiiv.com',
    'substack.com',
    'mailchimp.com',
    'convertkit.com',
    'constantcontact.com',
    'hubspotemail.net',
    'alphasignal.ai',
]

REDIRECT_PATTERNS = [
    '/redirect/',
    '/track/',
    '/click?',
    'utm_source=',
    'utm_medium=',
    'utm_campaign=',
    'referrer=',
    '/ss/c/',
    'CL0/',
]

MIN_SUBSTANTIAL_LENGTH = 200
MIN_CONTENT_LENGTH = 50


class EmailParser:
    """Parses email content and extracts links — no database interaction."""

    def __init__(self):
        pass

    def parse(self, email_data):
        """Parse email content, detect forwarded emails, extract links.

        Args:
            email_data: Dict from the fetcher with keys like subject,
                        content, html, raw_content, etc.

        Returns:
            The enriched email_data dict (with content, content_type,
            links added), or None on failure.
        """
        try:
            if not email_data:
                logger.warning("Empty email data provided to parser")
                return None

            if 'subject' not in email_data or not email_data['subject']:
                email_data['subject'] = "No Subject"

            subject = email_data.get('subject', '')

            # If content is already a structured dict with substantial data, preserve it
            if isinstance(email_data.get('content'), dict):
                preserved = self._try_preserve_content_dict(email_data)
                if preserved:
                    return preserved

            self._ensure_content_fields(email_data)

            is_forwarded = any(m in subject for m in FORWARDED_MARKERS)
            if is_forwarded:
                email_data['is_forwarded'] = True
                logger.info("Detected forwarded email: %s", subject)

            if is_forwarded:
                forwarded_result = self._try_extract_from_raw_forwarded(email_data)
                if forwarded_result:
                    return forwarded_result

            message_body = self._extract_message_body(email_data, is_forwarded, subject)

            if is_forwarded:
                message_body = self._try_forwarded_deep_search(
                    email_data, message_body
                )

            if not message_body or len(message_body) < MIN_CONTENT_LENGTH:
                message_body = self._combine_all_sources(email_data, subject)

            links = []
            if message_body and len(message_body) > MIN_CONTENT_LENGTH:
                content_type = _detect_content_type(message_body)
                links = self.extract_links(message_body, content_type)
                logger.info("Extracted %d links from email content", len(links))

            email_data['content'] = message_body
            email_data['content_type'] = _detect_content_type(message_body)
            email_data['links'] = links
            return email_data

        except Exception:
            logger.error("Error parsing email", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Link extraction
    # ------------------------------------------------------------------

    def extract_links(self, content, content_type='html'):
        """Extract and deduplicate links from content."""
        links = []

        try:
            if content_type.lower() == 'html':
                soup = BeautifulSoup(content, 'html.parser')
                for a_tag in soup.find_all('a'):
                    url = a_tag.get('href', '')
                    if not url or not self._is_valid_url(url):
                        continue

                    title = a_tag.get_text(strip=True) or a_tag.get('title', '') or "Link"
                    is_tracking = self._is_tracking_url(url)

                    links.append({
                        'url': url,
                        'title': title,
                        'source': 'html',
                        'is_tracking': is_tracking,
                        'original_url': url,
                    })
            else:
                links = self._extract_links_with_regex(content)
                for link in links:
                    link['is_tracking'] = self._is_tracking_url(link.get('url', ''))
                    link['original_url'] = link.get('url', '')

            seen = set()
            unique = []
            for link in links:
                url = link.get('url', '').strip()
                if url not in seen:
                    seen.add(url)
                    unique.append(link)

            logger.info("Extracted %d unique links from content", len(unique))
            return unique

        except Exception:
            logger.error("Error extracting links", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # HTML / text cleaning
    # ------------------------------------------------------------------

    def _clean_html(self, html_content, is_forwarded=False, subject=''):
        """Clean and process HTML content, returning the useful body."""
        if not html_content or not isinstance(html_content, str):
            return ""

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            for tag in soup(['script', 'style', 'header']):
                tag.decompose()

            for el in soup.select(
                '.footer, .email-footer, .unsubscribe, '
                '[id*="footer"], [class*="footer"]'
            ):
                el.decompose()

            if is_forwarded:
                gmail_quote = soup.select_one('.gmail_quote')
                if gmail_quote:
                    return str(gmail_quote)

                for div in soup.find_all('div'):
                    text = div.get_text() or ''
                    if any(
                        m in text.lower()
                        for m in ["forwarded message", "begin forwarded", "original message"]
                    ):
                        if div.parent:
                            return str(div.parent)

            for el in soup.select('[class*="quote"], [class*="signature"]'):
                el.decompose()

            if is_forwarded:
                tables = soup.find_all('table')
                if tables:
                    largest = max(tables, key=lambda t: len(str(t)))
                    if len(str(largest)) > MIN_SUBSTANTIAL_LENGTH:
                        return str(largest)

            return str(soup.body) if soup.body else str(soup)

        except Exception:
            logger.exception("Error cleaning HTML")
            return html_content

    def _clean_text(self, text_content):
        """Normalize whitespace in plain-text content."""
        if not text_content:
            return ""
        text = text_content.replace('\r\n', '\n').replace('\r', '\n')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return '\n'.join(lines)

    def _extract_text_from_html(self, html_content):
        """Convert HTML to readable plain text."""
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            text = ""
            for el in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']):
                el_text = el.get_text(strip=True)
                if el_text:
                    text += el_text + "\n\n"
            if not text:
                text = soup.get_text()
            return text.strip()
        except Exception:
            logger.exception("Error extracting text from HTML")
            return re.sub(r'<[^>]*>', ' ', html_content)

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _is_valid_url(self, url):
        if not url:
            return False
        if url.startswith('www.'):
            url = 'http://' + url
        try:
            result = urlparse(url)
            return result.scheme in ('http', 'https') and bool(result.netloc)
        except Exception:
            return False

    def _is_tracking_url(self, url):
        if not url or not isinstance(url, str):
            return False
        for domain in TRACKING_DOMAINS:
            if domain in url:
                return True
        for pattern in REDIRECT_PATTERNS:
            if pattern in url:
                return True
        return False

    def _extract_links_with_regex(self, content):
        """Regex-based link extraction for plain-text content."""
        links = []
        seen = set()
        url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+'

        try:
            if not isinstance(content, str):
                content = str(content) if content is not None else ""

            for url in re.findall(url_pattern, content):
                url = url.rstrip(',.;:\'\"!?)')
                if url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
                    continue
                if url.startswith('www.'):
                    url = 'http://' + url
                if url not in seen:
                    seen.add(url)
                    links.append({'url': url, 'title': url})
            return links
        except Exception:
            logger.error("Error in regex link extraction", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Forwarded email content extraction
    # ------------------------------------------------------------------

    def _extract_forwarded_content(self, raw_message):
        """Pull readable content out of a forwarded email's raw data."""
        try:
            if hasattr(raw_message, 'as_string'):
                raw_str = raw_message.as_string()
            else:
                raw_str = raw_message

            is_html = '<html' in raw_str.lower() or '<!doctype html' in raw_str.lower()

            if is_html:
                soup = BeautifulSoup(raw_str, 'html.parser')
                body = soup.find('body')
                if body:
                    return body.get_text(separator='\n', strip=True)
                return raw_str

            lines = raw_str.split('\n')
            content_lines = []
            in_forwarded = False
            header_fields = ('From:', 'Date:', 'Subject:', 'To:')

            for line in lines:
                if any(
                    m in line
                    for m in [
                        '---------- Forwarded message ---------',
                        '-------- Original Message --------',
                    ]
                ):
                    in_forwarded = True
                    continue
                if in_forwarded and not line.startswith('>') and not any(
                    line.startswith(h) for h in header_fields
                ):
                    content_lines.append(line)

            if content_lines:
                return '\n'.join(content_lines)

            return raw_str

        except Exception:
            logger.error("Error extracting forwarded content", exc_info=True)
            if hasattr(raw_message, 'as_string'):
                try:
                    if raw_message.is_multipart():
                        for part in raw_message.walk():
                            ct = part.get_content_type()
                            if ct in ('text/plain', 'text/html'):
                                payload = part.get_payload(decode=True)
                                if payload:
                                    return payload.decode('utf-8', errors='replace')
                    else:
                        payload = raw_message.get_payload(decode=True)
                        if payload:
                            return payload.decode('utf-8', errors='replace')
                except Exception:
                    pass
            return str(raw_message)[:500]

    def _extract_content_from_full_message(self, full_message, is_forwarded=False):
        """Extract content from a complete email message string."""
        if not full_message:
            return ""

        try:
            is_html = '<html' in full_message.lower() or '<div' in full_message.lower()

            if is_html:
                soup = BeautifulSoup(full_message, 'html.parser')

                if is_forwarded:
                    gmail_quote = soup.select_one('.gmail_quote')
                    if gmail_quote:
                        return gmail_quote.get_text(separator='\n')

                    fwd_markers = [
                        "---------- Forwarded message ---------",
                        "Begin forwarded message:",
                        "Forwarded message",
                        "Original Message",
                    ]
                    for marker in fwd_markers:
                        elements = soup.find_all(string=lambda s: s and marker in s)
                        for el in elements:
                            parent = el.parent
                            if not parent:
                                continue
                            text = parent.get_text(separator='\n')
                            for sib in parent.next_siblings:
                                if getattr(sib, 'name', None) and sib.get_text():
                                    text += '\n' + sib.get_text(separator='\n')
                            if len(text) > MIN_SUBSTANTIAL_LENGTH:
                                return text

                    for el in soup.find_all(['div', 'blockquote']):
                        style = el.get('style', '')
                        if any(kw in style for kw in ('border', 'margin', 'padding')):
                            text = el.get_text(separator='\n')
                            if len(text) > MIN_SUBSTANTIAL_LENGTH:
                                return text

                return (
                    soup.body.get_text(separator='\n')
                    if soup.body
                    else soup.get_text(separator='\n')
                )

            if is_forwarded:
                fwd_markers = [
                    "---------- Forwarded message ---------",
                    "Begin forwarded message:",
                    "Forwarded message",
                    "Original Message",
                ]
                for marker in fwd_markers:
                    if marker in full_message:
                        parts = full_message.split(marker, 1)
                        if len(parts) > 1:
                            return parts[1]

                header_pattern = r"From:.*?\nDate:.*?\nSubject:.*?\nTo:"
                match = re.search(header_pattern, full_message, re.DOTALL)
                if match and match.end() < len(full_message):
                    return full_message[match.end():]

            return full_message

        except Exception:
            logger.error("Error extracting from full message", exc_info=True)
            return full_message

    def _extract_content_from_raw(self, raw_content, is_forwarded=False):
        """Extract content from a raw_content field (may be JSON, HTML, etc.)."""
        if not raw_content:
            return ""

        try:
            if isinstance(raw_content, str) and (
                raw_content.startswith('{') or raw_content.startswith('[')
            ):
                try:
                    data = json.loads(raw_content)
                    if isinstance(data, dict):
                        for key in ('content', 'main_content', 'text', 'html'):
                            val = data.get(key)
                            if isinstance(val, str) and len(val) > 100:
                                return val
                except (json.JSONDecodeError, ValueError):
                    pass

            if isinstance(raw_content, str):
                return self._extract_content_from_full_message(
                    raw_content, is_forwarded
                )

            if isinstance(raw_content, dict):
                for key in ('content', 'main_content', 'text', 'html'):
                    val = raw_content.get(key)
                    if isinstance(val, str) and len(val) > 100:
                        return val

            return str(raw_content)

        except Exception:
            logger.error("Error extracting from raw content", exc_info=True)
            return str(raw_content)

    # ------------------------------------------------------------------
    # Deep-search helpers
    # ------------------------------------------------------------------

    def _deep_search_content(self, email_data, is_forwarded=False, depth=0, max_depth=5):
        """Recursively hunt for the most substantial content in email_data."""
        if depth > max_depth or not email_data:
            return ""

        best = ""

        if is_forwarded:
            for field in (
                'raw_message', 'original_message', 'original_content',
                'forward_content', 'message',
            ):
                val = email_data.get(field)
                if isinstance(val, (str, bytes)):
                    extracted = self._extract_forwarded_content(val)
                    if extracted and len(extracted) > len(best):
                        best = extracted

        content_dict = email_data.get('content', {})
        if isinstance(content_dict, dict):
            html = content_dict.get('html', '')
            if html:
                cleaned = self._clean_html(html, is_forwarded=is_forwarded)
                if cleaned and len(cleaned) > len(best):
                    best = cleaned
            text = content_dict.get('text', '')
            if text:
                cleaned = self._clean_text(text)
                if cleaned and len(cleaned) > len(best):
                    best = cleaned
            deep = self._deep_search_content_recursive(content_dict, depth + 1, max_depth)
            if deep and len(deep) > len(best):
                best = deep
        elif isinstance(email_data.get('content'), str):
            c = email_data['content']
            if len(c) > len(best):
                best = c

        for field in ('html', 'text', 'body', 'html_content', 'text_content'):
            val = email_data.get(field)
            if not isinstance(val, str):
                continue
            processed = (
                self._clean_html(val, is_forwarded=is_forwarded)
                if 'html' in field
                else self._clean_text(val)
            )
            if processed and len(processed) > len(best):
                best = processed

        for key, value in email_data.items():
            if key in ('content', 'html', 'text', 'raw_message', 'original_message'):
                continue
            if isinstance(value, dict):
                deep = self._deep_search_content_recursive(value, depth + 1, max_depth)
                if deep and len(deep) > len(best):
                    best = deep
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, (dict, list)):
                        deep = self._deep_search_content_recursive(item, depth + 1, max_depth)
                        if deep and len(deep) > len(best):
                            best = deep

        if best and len(best) > MIN_SUBSTANTIAL_LENGTH:
            return best

        if not best or len(best) < MIN_CONTENT_LENGTH:
            subject = email_data.get('subject', 'Unknown Subject')
            return f"No substantial content found in forwarded email: {subject}"

        return best

    def _deep_search_content_recursive(self, data, depth=0, max_depth=5):
        """Recursively search nested structures for meaningful content."""
        if depth > max_depth:
            return ""

        if isinstance(data, dict):
            for key in ('content', 'body', 'message', 'text', 'html'):
                if key not in data:
                    continue
                value = data[key]
                if isinstance(value, str) and len(value) > 100:
                    return value
                result = self._deep_search_content_recursive(value, depth + 1, max_depth)
                if result:
                    return result

            for value in data.values():
                result = self._deep_search_content_recursive(value, depth + 1, max_depth)
                if result:
                    return result

        elif isinstance(data, list):
            for item in data:
                result = self._deep_search_content_recursive(item, depth + 1, max_depth)
                if result:
                    return result

        elif isinstance(data, str) and len(data) > 100:
            return data

        return ""

    # ------------------------------------------------------------------
    # Internal orchestration helpers
    # ------------------------------------------------------------------

    def _try_preserve_content_dict(self, email_data):
        """If email_data['content'] is already a rich dict, keep it."""
        content_dict = email_data['content']
        html_content = content_dict.get('html', '')
        text_content = content_dict.get('text', '')

        html_len = len(html_content) if isinstance(html_content, str) else 0
        text_len = len(text_content) if isinstance(text_content, str) else 0

        if html_len <= 1000 and text_len <= 1000:
            return None

        logger.info(
            "Preserving original content dict — HTML=%d, TEXT=%d",
            html_len, text_len,
        )

        content_type = 'html' if html_len > text_len else 'text'
        to_extract = html_content if content_type == 'html' else text_content

        content_dict['links'] = self.extract_links(to_extract, content_type)
        email_data['content_type'] = content_type

        if html_content:
            email_data['html_content'] = html_content
        if text_content:
            email_data['text_content'] = text_content

        return email_data

    def _ensure_content_fields(self, email_data):
        """Set default values for html_content, text_content, content."""
        email_data.setdefault('html_content', None)
        email_data.setdefault('text_content', None)
        if not email_data.get('content'):
            email_data['content'] = {}

    def _try_extract_from_raw_forwarded(self, email_data):
        """Try to pull content from raw_email / raw_message for forwards."""
        content = email_data.get('content', {})
        raw_email = None

        if isinstance(content, dict) and 'raw_email' in content:
            raw_email = content['raw_email']
        elif isinstance(content, dict) and 'raw_message' in content:
            raw_email = content['raw_message']
        elif 'raw_email' in email_data:
            raw_email = email_data['raw_email']
        elif 'raw_message' in email_data:
            raw_email = email_data['raw_message']

        if not raw_email or len(raw_email) <= 500:
            return None

        extracted = self._extract_forwarded_content(raw_email)
        if not extracted or len(extracted) <= MIN_SUBSTANTIAL_LENGTH:
            return None

        logger.info(
            "Extracted %d chars from raw forwarded email", len(extracted)
        )
        content_type = 'html' if '<html' in extracted.lower() else 'text'
        email_data['content'] = extracted
        email_data['content_type'] = content_type
        email_data['links'] = self.extract_links(extracted, content_type)
        return email_data

    def _extract_message_body(self, email_data, is_forwarded, subject):
        """Walk through html / text / raw fields to find a message body."""
        message_body = None

        if email_data.get('html'):
            cleaned = self._clean_html(
                email_data['html'], is_forwarded=is_forwarded, subject=subject
            )
            if cleaned:
                message_body = cleaned
                email_data['html_content'] = cleaned

        if not message_body and email_data.get('text'):
            cleaned = self._clean_text(email_data['text'])
            if cleaned:
                message_body = cleaned
                email_data['text_content'] = cleaned

        if (
            (not message_body or len(message_body) < MIN_SUBSTANTIAL_LENGTH)
            and 'original_full_message' in email_data
        ):
            extracted = self._extract_content_from_full_message(
                email_data['original_full_message'], is_forwarded
            )
            if extracted and (not message_body or len(extracted) > len(message_body)):
                message_body = extracted

        if (
            (not message_body or len(message_body) < MIN_SUBSTANTIAL_LENGTH)
            and 'raw_content' in email_data
        ):
            extracted = self._extract_content_from_raw(
                email_data['raw_content'], is_forwarded
            )
            if extracted and (not message_body or len(extracted) > len(message_body)):
                message_body = extracted

        return message_body

    def _try_forwarded_deep_search(self, email_data, message_body):
        """Additional forwarded-email content hunting."""
        content = email_data.get('content', {})

        if 'raw_message' in email_data:
            fwd = self._extract_forwarded_content(email_data['raw_message'])
            if fwd and len(fwd) > MIN_SUBSTANTIAL_LENGTH:
                message_body = fwd

        if isinstance(content, dict) and 'forwarded_html' in content:
            fwd_html = content['forwarded_html']
            if fwd_html and len(fwd_html) > MIN_SUBSTANTIAL_LENGTH:
                message_body = fwd_html

        if not message_body or len(message_body) < MIN_SUBSTANTIAL_LENGTH:
            deep = self._deep_search_content(email_data, is_forwarded=True)
            if deep and (not message_body or len(deep) > len(message_body)):
                message_body = deep

        return message_body

    def _combine_all_sources(self, email_data, subject):
        """Last-resort: combine every content source we can find."""
        all_content = []
        content = email_data.get('content', {})

        if email_data.get('html_content'):
            all_content.append(
                self._extract_text_from_html(email_data['html_content'])
            )
        if email_data.get('text_content'):
            all_content.append(email_data['text_content'])

        if isinstance(content, dict):
            for value in content.values():
                if isinstance(value, str) and len(value) > MIN_CONTENT_LENGTH:
                    if '<html' in value.lower():
                        all_content.append(self._extract_text_from_html(value))
                    else:
                        all_content.append(value)

        if all_content:
            combined = "\n\n".join(all_content)
            logger.info("Combined %d sources, total %d chars", len(all_content), len(combined))
            return combined

        return f"Email '{subject}' with no extractable content."


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _detect_content_type(text):
    """Return 'html' if text looks like HTML, else 'text'."""
    if not text:
        return 'text'
    lower = text.lower()
    if '<html' in lower or '<div' in lower:
        return 'html'
    return 'text'
