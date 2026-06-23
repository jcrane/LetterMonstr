"""
Summary generator for LetterMonstr Firebase Cloud Functions.

Uses the Anthropic Claude API to generate newsletter summaries.
No direct database access — the caller handles persistence via Firestore.
"""

import logging
import re
from datetime import datetime
from html import escape
from urllib.parse import urlparse

from anthropic import Anthropic
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Matches source citation markers emitted by the model, tolerating common
# formatting variance: [[S3]], [S3], (S3), {{S3}}, optional inner whitespace,
# case-insensitive "s". Capture group 1 is the numeric source id.
_MARKER_RE = re.compile(r'[\[\(\{]{1,2}\s*[Ss](\d{1,3})\s*[\]\)\}]{1,2}')


def _normalize_url(url):
    """Normalize a URL for equality comparison (strip query/fragment/trailing slash)."""
    if not url or not isinstance(url, str):
        return ""
    base = url.split('?', 1)[0].split('#', 1)[0]
    return base.rstrip('/').lower()

LLM_SYSTEM_PROMPTS = {
    'newsletter': """You are an expert email summarizer that creates CONCISE, HIGH-LEVEL summaries of newsletter content. 
Your primary goal is to provide a QUICK OVERVIEW that helps users quickly understand what's important.
Extract only the ESSENTIAL key information, critical insights, and main findings from the provided content.
Be BRIEF and TO THE POINT - focus on high-level information, not exhaustive details.
Keep each section to 2-4 sentences covering only the most important points.
Organize the summary by category or topic, with clear headings.
Be factual, objective, and concise in your coverage.
Focus on WHAT happened and WHY it matters - users can click links for full details.
Your summary should be well-structured with proper headings, paragraphs, bullet points, and clear formatting.

CONTENT PRIORITIZATION - EXTREMELY IMPORTANT:
* PRIORITIZE: AI product developments, new AI capabilities, technology breakthroughs, new tools and platforms
* EMPHASIZE: Product launches, feature releases, technical innovations, research breakthroughs, new capabilities
* MINIMIZE: Funding rounds, venture capital investments, company valuations, and general financial news
* INCLUDE BUT LIMIT: Only major acquisitions and transformative financial deals that significantly impact the industry
* When covering financial news, focus on the strategic and technological implications rather than the financial details
* Keep ALL summaries CONCISE - even prioritized content should be high-level overviews (2-4 sentences max per topic)
* Remember: The goal is a quick scan to identify what's worth reading in full, not comprehensive coverage

WITHIN-BATCH CONSOLIDATION - VERY IMPORTANT:
* Multiple content items in this batch may cover the SAME story or event from different sources.
* When you detect that two or more items are reporting on the same underlying news, CONSOLIDATE them into ONE summary section.
* In the consolidated section, include ALL unique perspectives, details, and angles from every source — never drop a unique fact just because another source also covered the story.
* Include ALL source links from every consolidated item so the reader can explore each source.
* Do NOT repeat the same story in multiple sections.

CRITICALLY IMPORTANT - SOURCE CITATION MARKERS:
* Some source blocks are labelled with a citation marker like [[S3]] (shown in the block header `--- Title [[S3]] ---` and listed under "AVAILABLE SOURCE MARKERS FOR THIS NEWSLETTER").
* After each section you write, copy the marker(s) of every source block you drew that section's information from, exactly as written (e.g. [[S3]] or [[S1]][[S4]]). Put them on their own line at the end of the section.
* When you consolidate multiple sources into one section, include ALL of their markers.
* NEVER write a URL, an <a> tag, or the literal words "Read more" yourself - the system converts each marker into the correct link automatically.
* NEVER invent or guess a marker number that was not given to you. Use only markers that actually appear in the content.
* If a section has no associated marker, write no marker - that is fine, do not fabricate one.

Be concise while preserving critical high-level information and key findings.
Write in a professional, engaging style that provides a quick overview - users can click links for full details.
""",
    'weekly': """You are an expert email summarizer that creates CONCISE weekly digests of newsletter content.
Organize the summary by clear categories (Technology, Business, Science, etc.) with descriptive headings.
For each item, include a BRIEF high-level overview covering only the ESSENTIAL main points and key findings.
Keep each section to 2-4 sentences - focus on what matters most, not exhaustive details.
Use clear hierarchical headings, properly formatted paragraphs, and bullet points for readability.
Be factual, objective, and concise in your coverage.

CONTENT PRIORITIZATION - EXTREMELY IMPORTANT:
* PRIORITIZE: AI product developments, new AI capabilities, technology breakthroughs, new tools and platforms
* EMPHASIZE: Product launches, feature releases, technical innovations, research breakthroughs, new capabilities
* MINIMIZE: Funding rounds, venture capital investments, company valuations, and general financial news
* INCLUDE BUT LIMIT: Only major acquisitions and transformative financial deals that significantly impact the industry
* When covering financial news, focus on the strategic and technological implications rather than the financial details
* Keep ALL summaries CONCISE - even prioritized content should be high-level overviews (2-4 sentences max per topic)
* Remember: The goal is a quick scan to identify what's worth reading in full, not comprehensive coverage

WITHIN-BATCH CONSOLIDATION - VERY IMPORTANT:
* Multiple content items in this batch may cover the SAME story or event from different sources.
* When you detect that two or more items are reporting on the same underlying news, CONSOLIDATE them into ONE summary section.
* In the consolidated section, include ALL unique perspectives, details, and angles from every source — never drop a unique fact just because another source also covered the story.
* Include ALL source links from every consolidated item so the reader can explore each source.
* Do NOT repeat the same story in multiple sections.

CRITICALLY IMPORTANT - SOURCE CITATION MARKERS:
* Some source blocks are labelled with a citation marker like [[S3]] (shown in the block header `--- Title [[S3]] ---` and listed under "AVAILABLE SOURCE MARKERS FOR THIS NEWSLETTER").
* After each section you write, copy the marker(s) of every source block you drew that section's information from, exactly as written (e.g. [[S3]] or [[S1]][[S4]]). Put them on their own line at the end of the section.
* When you consolidate multiple sources into one section, include ALL of their markers.
* NEVER write a URL, an <a> tag, or the literal words "Read more" yourself - the system converts each marker into the correct link automatically.
* NEVER invent or guess a marker number that was not given to you. Use only markers that actually appear in the content.
* If a section has no associated marker, write no marker - that is fine, do not fabricate one.

Write in a professional, engaging style that makes complex topics accessible through concise high-level overviews.
Focus on key findings and essential information - users can click links to explore the full depth of any topic.
""",
}


