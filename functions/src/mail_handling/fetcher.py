"""
Email fetcher for LetterMonstr serverless application.

Connects to Gmail via IMAP and fetches new emails. Returns raw email data
as dicts — the caller (Cloud Function) handles Firestore storage and
duplicate checking.
"""

import imaplib
import logging
import socket
import time
import base64
import email as email_lib
from datetime import datetime, timedelta, timezone
from email.header import decode_header

logger = logging.getLogger(__name__)

MAX_CONNECT_RETRIES = 5
INITIAL_RETRY_DELAY_SECONDS = 5
CONNECTION_TIMEOUT_SECONDS = 30
CONNECTION_CHECK_INTERVAL = 10


def _extract_rfc822_bytes(msg_data):
    """Pull the RFC822 body bytes from an imaplib FETCH response.

    Normal response: ``[(b'N (RFC822 {size}', b'<body>'), b')']`` — a tuple of
    (envelope, body) first. Edge cases (message deleted between SEARCH and
    FETCH, Gmail flag-only responses, certain large/malformed messages)
    return ``[b'N (UID … RFC822 …)']`` — a bare bytes element with no body.
    Indexing ``[0][1]`` into the bytes form yields an int, which then
    explodes inside ``email.message_from_bytes``.
    """
    for entry in msg_data or ():
        if (
            isinstance(entry, tuple)
            and len(entry) >= 2
            and isinstance(entry[1], (bytes, bytearray))
        ):
            return bytes(entry[1])
    return None


