"""
Email sender for LetterMonstr serverless application.

Sends summary emails via SMTP. No database calls — the caller passes
the summary text and the constructor receives the password directly.
"""

import re
import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from bs4 import BeautifulSoup
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

PROBLEMATIC_DOMAINS = [
    'beehiiv.com', 'media.beehiiv.com', 'link.mail.beehiiv.com',
    'mailchimp.com', 'substack.com', 'bytebytego.com',
    'sciencealert.com', 'leapfin.com', 'cutt.ly',
    'genai.works', 'link.genai.works',
]


def _replace_list(match):
    """Replace list items with HTML list format."""
    content = match.group(2)
    return f'</p><ul><li>{content}</li></ul><p>'


def _save_link(match):
    """Format markdown links as HTML."""
    text, url = match.groups()
    return f'<a href="{url}">{text}</a>'


class EmailSender:
    """Sends summary emails to a recipient via SMTP."""

    def __init__(self, config, password):
        """Initialize with the summary section of config and an SMTP password.

        Args:
            config: Dict with keys: recipient_email, sender_email,
                    smtp_server, smtp_port, subject_prefix.
            password: SMTP password string (e.g. Gmail app password).
        """
        self.recipient_email = config['recipient_email']
        self.sender_email = config['sender_email']
        self.smtp_server = config['smtp_server']
        self.smtp_port = config['smtp_port']
        self.subject_prefix = config.get('subject_prefix', '[LetterMonstr] ')
        self.password = password

    def send_summary(self, summary_text):
        """Create and send a summary email.

        Args:
            summary_text: The summary content (plain text or HTML).

        Returns:
            True on success, False on failure.
        """
        if not self.recipient_email:
            logger.warning("No recipient email configured — skipping delivery")
            return False

        if not self.password:
            logger.error("No email password provided")
            return False

        try:
            msg = self._create_email_message(summary_text)
            self._send_email(msg)
            logger.info("Summary email sent to %s", self.recipient_email)
            return True
        except Exception:
            logger.error("Error sending summary email", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Message creation
    # ------------------------------------------------------------------

    def _create_email_message(self, summary_text):
        """Build a multipart email with plain-text and HTML alternatives."""
        msg = MIMEMultipart('alternative')

        msg['From'] = self.sender_email
        msg['To'] = self.recipient_email

        today = datetime.now()
        current_date = today.strftime('%Y-%m-%d')
        msg['Subject'] = f'{self.subject_prefix}Newsletter Summary {current_date}'

        is_html = bool(re.search(r'<html|<body|<h[1-6]|<p>|<div', summary_text))
        body_html = (
            self._ensure_proper_html(summary_text) if is_html
            else self._markdown_to_html(summary_text)
        )

        html = _wrap_in_template(body_html, current_date)
        html = _sanitize_links(html)

        plain_text = _html_to_plain(html, current_date)

        msg.attach(MIMEText(plain_text, 'plain'))
        msg.attach(MIMEText(html, 'html'))
        return msg

    def _send_email(self, msg):
        """Send an email message via SMTP with STARTTLS."""
        context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(self.sender_email, self.password)
            server.sendmail(
                self.sender_email, self.recipient_email, msg.as_string()
            )

    # ------------------------------------------------------------------
    # HTML helpers
    # ------------------------------------------------------------------

    def _ensure_proper_html(self, html_content):
        """Fix markdown remnants in mostly-HTML content."""
        if not html_content:
            return "<h1>LetterMonstr Newsletter Summary</h1><p>No content available</p>"

        if not re.search(r'<h1', html_content):
            html_content = f"<h1>LetterMonstr Newsletter Summary</h1>\n{html_content}"

        html_content = re.sub(r'^#\s+(.+?)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^##\s+(.+?)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^###\s+(.+?)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)

        html_content = re.sub(r'^\*\s+(.+?)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^-\s+(.+?)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)

        html_content = re.sub(
            r'(<li>.+?</li>)\s*(<li>.+?</li>)',
            r'<ul>\1\2</ul>', html_content, flags=re.DOTALL,
        )
        html_content = re.sub(
            r'(<li>.+?</li>)(?!<li>|</ul>)',
            r'<ul>\1</ul>', html_content,
        )

        paragraphs = re.split(r'\n\n+', html_content)
        processed = []
        for p in paragraphs:
            stripped = p.strip()
            if not stripped:
                continue
            if re.match(r'^\s*<(h[1-6]|p|ul|ol|li|div|table)', stripped):
                processed.append(p)
            elif not re.match(r'^\s*<([a-z][a-z0-9]*)\b[^>]*>(.*?)</\1>', stripped):
                processed.append(f"<p>{p}</p>")
            else:
                processed.append(p)

        html_content = '\n'.join(processed)

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            for tag in soup.find_all(string=re.compile(r'^#+\s+')):
                match = re.match(r'^(#+)\s+', tag.string)
                if match:
                    level = min(len(match.group(1)), 6)
                    text = re.sub(r'^#+\s+', '', tag.string)
                    new_tag = soup.new_tag(f"h{level}")
                    new_tag.string = text
                    tag.replace_with(new_tag)

            for link in soup.find_all('a'):
                if "read more" in link.text.lower() and not link.get('class'):
                    link['class'] = 'read-more'

            return str(soup)
        except Exception:
            logger.error("Error cleaning HTML with BeautifulSoup", exc_info=True)
            return html_content

    def _markdown_to_html(self, markdown_text):
        """Convert markdown-like text to clean HTML."""
        if not markdown_text:
            return "<h1>LetterMonstr Newsletter Summary</h1><p>No content available</p>"

        if markdown_text.strip().startswith(('<html', '<!DOCTYPE html')):
            return self._ensure_proper_html(markdown_text)

        md = markdown_text
        md = re.sub(r'<br\s*/?>', '\n', md)
        md = re.sub(r'</p>\s*<p>', '\n\n', md)
        md = re.sub(r'</?(?:p|div|span)>', '', md)

        md = re.sub(
            r'^#\s+(.+?)$|^==\s*(.+?)\s*==|^([A-Z][A-Z\s&]+[A-Z])(?::|\s*$)',
            lambda m: f'<h1>{m.group(1) or m.group(2) or m.group(3)}</h1>',
            md, flags=re.MULTILINE,
        )
        md = re.sub(
            r'^##\s+(.+?)$|^--\s*(.+?)\s*--',
            lambda m: f'<h2>{m.group(1) or m.group(2)}</h2>',
            md, flags=re.MULTILINE,
        )
        md = re.sub(r'^###\s+(.+?)$', r'<h3>\1</h3>', md, flags=re.MULTILINE)

        md = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', md)
        md = re.sub(r'\*(.+?)\*', r'<em>\1</em>', md)

        lines = md.split('\n')
        in_list = False
        processed = []
        for line in lines:
            list_match = re.match(r'^\s*[-*•]\s+(.+)$', line)
            if list_match:
                if not in_list:
                    processed.append('<ul>')
                    in_list = True
                processed.append(f'<li>{list_match.group(1)}</li>')
            else:
                if in_list:
                    processed.append('</ul>')
                    in_list = False
                processed.append(line)
        if in_list:
            processed.append('</ul>')

        md = '\n'.join(processed)

        md = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', md)
        md = re.sub(
            r'\[Read more\]\s*\((https?://[^)]+)\)',
            r'<a href="\1" class="read-more">Read more</a>', md,
        )
        md = re.sub(
            r'<a\s+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?Read more.*?)</a>',
            r'<a href="\1" class="read-more">\2</a>', md,
        )

        paragraphs = re.split(r'\n\n+', md)
        result = []
        for p in paragraphs:
            stripped = p.strip()
            if not stripped:
                continue
            if re.match(r'^\s*<(h[1-6]|ul|ol|li|div|p)', stripped):
                result.append(p)
            else:
                p_br = re.sub(r'\n', '<br>\n', p)
                result.append(f'<p>{p_br}</p>')

        md = '\n'.join(result)

        try:
            soup = BeautifulSoup(md, 'html.parser')

            standalone = soup.find_all('li', recursive=False)
            if standalone:
                ul = soup.new_tag('ul')
                for item in standalone:
                    item.extract()
                    ul.append(item)
                soup.append(ul)

            for p in soup.find_all('p'):
                if p.find('p'):
                    for nested in p.find_all('p'):
                        nested.replace_with(nested.decode_contents())

            if not soup.find('h1'):
                title = soup.new_tag('h1')
                title.string = "LetterMonstr Newsletter Summary"
                soup.insert(0, title)

            return str(soup)
        except Exception:
            logger.error("Error cleaning HTML with BeautifulSoup", exc_info=True)
            if not re.search(r'<h1', md):
                md = "<h1>LetterMonstr Newsletter Summary</h1>\n" + md
            return md


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.4;
            color: #333333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1, h2, h3, h4, h5, h6 {{
            color: #222222;
            margin-top: 20px;
            margin-bottom: 10px;
        }}
        h1 {{ font-size: 24px; }}
        h2 {{ font-size: 22px; color: #0056b3; }}
        h3 {{ font-size: 18px; color: #0056b3; }}
        p {{ margin-bottom: 10px; }}
        a {{ color: #0066cc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .source-link {{
            font-size: 14px;
            color: #666;
            display: block;
            margin-top: 5px;
            margin-bottom: 15px;
        }}
        .read-more {{
            display: inline-block;
            margin-top: 8px;
            margin-bottom: 16px;
            font-weight: 500;
            color: #0066cc;
            text-decoration: none;
        }}
        .read-more::after {{ content: " →"; }}
        .read-more:hover {{ text-decoration: underline; }}
        .read-more-missing {{
            color: #999;
            font-style: italic;
        }}
        hr {{
            border: 0;
            height: 1px;
            background: #ddd;
            margin: 20px 0;
        }}
        ul {{
            margin-top: 5px;
            margin-bottom: 10px;
            padding-left: 25px;
        }}
        li {{ margin-bottom: 5px; }}
        .footer {{
            margin-top: 30px;
            padding-top: 10px;
            border-top: 1px solid #ddd;
            font-size: 12px;
            color: #777;
        }}
    </style>
</head>
<body>
    {body}
    <div class="footer">
        <p>This summary was generated by LetterMonstr on {date}.</p>
        <p>To change your delivery preferences, please update your configuration.</p>
    </div>
</body>
</html>"""


def _wrap_in_template(body_html, current_date):
    return EMAIL_TEMPLATE.format(body=body_html, date=current_date)


def _sanitize_links(html):
    """Remove links to tracker/problematic domain roots."""
    try:
        soup = BeautifulSoup(html, 'html.parser')

        for link in soup.find_all('a'):
            href = link.get('href')
            if not href:
                continue

            parsed = urlparse(href)
            domain = parsed.netloc.lower()

            if (
                any(d in domain for d in PROBLEMATIC_DOMAINS)
                and (not parsed.path or parsed.path == '/' or len(parsed.path) < 5)
            ):
                link.replace_with(link.text)

            if "read more" in link.text.lower() and not link.get('class'):
                link['class'] = 'read-more'

        for tag in soup.find_all(string=re.compile(r'^#+\s+')):
            if tag.string:
                tag.replace_with(re.sub(r'^#+\s+', '', tag.string))

        return str(soup)
    except Exception:
        logger.error("Error sanitizing links", exc_info=True)
        return html


def _html_to_plain(html, current_date):
    """Generate a plain-text fallback from the HTML body."""
    text = f"LetterMonstr Newsletter Summary\n{'=' * 31}\n\n"
    try:
        soup = BeautifulSoup(html, 'html.parser')
        text += soup.get_text(separator='\n\n')
    except Exception:
        text += (
            "A formatted HTML newsletter summary is available. "
            "Please view in an HTML-compatible email client."
        )
    return text