class SummaryGenerator:
    """Generates summaries using the Claude API."""

    def __init__(self, config):
        """Initialize with LLM configuration dict.

        Expected keys: anthropic_api_key, model, max_tokens, temperature.
        """
        self.api_key = config['anthropic_api_key']
        self.model = config['model']
        self.max_tokens = config['max_tokens']
        self.temperature = config['temperature']
        self.client = None
        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_summary(self, processed_content, format_preferences=None,
                         recent_headlines=None):
        """Generate a summary of the processed content.

        Args:
            processed_content: List of content dicts to summarise.
            format_preferences: Optional dict with 'format' key
                ('newsletter' or 'weekly').
            recent_headlines: Optional list of dicts with 'topic' and 'date'
                keys used for cross-summary deduplication context.

        Returns:
            dict with keys: summary, title, categories, key_points, source_urls.
        """
        logger.info(f"Generating summary for {len(processed_content)} content items")

        prepared_content, registry = self._prepare_content_for_summary(processed_content)
        source_urls = [entry['url'] for entry in registry.values()]

        if prepared_content.startswith("NO CONTENT") or prepared_content.startswith("NO MEANINGFUL"):
            logger.error("No content available for summarization")
            return {
                "summary": prepared_content,
                "title": "No Content Available",
                "categories": [],
                "key_points": [],
                "source_urls": [],
            }

        logger.info(f"Prepared content length: {len(prepared_content)} characters")

        format_prefs = format_preferences or {}
        summary_format = format_prefs.get('format', 'newsletter')

        day_context = ""
        if summary_format == 'weekly':
            today = datetime.today()
            day_context = f"Today is {today.strftime('%A, %B %d')}. "

        system_prompt = LLM_SYSTEM_PROMPTS.get(summary_format, LLM_SYSTEM_PROMPTS['newsletter'])

        if summary_format == 'weekly':
            system_prompt = day_context + system_prompt

        content_length = len(prepared_content)
        token_estimate = content_length // 4

        if token_estimate > 10000:
            system_prompt += (
                f"\n\nNOTE: You are summarizing a very large amount of content "
                f"({content_length} characters). Keep your summary CONCISE and "
                f"HIGH-LEVEL - focus on essential key findings only, not exhaustive details."
            )

        if recent_headlines:
            recent_topics_block = self._build_recent_topics_context(recent_headlines)
            if recent_topics_block:
                system_prompt += "\n\n" + recent_topics_block

        prompt = self._create_summary_prompt(prepared_content, system_prompt)

        summary_text = self._call_claude_api(prompt)

        if not summary_text:
            logger.error("Claude API returned no summary")
            return {"summary": "", "title": "", "categories": [], "key_points": [],
                    "source_urls": []}

        title, categories, key_points = self._extract_metadata(summary_text)

        summary_text = self._clean_summary(summary_text)
        summary_text = self._expand_markers(summary_text, registry)

        return {
            "summary": summary_text,
            "title": title,
            "categories": categories,
            "key_points": key_points,
            "source_urls": source_urls,
        }

    def combine_summaries(self, summaries):
        """Combine multiple batch summaries into one comprehensive summary."""
        if not summaries:
            return "No summaries to combine"

        if len(summaries) == 1:
            return summaries[0]

        formatted_content = ""
        for i, summary in enumerate(summaries):
            formatted_content += f"=== SUMMARY BATCH {i+1} ===\n\n{summary}\n\n"

        try:
            logger.info(f"Combining {len(summaries)} summaries into one")
            combined_prompt = {
                "system": """You are a newsletter summarization assistant for the LetterMonstr application.
Your task is to combine multiple newsletter summaries into one CONCISE, HIGH-LEVEL summary.

The summaries below are from different batches of newsletters that have been processed separately.
Please combine these summaries into a single coherent summary that:

1. PRESERVES ALL UNIQUE KEY FINDINGS from each summary - focus on essential high-level information
2. Eliminates redundancy between the different summaries
3. Organizes information by topic, not by summary batch
4. Each topic should be 2-4 sentences covering only the most important points
5. Maintains a clear structure with section headers
6. PRESERVES ALL SOURCE LINKS - CRITICALLY IMPORTANT!
7. Improves the overall flow and readability while keeping it concise

CONTENT PRIORITIZATION - EXTREMELY IMPORTANT:
* PRIORITIZE: AI product developments, new AI capabilities, technology breakthroughs, new tools and platforms
* EMPHASIZE: Product launches, feature releases, technical innovations, research breakthroughs, new capabilities
* MINIMIZE: Funding rounds, venture capital investments, company valuations, and general financial news
* INCLUDE BUT LIMIT: Only major acquisitions and transformative financial deals that significantly impact the industry
* When covering financial news, focus on the strategic and technological implications rather than the financial details
* Keep ALL summaries CONCISE - even prioritized content should be high-level overviews (2-4 sentences max per topic)
* Remember: The goal is a quick scan to identify what's worth reading in full, not comprehensive coverage

CRITICALLY IMPORTANT - SOURCE LINKS:
* The summaries below already contain finished <a href="..."> link tags.
* Copy every <a> tag VERBATIM - never change, shorten, merge, or fabricate an href, and never invent a new URL or <a> tag of your own.
* When you merge multiple sections into one, keep ALL of their <a> tags together in the merged section.
* NEVER remove or omit a link - if a merged section came from 3 sources, include all 3 <a> tags.
* Keep each link's visible text exactly as written in the original summaries.

Keep the combined summary CONCISE and HIGH-LEVEL - focus on essential key findings, not exhaustive details.
If in doubt about whether content is unique or redundant, include the key finding but keep it brief - users can click links for full details.""",
                "user": (
                    "Please combine these newsletter summaries into one CONCISE, HIGH-LEVEL summary "
                    "that preserves all unique key findings and source links with their descriptive text "
                    f"from each batch:\n\n{formatted_content}"
                ),
            }
            result = self._call_claude_api(combined_prompt)
            if not result:
                logger.error("Claude API returned no result for combined summary")
                return "\n\n---\n\n".join(summaries)
            return result
        except Exception as e:
            logger.error(f"Error combining summaries: {e}", exc_info=True)
            return "\n\n---\n\n".join(summaries)

    # ------------------------------------------------------------------
    # Recent-topics context for cross-summary dedup
    # ------------------------------------------------------------------

    def _build_recent_topics_context(self, headlines):
        """Format recent topic headlines into a context block for the LLM prompt."""
        if not headlines:
            return ""

        lines = ["RECENTLY COVERED TOPICS (last 5 days):"]
        for h in headlines[:50]:
            lines.append(f'- "{h["topic"]}" (covered {h["date"]})')

        lines.append("")
        lines.append("DEDUPLICATION INSTRUCTIONS:")
        lines.append(
            "- If a content item reports the EXACT SAME news as a recently covered "
            "topic with NO new information, SKIP it entirely — do not include it in your summary."
        )
        lines.append(
            "- If a content item has NEW information, a different perspective, or a "
            "meaningful UPDATE on a recently covered topic, include it BRIEFLY as an update, noting what is new."
        )
        lines.append("- If a content item covers a topic NOT in the recent list above, include it fully.")
        lines.append(
            "- When multiple content items in THIS batch cover the same story, CONSOLIDATE "
            "them into one section with all unique perspectives and ALL source links."
        )
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Content preparation
    # ------------------------------------------------------------------

    def _prepare_content_for_summary(self, processed_content):
        """Prepare content for summarisation, tagging crawl-validated sources
        with citation markers ([[S1]], [[S2]], ...).

        Returns:
            (formatted_text, registry) where registry maps each integer marker
            id to {'url', 'title', 'source'}.
        """
        formatted_content = []

        if not processed_content:
            logger.error("No content provided for summarization")
            return "NO CONTENT AVAILABLE FOR SUMMARIZATION", {}

        min_content_length = 100

        def is_root_domain(url):
            if not url or not isinstance(url, str):
                return True
            if self._is_tracking_url(url):
                return True
            parsed_url = urlparse(url)
            path = parsed_url.path.strip('/')
            return (
                not path
                or parsed_url.path.lower() in ['/', '/index.html', '/index.php', '/home', '/homepage']
                or len(path) < 5
                or path.lower() in ['index', 'home', 'homepage', 'default']
            )

        self.is_root_domain = is_root_domain

        sorted_content = sorted(
            processed_content,
            key=lambda x: x.get('date', ''),
            reverse=True,
        )

        registry, article_markers = self._build_source_registry(sorted_content, is_root_domain)

        has_meaningful_content = False
        total_content_length = 0
        for item in sorted_content:
            content = item.get('content', '')
            if not content or not isinstance(content, str):
                continue
            item_total_length = len(content)
            for article in item.get('articles', []) or []:
                if isinstance(article, dict) and isinstance(article.get('content', ''), str):
                    item_total_length += len(article['content'])
            if item_total_length > min_content_length:
                has_meaningful_content = True
                total_content_length += item_total_length

        if not has_meaningful_content:
            logger.error("No meaningful content found for summarization")
            return "NO MEANINGFUL CONTENT AVAILABLE FOR SUMMARIZATION", {}

        max_tokens = 150000
        available_chars = max_tokens * 4
        scale_factor = (
            1.0 if total_content_length <= available_chars
            else max(available_chars / total_content_length, 0.7)
        )

        logger.info(
            f"Prepared content for summary: {total_content_length} characters, "
            f"~{total_content_length // 4} tokens"
        )
        if scale_factor < 1.0:
            logger.info(f"Scaling content by factor {scale_factor:.2f} to fit token limit")

        for item in sorted_content:
            content = item.get('content', '')
            if not isinstance(content, str) or len(content) < min_content_length:
                continue

            source = item.get('source', 'Unknown Source')
            body = self._scale_text(content, scale_factor, floor=2000)
            formatted_item = f"==== {source} ====\n\n{body}\n\n"

            item_marker_ids = []
            for article in item.get('articles', []) or []:
                if not isinstance(article, dict):
                    continue
                article_content = article.get('content', '')
                if not article_content or len(article_content) <= min_content_length:
                    continue

                article_title = article.get('title', 'Article')
                marker_id = article_markers.get(id(article))
                marker = f" [[S{marker_id}]]" if marker_id else ""
                if marker_id and marker_id not in item_marker_ids:
                    item_marker_ids.append(marker_id)

                article_body = self._scale_text(article_content, scale_factor, floor=1000)
                formatted_item += f"--- {article_title}{marker} ---\n{article_body}\n\n"

            if item_marker_ids:
                formatted_item += (
                    "AVAILABLE SOURCE MARKERS FOR THIS NEWSLETTER: "
                    + " ".join(f"[[S{m}]]" for m in item_marker_ids)
                    + "\n\n"
                )

            formatted_content.append(formatted_item)

        return "\n".join(formatted_content), registry

    def _build_source_registry(self, sorted_content, is_root_domain):
        """Assign citation markers to crawl-validated article URLs.

        Only URLs that came from successfully crawled articles are eligible —
        these are the destinations that were actually fetched, so they are the
        only links guaranteed to resolve. Tracking wrappers and root-domain
        URLs are excluded.

        Returns:
            (registry, article_markers):
                registry: {marker_id: {'url', 'title', 'source'}}
                article_markers: {id(article_dict): marker_id}
        """
        registry = {}
        article_markers = {}
        url_to_id = {}
        next_id = 1

        for item in sorted_content:
            source = (item.get('source', '') or '').strip()
            for article in item.get('articles', []) or []:
                if not isinstance(article, dict):
                    continue
                url = article.get('url', '')
                if not url or self._is_tracking_url(url) or is_root_domain(url):
                    continue
                norm = _normalize_url(url)
                if not norm:
                    continue

                marker_id = url_to_id.get(norm)
                if marker_id is None:
                    marker_id = next_id
                    next_id += 1
                    url_to_id[norm] = marker_id
                    registry[marker_id] = {
                        'url': url,
                        'title': (article.get('title') or '').strip(),
                        'source': source,
                    }
                article_markers[id(article)] = marker_id

        logger.info(
            "Source registry built: %d unique URLs from %d items",
            len(registry), len(sorted_content),
        )
        for mid, entry in list(registry.items())[:5]:
            logger.info("  [S%d] %s — %s", mid, entry['source'][:60], entry['url'])
        if len(registry) > 5:
            logger.info("  ... and %d more", len(registry) - 5)

        return registry, article_markers

    @staticmethod
    def _scale_text(text, scale_factor, floor):
        """Truncate text to roughly scale_factor of its length, on a sentence
        boundary where possible. Returns the full text when not scaling."""
        if scale_factor >= 1.0 or not isinstance(text, str):
            return text
        item_length = len(text)
        scaled_length = max(int(item_length * scale_factor), min(floor, item_length))
        if scaled_length >= item_length:
            return text
        sentence_end = text.rfind('. ', 0, scaled_length)
        if sentence_end > 0 and (scaled_length - sentence_end) < 100:
            return text[:sentence_end + 1]
        return text[:scaled_length]

    def _expand_markers(self, text, registry):
        """Replace citation markers ([[S3]]) with validated <a> links.

        Markers whose id is not in the registry are dropped, so the model can
        never emit a link the system did not validate.
        """
        if not text:
            return text

        marker_matches = list(_MARKER_RE.finditer(text))
        unknown_count = sum(
            1 for m in marker_matches if int(m.group(1)) not in registry
        )
        expanded_count = len(marker_matches) - unknown_count
        logger.info(
            "Marker expansion: %d markers in text, %d expanded, %d dropped (id not in registry of %d)",
            len(marker_matches), expanded_count, unknown_count, len(registry),
        )

        def repl(match):
            entry = registry.get(int(match.group(1)))
            if not entry:
                return ""
            title = (entry.get('title') or '').strip()
            source = (entry.get('source') or '').strip()
            if title and len(title) <= 120:
                label = f"Read more: {title}"
            elif source:
                label = f"Read more from {source}"
            else:
                label = "Read more"
            href = escape(entry["url"], quote=True)
            return f'<a href="{href}" class="read-more">{escape(label)}</a>'

        expanded = _MARKER_RE.sub(repl, text)
        # When a section cites several sources, the markers may be adjacent
        # (e.g. [[S1]][[S4]]). Separate consecutive "Read more" links with a
        # line break so each renders on its own line as a list.
        expanded = re.sub(
            r'</a>\s*(<a [^>]*class="read-more")',
            r'</a><br>\1',
            expanded,
        )
        return expanded

    def _strip_unvalidated_anchors(self, html, valid_urls):
        """Remove <a> tags whose href is not among the validated source URLs.

        A final safety net: even if the combine step or the model produces an
        anchor for a URL that was never crawl-validated, it is reduced to plain
        text here. Matching is done on normalized URLs so query/fragment
        differences do not cause false drops.
        """
        if not html:
            return html
        valid = {_normalize_url(u) for u in (valid_urls or []) if u}
        try:
            soup = BeautifulSoup(html, 'html.parser')
            anchors = list(soup.find_all('a'))
            stripped = 0
            for link in anchors:
                href = link.get('href')
                if not href or _normalize_url(href) not in valid:
                    if href:
                        logger.info("Stripping unvalidated anchor: %s", href)
                    link.replace_with(link.text)
                    stripped += 1
            logger.info(
                "Anchor strip: %d anchors checked, %d kept, %d stripped (validity set: %d URLs)",
                len(anchors), len(anchors) - stripped, stripped, len(valid),
            )
            return str(soup)
        except Exception:
            logger.error("Error stripping unvalidated anchors", exc_info=True)
            return html

    # ------------------------------------------------------------------
    # Prompt & API
    # ------------------------------------------------------------------

    def _create_summary_prompt(self, content, system_prompt=None):
        """Build the prompt dict for Claude summarisation."""
        if not system_prompt:
            system_prompt = LLM_SYSTEM_PROMPTS['newsletter']

        return {
            "system": system_prompt,
            "user": f"Please summarize the following newsletter content:\n\n{content}",
        }

    def _call_claude_api(self, prompt):
        """Call the Claude API using streaming and return the generated text.

        Returns the summary text on success, or None on failure.
        """
        try:
            logger.info(f"Calling Claude API with model {self.model} and max_tokens {self.max_tokens}")

            if not self.client:
                logger.error("Claude API client is not initialized - check your API key configuration")
                return None

            system_chars = len(prompt.get('system', ''))
            user_chars = len(prompt.get('user', ''))
            logger.info(f"Prompt size: system={system_chars} chars, user={user_chars} chars")

            with self.client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=prompt['system'],
                messages=[{"role": "user", "content": prompt['user']}],
            ) as stream:
                response = stream.get_final_message()

            summary = response.content[0].text
            logger.info(f"Claude API responded with {len(summary)} characters")

            return summary
        except Exception as e:
            logger.error(f"Error calling Claude API: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _extract_metadata(self, summary_text):
        """Extract title, categories, and key points from the summary."""
        title = "Newsletter Summary"
        categories = []
        key_points = []

        lines = summary_text.split('\n')
        if lines and lines[0].strip():
            first_line = lines[0].strip()
            if len(first_line) < 100 and not first_line.endswith('.'):
                title = first_line

        category_pattern = r'(?:^|\n)#+\s+(.+?)(?:\n|$)'
        category_matches = re.findall(category_pattern, summary_text)
        if category_matches:
            categories = [cat.strip() for cat in category_matches if cat.strip()]

        bullet_pattern = r'(?:^|\n)[*\-•]\s+(.+?)(?:\n|$)'
        bullet_matches = re.findall(bullet_pattern, summary_text)
        if bullet_matches:
            key_points = [point.strip() for point in bullet_matches if point.strip()]

        return title, categories, key_points

    def _clean_summary(self, summary_text):
        """Remove assistant-style preamble from the summary."""
        prefixes_to_remove = [
            "Here's a summary",
            "I've summarized",
            "Here is a summary",
            "I have summarized",
            "Below is a summary",
            "The following is a summary",
        ]

        for prefix in prefixes_to_remove:
            if summary_text.startswith(prefix):
                first_para_end = summary_text.find('\n\n', len(prefix))
                if first_para_end > 0:
                    summary_text = summary_text[first_para_end:].strip()
                break

        return summary_text

    # ------------------------------------------------------------------
    # URL utilities
    # ------------------------------------------------------------------

    def _is_tracking_url(self, url):
        """Return True if the URL belongs to a known tracking/redirect service."""
        if not url or not isinstance(url, str):
            return False

        tracking_domains = [
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
            'url9934.notifications.substack.com',
            'tracking.tldrnewsletter.com',
            'beehiiv.com',
            'substack.com',
            'mailchimp.com',
            'convertkit.com',
            'constantcontact.com',
            'hubspotemail.net',
        ]

        for domain in tracking_domains:
            if domain in url:
                return True

        redirect_patterns = [
            '/redirect/',
            '/track/',
            '/click?',
            '/ss/c/',
            'CL0/',
            'link.alphasignal.ai',
        ]

        for pattern in redirect_patterns:
            if pattern in url:
                return True

        return False