class EmailFetcher:
    """Fetches emails from a Gmail account via IMAP."""

    def __init__(self, config):
        """Initialize with email configuration.

        Args:
            config: Dict with keys: fetch_email, password, imap_server,
                    imap_port, folders, initial_lookback_days.
        """
        self.email = config['fetch_email']
        self.password = config['password']
        self.server = config['imap_server']
        self.port = config['imap_port']
        self.folders = config['folders']
        self.lookback_days = config['initial_lookback_days']
        self._mail = None

    def connect(self):
        """Connect to the IMAP server with retry + exponential backoff."""
        retry_delay = INITIAL_RETRY_DELAY_SECONDS

        if self._mail:
            try:
                self._mail.logout()
            except Exception:
                pass
            self._mail = None

        for attempt in range(MAX_CONNECT_RETRIES):
            try:
                logger.info(
                    "Connecting to %s:%s (attempt %d/%d)",
                    self.server, self.port, attempt + 1, MAX_CONNECT_RETRIES,
                )
                self._mail = imaplib.IMAP4_SSL(
                    self.server, self.port, timeout=CONNECTION_TIMEOUT_SECONDS
                )
                self._mail.login(self.email, self.password)
                logger.info("Successfully connected to %s", self.server)
                return self._mail

            except (socket.gaierror, socket.timeout, OSError) as exc:
                logger.error("Network error connecting to server: %s", exc)
                if attempt < MAX_CONNECT_RETRIES - 1:
                    logger.info("Retrying in %.1f seconds…", retry_delay)
                    time.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    raise

            except Exception as exc:
                logger.error("Failed to connect to email server: %s", exc)
                if attempt < MAX_CONNECT_RETRIES - 1:
                    logger.info("Retrying in %.1f seconds…", retry_delay)
                    time.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    raise

    def check_connection(self, mail=None):
        """Verify IMAP connection is alive; reconnect if dead."""
        mail = mail or self._mail

        if not mail:
            logger.warning("No IMAP connection found, creating new one")
            return self.connect()

        try:
            status, _ = mail.noop()
            if status == 'OK':
                return mail
        except (imaplib.IMAP4.abort, socket.error, socket.timeout, OSError):
            pass
        except Exception:
            pass

        logger.warning("Connection dead, reconnecting…")
        self._mail = None
        return self.connect()

    def fetch_new_emails(self):
        """Fetch UNSEEN + recent emails from all configured folders.

        Returns a list of dicts, each with: message_id, subject, sender,
        date, content (text), html, raw_content. The caller is responsible
        for checking Firestore for duplicates.
        """
        mail = self.connect()
        all_emails = []

        try:
            since_date = (
                datetime.now() - timedelta(days=max(self.lookback_days, 1))
            ).strftime("%d-%b-%Y")

            for folder in self.folders:
                mail.select(folder)

                status_unseen, unseen_msgs = mail.search(None, 'UNSEEN')
                unseen_ids = (
                    unseen_msgs[0].split() if status_unseen == 'OK' else []
                )

                status_recent, recent_msgs = mail.search(
                    None, f'(SINCE {since_date})'
                )
                recent_ids = (
                    recent_msgs[0].split() if status_recent == 'OK' else []
                )

                all_ids = list(set(unseen_ids + recent_ids))

                if not all_ids:
                    logger.info("No emails to process in folder %s", folder)
                    continue

                logger.info(
                    "Found %d emails to process in folder %s",
                    len(all_ids), folder,
                )

                for e_id in all_ids:
                    try:
                        if (
                            len(all_emails) > 0
                            and len(all_emails) % CONNECTION_CHECK_INTERVAL == 0
                        ):
                            mail = self.check_connection(mail)

                        status, msg_data = mail.fetch(e_id, '(RFC822)')
                        if status != 'OK':
                            logger.warning("Failed to fetch email %s: %s", e_id, msg_data)
                            continue

                        raw_bytes = _extract_rfc822_bytes(msg_data)
                        if raw_bytes is None:
                            logger.warning(
                                "Unexpected IMAP response shape for email %s: %r — skipping",
                                e_id, msg_data,
                            )
                            continue

                        msg = email_lib.message_from_bytes(raw_bytes)
                        subject = self._decode_header(msg.get('Subject', 'No Subject'))
                        sender = self._decode_header(msg.get('From', 'Unknown'))
                        logger.info("Processing email: %s from %s", subject, sender)

                        parsed = self._parse_email(msg)
                        if parsed:
                            all_emails.append(parsed)
                        else:
                            logger.warning("Failed to parse email %s — skipping", subject)

                    except Exception:
                        logger.exception(
                            "Error processing email id %s — skipping to preserve batch",
                            e_id,
                        )
                        continue

            self._close_connection(mail)
            logger.info(
                "Successfully fetched %d new emails for processing",
                len(all_emails),
            )
            return all_emails

        except Exception:
            logger.error("Error fetching emails", exc_info=True)
            self._close_connection(mail)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close_connection(self, mail):
        """Safely close and logout from the IMAP connection."""
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass
        self._mail = None

    def _parse_email(self, msg):
        """Parse an email.message.Message into a flat dict."""
        try:
            message_id = msg.get('Message-ID', '')
            subject = self._decode_header(msg.get('Subject', 'No Subject'))
            sender = self._decode_header(msg.get('From', 'Unknown'))
            date_str = msg.get('Date', '')

            try:
                date = email_lib.utils.parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                date = datetime.now(tz=timezone.utc)

            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)

            content = self._get_email_content(msg)

            text_content = content.get('text', '')
            if text_content:
                text_content = ''.join(
                    c if ord(c) >= 32 or c in '\n\r\t' else ' '
                    for c in text_content
                )

            html_size = len(content.get('html', ''))
            text_size = len(text_content)
            logger.info(
                "Extracted HTML: %d chars, text: %d chars from: %s",
                html_size, text_size, subject,
            )

            return {
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'date': date,
                'content': text_content,
                'html': content.get('html', ''),
                'raw_content': content.get('raw_content', ''),
            }

        except Exception:
            logger.error("Error parsing email", exc_info=True)
            return None

    def _decode_header(self, header):
        """Decode an RFC-2047 encoded email header into a plain string."""
        try:
            decoded_parts = decode_header(header)
            parts = []
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    try:
                        parts.append(
                            part.decode(encoding) if encoding
                            else part.decode('utf-8', errors='ignore')
                        )
                    except (UnicodeDecodeError, LookupError):
                        parts.append(part.decode('utf-8', errors='ignore'))
                else:
                    parts.append(part)
            return ' '.join(parts)
        except Exception:
            logger.error("Error decoding header", exc_info=True)
            return header

    def _get_email_content(self, msg):
        """Extract text, html, and raw content from an email message.

        Handles multipart messages, forwarded-email detection, and nested
        MIME parts. Returns a dict with 'text', 'html', and optionally
        'raw_content', 'forwarded_html', 'forwarded_content_extracted'.
        """
        content = {
            'text': '',
            'html': '',
            'attachments': [],
            'raw_message': str(msg),
        }

        best_html_part = ""
        best_text_part = ""

        def inspect_part(part):
            nonlocal best_html_part, best_text_part

            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition:
                try:
                    filename = part.get_filename()
                    if filename:
                        payload = part.get_payload(decode=True)
                        if payload:
                            content['attachments'].append({
                                'filename': filename,
                                'content_type': content_type,
                                'data': base64.b64encode(payload).decode('utf-8'),
                            })
                except Exception as exc:
                    logger.error("Error processing attachment: %s", exc)
                return

            try:
                if part.is_multipart():
                    for subpart in part.get_payload():
                        inspect_part(subpart)
                else:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        return

                    if content_type == "text/plain":
                        decoded = payload.decode("utf-8", errors="replace")
                        if len(decoded) > len(best_text_part):
                            best_text_part = decoded

                    elif content_type == "text/html":
                        decoded = payload.decode("utf-8", errors="replace")
                        if len(decoded) > len(best_html_part):
                            best_html_part = decoded
                    else:
                        logger.debug("Found other content type: %s", content_type)

            except Exception as exc:
                logger.error("Error processing part: %s", exc)

        try:
            subject = msg.get('Subject', '')
            is_forwarded = bool(subject and subject.startswith('Fwd:'))
            if is_forwarded:
                logger.debug("Processing forwarded message: %s", subject)

            if is_forwarded:
                from email import policy  # noqa: F401
                raw_email_string = msg.as_string()
                content['raw_email'] = raw_email_string
                logger.info(
                    "Stored raw email for forwarded message, length: %d",
                    len(raw_email_string),
                )

                if msg.is_multipart():
                    parts = msg.get_payload()
                    if len(parts) > 1:
                        last_part = parts[-1]
                        if last_part.is_multipart():
                            for subpart in last_part.get_payload():
                                if subpart.get_content_type() == 'text/html':
                                    orig_html = subpart.get_payload(decode=True)
                                    if orig_html:
                                        html_str = orig_html.decode(
                                            'utf-8', errors='replace'
                                        )
                                        content['forwarded_html'] = html_str
                                        logger.info(
                                            "Extracted forwarded HTML, length: %d",
                                            len(html_str),
                                        )

            inspect_part(msg)

            if best_html_part:
                content['html'] = best_html_part
            if best_text_part:
                content['text'] = best_text_part

            html_len = len(content['html'])
            text_len = len(content['text'])
            logger.debug(
                "Content sizes — HTML: %d, text: %d", html_len, text_len
            )

            if is_forwarded and html_len > 0:
                self._extract_forwarded_from_html(content)

            if (html_len < 100 and text_len < 100) and msg.is_multipart():
                import re
                raw = str(msg)
                content['raw_content'] = raw
                html_match = re.search(
                    r'<html[^>]*>.*?</html>', raw,
                    re.DOTALL | re.IGNORECASE,
                )
                if html_match and len(html_match.group(0)) > html_len:
                    content['html'] = html_match.group(0)

        except Exception:
            logger.error("Error extracting email content", exc_info=True)

        return content

    def _extract_forwarded_from_html(self, content):
        """Try to isolate the forwarded message body from surrounding HTML."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(content['html'], 'html.parser')
            found = False

            # Gmail marker
            marker = soup.find(
                string=lambda s: s and "---------- Forwarded message ---------" in s
            )
            if marker and marker.parent:
                divs_after = marker.parent.find_next_siblings('div')
                if divs_after:
                    largest = max(divs_after, key=lambda x: len(str(x)))
                    if len(str(largest)) > 200:
                        content['html'] = str(largest)
                        found = True

            # Apple Mail marker
            if not found:
                marker = soup.find(
                    string=lambda s: s and "Begin forwarded message:" in s
                )
                if marker and marker.parent:
                    siblings = list(marker.parent.next_siblings)
                    combined = ''.join(str(s) for s in siblings)
                    if len(combined) > 200:
                        content['html'] = combined
                        found = True

            # Blockquote fallback
            if not found:
                quotes = soup.select('blockquote')
                if quotes:
                    largest = max(quotes, key=lambda x: len(str(x)))
                    if len(str(largest)) > 200:
                        content['html'] = str(largest)
                        found = True

            if found:
                content['forwarded_content_extracted'] = True

        except Exception as exc:
            logger.error("Error processing forwarded HTML: %s", exc)
