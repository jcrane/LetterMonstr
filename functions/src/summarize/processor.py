"""
Content processor for LetterMonstr Firebase Cloud Functions.

Processes and deduplicates content from multiple newsletter sources.
No direct database access — the caller provides historical data and
handles persistence via Firestore.
"""

import logging
import difflib
import hashlib
import re
import json
import copy

logger = logging.getLogger(__name__)

_BOILERPLATE_PATTERNS = [
    r'^(hi|hey|hello|dear|good morning|good afternoon)[\s,]',
    r'^(welcome to|thanks for reading|thank you for)',
    r'^(view (this|in) (your )?browser)',
    r'^(forward(ed)? (this )?email)',
    r'^(unsubscribe|manage (your )?preferences)',
    r'^(sent via|powered by)',
]
_BOILERPLATE_RE = re.compile('|'.join(_BOILERPLATE_PATTERNS), re.IGNORECASE)


class ContentProcessor:
    """Processes and deduplicates content from different sources."""

    def __init__(self, config):
        """Initialize processor with content configuration dict.

        Expected keys: ad_keywords (list[str]).  Other keys are accepted
        but not required.
        """
        self.config = config
        self.similarity_threshold = 0.85
        self.min_content_length = 100
        self.ad_keywords = config.get('ad_keywords', [])
        self.title_similarity_threshold = 0.90
        self.cross_summary_lookback_days = 5

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_and_deduplicate(self, items):
        """Process and deduplicate a list of content items.

        Args:
            items: List of content dicts (keys: source, content, …).

        Returns:
            list[dict]: Deduplicated items ready for summarisation.
        """
        if not items:
            logger.warning("No items to process")
            return []

        try:
            logger.info(f"Processing {len(items)} items for summarization")

            processed_items = []
            for item in items:
                processed_item = self._process_item(item)
                if processed_item:
                    processed_items.append(processed_item)

            for i, item in enumerate(processed_items):
                content = item.get('content', '')
                content_length = len(content) if isinstance(content, str) else 0
                logger.info(f"Item {i+1}: Content length = {content_length} chars")

            if not processed_items:
                logger.warning("No content to process after processing step")
                return []

            logger.info(f"Starting deduplication of {len(processed_items)} items")
            deduplicated_items = self._deduplicate_items(processed_items)

            logger.info(
                f"Deduplication: {len(processed_items)} original items → "
                f"{len(deduplicated_items)} deduplicated items"
            )
            merged_count = len(processed_items) - len(deduplicated_items)
            logger.info(f"Preserved {len(deduplicated_items)} unique items, merged {merged_count} similar items")

            source_count = len(set(item.get('source', '') for item in deduplicated_items))
            logger.info(f"After deduplication: {len(deduplicated_items)} unique items from {source_count} sources")

            return deduplicated_items

        except Exception as e:
            logger.error(f"Error in process_and_deduplicate: {e}", exc_info=True)
            return []

    def filter_with_history(self, items, historical_content):
        """Deduplicate items against previously-summarised content.

        Convenience wrapper that calls _filter_previously_summarized with
        externally-provided historical data.

        Args:
            items: Deduplicated content items from process_and_deduplicate().
            historical_content: List of dicts, each with keys:
                content_hash, content_title, content_fingerprint.

        Returns:
            list[dict]: Items not already covered in recent summaries.
        """
        return self._filter_previously_summarized(items, historical_content)

    # ------------------------------------------------------------------
    # Cross-summary deduplication
    # ------------------------------------------------------------------

    def _filter_previously_summarized(self, items, historical_content=None):
        """Filter out content already included in previous summaries.

        Uses a conservative approach: content is only skipped on exact hash
        match or content-body similarity at 85 %.  Title similarity alone
        is not sufficient because the same sender name would incorrectly
        match unrelated stories.

        Args:
            items: Content items to filter.
            historical_content: Optional list of dicts with keys
                content_hash, content_title, content_fingerprint.
                If None or empty, no filtering is performed.
        """
        if not items:
            return []

        if not historical_content:
            logger.info("No historical content provided, skipping cross-summary filtering")
            return items

        try:
            logger.info(f"Found {len(historical_content)} historical content items for cross-summary dedup")

            historical_fingerprints = [
                h['content_fingerprint'] for h in historical_content
                if h.get('content_fingerprint')
            ]
            historical_titles = [
                h['content_title'] for h in historical_content
                if h.get('content_title')
            ]
            historical_hashes = set(
                h['content_hash'] for h in historical_content
                if h.get('content_hash')
            )

            filtered_items = []
            skipped_items = 0

            for item in items:
                title = self._extract_content_title(item)
                source = item.get('source', '')

                content = item.get('content', '')
                fingerprint = self._extract_meaningful_fingerprint(content)
                if not fingerprint:
                    fingerprint = content[:1000] if content else ''

                content_hash = hashlib.md5(
                    (title + fingerprint[:100]).encode('utf-8')
                ).hexdigest()

                if content_hash in historical_hashes:
                    logger.info(f"Skipping previously summarized content (exact hash match): {title[:80]} [{source}]")
                    skipped_items += 1
                    continue

                content_match = False
                for hist_fingerprint in historical_fingerprints:
                    if self._is_similar(fingerprint, hist_fingerprint):
                        content_match = True
                        break

                if content_match:
                    logger.info(f"Skipping previously summarized content (content match): {title[:80]} [{source}]")
                    skipped_items += 1
                    continue

                title_match = False
                if len(title) > 15:
                    for hist_title in historical_titles:
                        if self._is_similar_title(title, hist_title):
                            title_match = True
                            break

                if title_match:
                    item_len = len(content) if isinstance(content, str) else 0
                    similar_length = False
                    for hist_fp in historical_fingerprints:
                        if abs(len(hist_fp) - min(item_len, 1500)) < 500:
                            similar_length = True
                            break
                    if similar_length:
                        logger.info(f"Skipping previously summarized content (title + length match): {title[:80]} [{source}]")
                        skipped_items += 1
                        continue

                filtered_items.append(item)

            logger.info(
                f"Cross-summary deduplication: {len(items)} items -> "
                f"{len(filtered_items)} items (skipped {skipped_items})"
            )
            return filtered_items

        except Exception as e:
            logger.error(f"Error filtering previously summarized content: {e}", exc_info=True)
            return items

    # ------------------------------------------------------------------
    # Item processing
    # ------------------------------------------------------------------

    def _process_item(self, item):
        """Process a single content item for summarisation."""
        try:
            title = item.get('source', 'Unknown')
            initial_content_length = 0

            if isinstance(item, dict):
                if 'content' in item and isinstance(item['content'], str):
                    initial_content_length = len(item['content'])

            logger.info(f"Processing item: {title} (initial content length: {initial_content_length})")

            if not item.get('content'):
                item['content'] = ''

            direct_html = item.get('html', '')
            direct_text = item.get('text', '')

            if direct_html and len(direct_html) > len(item['content']):
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(direct_html, 'html.parser')
                    extracted_text = soup.get_text(separator='\n', strip=True)
                    if len(extracted_text) > len(item['content']):
                        item['content'] = extracted_text
                        logger.info(f"Using HTML content for {title}: {len(extracted_text)} chars")
                except Exception as e:
                    logger.warning(f"Error extracting text from HTML: {e}")

            if direct_text and len(direct_text) > len(item['content']):
                item['content'] = direct_text
                logger.info(f"Using plain text content for {title}: {len(direct_text)} chars")

            if not item['content'] or len(item['content']) < 100:
                if 'original_email' in item and isinstance(item['original_email'], dict):
                    email_content = item['original_email'].get('content', '')
                    if isinstance(email_content, str) and len(email_content) > len(item['content']):
                        item['content'] = email_content
                        logger.info(f"Using original email content for {title}: {len(email_content)} chars")

                    email_html = item['original_email'].get('html', '')
                    if email_html and len(email_html) > len(item['content']):
                        try:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(email_html, 'html.parser')
                            extracted_text = soup.get_text(separator='\n', strip=True)
                            if len(extracted_text) > len(item['content']):
                                item['content'] = extracted_text
                                logger.info(f"Using original email HTML for {title}: {len(extracted_text)} chars")
                        except Exception as e:
                            logger.warning(f"Error extracting text from email HTML: {e}")

            if 'articles' in item and isinstance(item['articles'], list):
                combined_article_content = ""
                for article in item['articles']:
                    if isinstance(article, dict) and isinstance(article.get('content'), str):
                        combined_article_content += "\n\n" + article.get('content', '')

                if combined_article_content and len(combined_article_content) > 100:
                    if item['content']:
                        item['content'] += "\n\n--- Articles ---\n" + combined_article_content
                    else:
                        item['content'] = combined_article_content
                    logger.info(f"Added article content for {title}: {len(combined_article_content)} chars")

            if 'crawled_content' in item and isinstance(item['crawled_content'], list):
                combined_crawled = ""
                for content in item['crawled_content']:
                    if isinstance(content, dict):
                        if 'clean_content' in content and isinstance(content['clean_content'], str):
                            combined_crawled += "\n\n" + content['clean_content']
                        elif 'content' in content and isinstance(content['content'], str):
                            combined_crawled += "\n\n" + content['content']

                if combined_crawled and len(combined_crawled) > 100:
                    if item['content']:
                        item['content'] += "\n\n--- Crawled Content ---\n" + combined_crawled
                    else:
                        item['content'] = combined_crawled
                    logger.info(f"Added crawled content for {title}: {len(combined_crawled)} chars")

            if not item['content'] or len(item['content']) < 50:
                logger.warning(f"Very short content for {title}: {len(item['content'])} chars")

                raw_content = item.get('raw_content', '')
                if raw_content and len(raw_content) > len(item['content']):
                    item['content'] = raw_content
                    logger.info(f"Using raw content for {title}: {len(raw_content)} chars")

            item['content'] = self._clean_text(item['content'])

            logger.info(f"Processing item: {title} (content size: {len(item['content'])} chars)")

            return item
        except Exception as e:
            logger.error(f"Error processing item: {e}", exc_info=True)
            return item

    # ------------------------------------------------------------------
    # Within-batch deduplication
    # ------------------------------------------------------------------

    def _deduplicate_items(self, items):
        """Deduplicate items based on title and content-hash similarity."""
        if not items:
            return []

        unique_by_title = {}
        for item in items:
            title = item.get('source', '')
            if not title:
                continue

            if title in unique_by_title:
                existing_content = unique_by_title[title].get('content', '')
                new_content = item.get('content', '')

                existing_len = len(existing_content) if isinstance(existing_content, str) else 0
                new_len = len(new_content) if isinstance(new_content, str) else 0

                if new_len > existing_len:
                    unique_by_title[title] = item
            else:
                unique_by_title[title] = item

        deduplicated_items = list(unique_by_title.values())
        for item in items:
            title = item.get('source', '')
            if not title:
                deduplicated_items.append(item)

        content_hash_map = {}
        for item in deduplicated_items:
            content = item.get('content', '')
            if not content or not isinstance(content, str):
                continue

            content_sample = content[:2500]
            content_hash = hashlib.md5(content_sample.encode('utf-8')).hexdigest()

            if content_hash in content_hash_map:
                existing_content = content_hash_map[content_hash].get('content', '')
                existing_len = len(existing_content) if isinstance(existing_content, str) else 0
                new_len = len(content) if isinstance(content, str) else 0

                if new_len > existing_len:
                    content_hash_map[content_hash] = item
            else:
                content_hash_map[content_hash] = item

        return list(content_hash_map.values())

    # ------------------------------------------------------------------
    # Similarity helpers
    # ------------------------------------------------------------------

    def _is_similar(self, text1, text2):
        """Return True when two text bodies exceed the similarity threshold."""
        similarity = difflib.SequenceMatcher(None, text1, text2).ratio()
        return similarity >= self.similarity_threshold

    def _is_similar_title(self, title1, title2):
        """Return True when two titles are similar enough to be the same article."""
        if title1 == title2:
            return True

        if len(title1) < 10 or len(title2) < 10:
            return False

        def clean_title(title):
            title = re.sub(r'[\U00010000-\U0010ffff]', '', title)
            title = re.sub(r'🔊|🏆|🧠|🖼️|🤖|💰|🖊️|🛎️|📣', '', title)
            return title.strip()

        clean1 = clean_title(title1)
        clean2 = clean_title(title2)

        similarity = difflib.SequenceMatcher(None, clean1, clean2).ratio()
        return similarity >= self.title_similarity_threshold

    # ------------------------------------------------------------------
    # Hashing / fingerprinting
    # ------------------------------------------------------------------

    def _generate_content_hash(self, item):
        """Generate a hash for duplicate detection."""
        title = self._extract_content_title(item)

        content = item.get('content', '')
        fingerprint = self._extract_meaningful_fingerprint(content)
        if not fingerprint:
            fingerprint = content[:1000] if content else ''

        return hashlib.md5((title + fingerprint[:100]).encode('utf-8')).hexdigest()

    def _generate_content_fingerprint(self, content):
        """Generate a fingerprint hash for content deduplication."""
        if not content or not isinstance(content, str):
            return hashlib.md5("empty_content".encode('utf-8')).hexdigest()

        fingerprint_text = self._extract_meaningful_fingerprint(content)
        if not fingerprint_text:
            fingerprint_text = content[:1000]

        return hashlib.md5(fingerprint_text.encode('utf-8')).hexdigest()

    def _extract_meaningful_fingerprint(self, content, max_length=1500):
        """Extract a content fingerprint that skips newsletter boilerplate."""
        if not content or not isinstance(content, str):
            return ''

        lines = content.split('\n')
        meaningful_lines = []
        chars_collected = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if chars_collected == 0 and _BOILERPLATE_RE.match(stripped):
                continue
            if chars_collected == 0 and len(stripped) < 20:
                continue
            meaningful_lines.append(stripped)
            chars_collected += len(stripped)
            if chars_collected >= max_length:
                break

        return '\n'.join(meaningful_lines)[:max_length]

    def _extract_content_title(self, item):
        """Extract an actual article/story title from the content item."""
        content = item.get('content', '') if isinstance(item, dict) else ''
        if not content or not isinstance(content, str):
            return item.get('title', item.get('source', ''))

        explicit_title = item.get('title', '')
        if explicit_title and explicit_title != item.get('source', '') and len(explicit_title) > 10:
            return explicit_title.strip()

        for line in content.split('\n'):
            line = line.strip()
            if not line or len(line) < 10:
                continue
            if _BOILERPLATE_RE.match(line):
                continue
            if line.startswith('http') or line.count('http') > 1:
                continue
            return line[:255]

        return item.get('title', item.get('source', ''))

    # ------------------------------------------------------------------
    # Content cleaning
    # ------------------------------------------------------------------

    def clean_content(self, content, content_type='text'):
        """Clean content based on content type (str or dict input)."""
        try:
            if content is None:
                return ""

            if isinstance(content, dict):
                for field in ['content', 'main_content', 'raw_content', 'text', 'html']:
                    if field in content and content[field]:
                        return self.clean_content(content[field], content_type)
                logger.warning(f"Dict content without valid content field, keys: {list(content.keys())}")
                return ""

            if not isinstance(content, str):
                content = str(content)

            if not content.strip():
                return ""

            if content_type == 'html':
                from bs4 import BeautifulSoup
                try:
                    soup = BeautifulSoup(content, 'html.parser')
                    for tag in soup(['script', 'style', 'header', 'footer', 'nav']):
                        tag.decompose()
                    text = soup.get_text(separator='\n')
                    return self._clean_text(text)
                except Exception as e:
                    logger.warning(f"Error cleaning HTML content: {e}")
                    return self._clean_text(content)
            else:
                return self._clean_text(content)

        except Exception as e:
            logger.error(f"Error cleaning content: {e}", exc_info=True)
            if isinstance(content, str):
                return content[:1000]
            elif isinstance(content, dict) and 'source' in content:
                return f"Content from {content['source']}"
            return ""

    def _clean_text(self, text):
        """Normalise whitespace and strip common email footers."""
        if not text or not isinstance(text, str):
            return ""

        text = text.replace('\r\n', '\n').replace('\r', '\n')

        lines = [line.strip() for line in text.split('\n')]
        cleaned = '\n'.join(line for line in lines if line)

        for footer in [
            "Sent from my iPhone",
            "Sent from my mobile device",
            "Get Outlook for",
            "If you received this email in error",
            "To unsubscribe",
            "View this email in your browser",
        ]:
            if footer in cleaned:
                pos = cleaned.find(footer)
                if pos > len(cleaned) // 2:
                    cleaned = cleaned[:pos]

        return cleaned
