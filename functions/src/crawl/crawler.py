"""
Web crawler for LetterMonstr Firebase Cloud Functions.

Fetches and extracts content from newsletter links.
No direct database access — the caller handles persistence via Firestore.
"""

import ipaddress
import logging
import socket
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class WebCrawler:
    """Fetches and extracts content from links."""

    def __init__(self, config):
        """Initialize with content configuration dict.

        Expected keys: max_links_per_email, max_link_depth, user_agent,
        request_timeout, ad_keywords.
        """
        self.max_links = config['max_links_per_email']
        self.max_depth = config['max_link_depth']
        self.user_agent = config['user_agent']
        self.timeout = config['request_timeout']
        self.ad_keywords = config['ad_keywords']
        self.headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def crawl(self, links, depth=0):
        """Crawl the provided links and extract content.

        Args:
            links: A single URL string, a dict with 'url', or a list of link dicts.
            depth: Current crawl depth (for recursive crawling).

        Returns:
            list[dict]: Each dict has keys: url, title, content, is_ad.
        """
        if not links:
            return []

        if depth >= self.max_depth:
            logger.info(f"Reached maximum crawl depth ({self.max_depth}), stopping")
            return []

        if isinstance(links, str):
            links = [{'url': links, 'title': links}]
        elif isinstance(links, dict) and 'url' in links:
            links = [links]

        links = self.get_content_urls(links)

        if len(links) > self.max_links:
            logger.info(f"Limiting crawl to {self.max_links} of {len(links)} links")
            links = links[:self.max_links]

        crawled_content = []

        try:
            for link_data in links:
                if not isinstance(link_data, dict) or 'url' not in link_data:
                    logger.warning(f"Invalid link data, skipping: {link_data}")
                    continue

                url = link_data['url']

                if not url.lower().startswith(('http://', 'https://')):
                    logger.warning(f"Skipping non-HTTP URL: {url}")
                    continue

                if not self._is_safe_url(url):
                    continue

                logger.info(f"Crawling URL: {url}")
                page_content = self._fetch_page(url)

                if not page_content:
                    logger.warning(f"No content fetched from URL: {url}")
                    continue

                extracted_content = self._extract_content(url, page_content)

                if not extracted_content or not extracted_content.get('clean_text'):
                    logger.warning(f"No meaningful content extracted from URL: {url}")
                    continue

                is_ad = self._is_advertisement(extracted_content)
                if is_ad:
                    logger.info(f"Content from {url} appears to be an advertisement, skipping")
                    continue

                crawled_content.append({
                    'url': url,
                    'title': extracted_content['title'],
                    'content': extracted_content['clean_text'],
                    'is_ad': is_ad,
                })

                time.sleep(1)

            return crawled_content

        except Exception as e:
            logger.error(f"Error in crawl process: {e}", exc_info=True)
            return crawled_content

    # ------------------------------------------------------------------
    # URL safety
    # ------------------------------------------------------------------

    BLOCKED_HOSTS = frozenset({
        "metadata.google.internal",
        "metadata.goog",
    })

    BLOCKED_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]

    def _is_safe_url(self, url: str) -> bool:
        """Reject URLs that resolve to private IPs or cloud metadata endpoints."""
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False

            if hostname.lower() in self.BLOCKED_HOSTS:
                logger.warning("Blocked metadata host: %s", hostname)
                return False

            addrs = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            for family, _, _, _, sockaddr in addrs:
                ip = ipaddress.ip_address(sockaddr[0])
                if any(ip in net for net in self.BLOCKED_NETWORKS):
                    logger.warning("Blocked private/reserved IP %s for host %s", ip, hostname)
                    return False

            return True
        except (socket.gaierror, ValueError) as exc:
            logger.warning("DNS resolution failed for %s: %s", url, exc)
            return False

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _fetch_page(self, url):
        """Fetch a web page and return its HTML content."""
        try:
            logger.info(f"Fetching URL: {url}")
            response = requests.get(url, headers=self.headers, timeout=self.timeout)

            if response.status_code == 200:
                return response.text

            logger.warning(f"Failed to fetch URL: {url} (Status code: {response.status_code})")
            return None

        except Exception as e:
            logger.error(f"Error fetching page {url}: {e}", exc_info=True)
            return None

    def resolve_redirect(self, url):
        """Follow redirects to get the actual destination URL."""
        try:
            if not url.lower().startswith(('http://', 'https://')):
                return url

            parsed_url = urlparse(url)
            if not parsed_url.path or parsed_url.path == '/' or parsed_url.path.lower() in ['/index.html', '/index.php', '/home']:
                logger.info(f"Skipping root domain URL without specific content path: {url}")
                return None

            problematic_domains = [
                'beehiiv.com', 'media.beehiiv.com', 'link.mail.beehiiv.com',
                'mailchimp.com', 'substack.com', 'bytebytego.com',
                'sciencealert.com', 'leapfin.com', 'cutt.ly',
                'genai.works', 'link.genai.works',
            ]

            if any(domain in parsed_url.netloc.lower() for domain in problematic_domains) and (
                not parsed_url.path or parsed_url.path == '/' or len(parsed_url.path) < 5
            ):
                logger.info(f"Skipping known newsletter/tracking domain without specific content: {url}")
                return None

            if not self._is_safe_url(url):
                return None

            logger.info(f"Resolving URL: {url}")
            head_response = requests.head(url, headers=self.headers, allow_redirects=True, timeout=self.timeout)
            final_url = head_response.url

            if final_url != url:
                logger.info(f"URL {url} redirected to {final_url}")

                if not self._is_safe_url(final_url):
                    return None

                final_parsed = urlparse(final_url)
                if not final_parsed.path or final_parsed.path == '/' or final_parsed.path.lower() in ['/index.html', '/index.php', '/home']:
                    logger.info(f"Redirect ended at root domain without specific content: {final_url}")
                    return None

            return final_url

        except Exception as e:
            logger.error(f"Error resolving URL {url}: {e}", exc_info=True)
            return url

    def get_content_urls(self, links):
        """Resolve redirects for a list of links and return actual content URLs.

        Args:
            links: List of link dicts or URL strings.

        Returns:
            list[dict]: Dicts with resolved 'url', 'title', and optional 'original_url'.
        """
        result = []

        for link in links:
            try:
                if isinstance(link, dict) and 'url' in link:
                    url = link['url']
                    title = link.get('title', '')
                elif isinstance(link, str):
                    url = link
                    title = ''
                else:
                    logger.warning(f"Invalid link format: {link}")
                    continue

                if not url.lower().startswith(('http://', 'https://')):
                    continue

                resolved_url = self.resolve_redirect(url)

                if not resolved_url:
                    continue

                result.append({
                    'url': resolved_url,
                    'title': title,
                    'original_url': url if resolved_url != url else None,
                })

            except Exception as e:
                logger.error(f"Error processing link {link}: {e}", exc_info=True)

        return result

    # ------------------------------------------------------------------
    # Content extraction
    # ------------------------------------------------------------------

    def _extract_content(self, url, html_content):
        """Extract structured content from raw HTML."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            title = self._extract_title(soup)

            meta_desc = ''
            meta_tag = soup.find('meta', attrs={'name': 'description'})
            if meta_tag and 'content' in meta_tag.attrs:
                meta_desc = meta_tag['content']

            for tag in soup(['script', 'style', 'header', 'footer', 'nav', 'aside']):
                tag.decompose()

            article = soup.find('article')
            if article:
                main_content = article
            else:
                main_content = soup.find('main') or soup.find(id=['content', 'main', 'article']) or soup.body

            clean_text = self._clean_text(main_content.get_text(' ', strip=True)) if main_content else ''

            return {
                'url': url,
                'title': title,
                'description': meta_desc,
                'raw_html': str(soup),
                'clean_text': clean_text,
            }

        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}", exc_info=True)
            return {
                'url': url,
                'title': '',
                'description': '',
                'raw_html': html_content,
                'clean_text': '',
            }

    def _extract_title(self, soup):
        """Extract the best available title from a BeautifulSoup object."""
        if not soup:
            return ""

        title_tag = soup.find('title')
        if title_tag and title_tag.text:
            return title_tag.text.strip()

        h1_tag = soup.find('h1')
        if h1_tag and h1_tag.text:
            return h1_tag.text.strip()

        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return meta_title['content'].strip()

        return ""

    def _clean_text(self, text):
        """Remove extra whitespace from extracted text."""
        return ' '.join(text.split())

    # ------------------------------------------------------------------
    # Ad detection
    # ------------------------------------------------------------------

    def _is_advertisement(self, content):
        """Check if extracted content is likely an advertisement."""
        if not content:
            return False

        try:
            title = content.get('title', '') or ''
            description = content.get('description', '') or ''
            clean_text = content.get('clean_text', '') or ''

            lower_content = (title + ' ' + description + ' ' + clean_text).lower()

            for keyword in self.ad_keywords:
                if keyword.lower() in lower_content:
                    logger.info(f"Identified advertisement content: {content.get('url', '')} (matched keyword: {keyword})")
                    return True
        except Exception as e:
            logger.error(f"Error checking if content is advertisement: {e}")
            return False

        return False
