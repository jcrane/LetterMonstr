"""
Summary generator for LetterMonstr Firebase Cloud Functions.

Uses the Anthropic Claude API to generate newsletter summaries.
No direct database access — the caller handles persistence via Firestore.
"""

import logging
import re
from datetime import datetime
from urllib.parse import urlparse

from anthropic import Anthropic

from src.summarize.claude_summarizer import create_claude_prompt

logger = logging.getLogger(__name__)

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

CRITICALLY IMPORTANT - READ MORE LINKS:
* After EACH SECTION you summarize, you MUST include links to the source content
* Each content item has a **PRIMARY SOURCE URL** marked clearly - USE THIS as your main "Read more" link
* If a section is marked with **ALL ADDITIONAL SOURCE URLs**, you MUST include ALL of those URLs in your summary
* When you combine multiple content items into a single summary section, you MUST include ALL links from ALL the aggregated items
* Format links with DESCRIPTIVE text: <a href="URL">Read more from [Publication/Source Name]</a>
* NEVER just use "Read more" - always include the source name in the link text
* If multiple source URLs are provided for a section, create separate "Read more" links for EACH URL
* NEVER omit source links - they are REQUIRED for each section
* Each link should appear on its own line after the relevant content
* ONLY use specific article URLs - NEVER use homepage or root domain URLs
* Examples of good link text:
  - <a href="URL">Read more from The Verge</a>
  - <a href="URL">Full article on TechCrunch</a>
  - <a href="URL">Original post on Substack</a>

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

CRITICALLY IMPORTANT - READ MORE LINKS:
* After EACH SECTION you summarize, you MUST include links to the source content
* Each content item has a **PRIMARY SOURCE URL** marked clearly - USE THIS as your main "Read more" link
* Format links with DESCRIPTIVE text: <a href="URL">Read more from [Publication/Source Name]</a>
* NEVER just use "Read more" - always include the source name in the link text
* If additional source URLs are listed, create separate "Read more" links for each distinct topic/article
* NEVER omit these source links - they are REQUIRED for each section
* Each link should appear on its own line after the relevant content
* ONLY use specific article URLs - NEVER use homepage or root domain URLs
* Examples of good link text:
  - <a href="URL">Read more from The Verge</a>
  - <a href="URL">Full article on TechCrunch</a>
  - <a href="URL">Original post on Substack</a>

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
            dict with keys: summary, title, categories, key_points.
        """
        logger.info(f"Generating summary for {len(processed_content)} content items")

        prepared_content = self._prepare_content_for_summary(processed_content)

        if prepared_content.startswith("NO CONTENT"):
            logger.error("No content available for summarization")
            return {
                "summary": prepared_content,
                "title": "No Content Available",
                "categories": [],
                "key_points": [],
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
            return {"summary": "", "title": "", "categories": [], "key_points": []}

        title, categories, key_points = self._extract_metadata(summary_text)

        summary_text = self._clean_summary(summary_text)

        return {
            "summary": summary_text,
            "title": title,
            "categories": categories,
            "key_points": key_points,
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
* You MUST preserve ALL links from the original summaries
* When combining multiple summaries into one section, you MUST include ALL links from ALL the aggregated content items
* Each section in your combined summary MUST end with ALL relevant source links from all aggregated items
* NEVER remove or omit these links - they are REQUIRED for each section of content
* If a section aggregates content from 3 different sources, you MUST include all 3 links
* Keep the DESCRIPTIVE link text exactly as it appears in the original summaries
* Examples of good link text:
  - <a href="URL">Read more from The Verge</a>
  - <a href="URL">Full article on TechCrunch</a>
  - <a href="URL">Original post on Substack</a>

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
        """Prepare content for summarisation with intelligent token management."""
        formatted_content = []

        if not processed_content:
            logger.error("No content provided for summarization")
            return "NO CONTENT AVAILABLE FOR SUMMARIZATION"

        has_meaningful_content = False
        total_content_length = 0
        min_content_length = 100
        meaningful_items = 0

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

        for item in sorted_content:
            content = item.get('content', '')
            if not content or not isinstance(content, str):
                continue

            item_total_length = len(content)

            if 'articles' in item and isinstance(item['articles'], list):
                for article in item['articles']:
                    if isinstance(article, dict) and 'content' in article:
                        article_content = article.get('content', '')
                        if isinstance(article_content, str):
                            item_total_length += len(article_content)

            if item_total_length > min_content_length:
                has_meaningful_content = True
                meaningful_items += 1
                total_content_length += item_total_length

                if 'urls' not in item and isinstance(item.get('content', ''), str):
                    try:
                        url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                        content_urls = re.findall(url_pattern, item['content'])
                        item['urls'] = self.filter_urls(content_urls)
                    except Exception as e:
                        logger.warning(f"Error extracting URLs from content: {e}")

                if 'articles' in item:
                    for article in item['articles']:
                        if isinstance(article, dict) and 'url' in article:
                            article_url = article['url']
                            if not is_root_domain(article_url):
                                if 'urls' not in item:
                                    item['urls'] = []
                                if article_url not in item['urls']:
                                    item['urls'].append(article_url)

        if not has_meaningful_content:
            logger.error("No meaningful content found for summarization")
            return "NO MEANINGFUL CONTENT AVAILABLE FOR SUMMARIZATION"

        max_tokens = 150000
        available_chars = max_tokens * 4

        logger.info(
            f"Prepared content for summary: {total_content_length} characters, "
            f"~{total_content_length // 4} tokens"
        )

        if total_content_length <= available_chars:
            for item in sorted_content:
                content = item.get('content', '')
                if not isinstance(content, str) or len(content) < min_content_length:
                    continue

                source = item.get('source', 'Unknown Source')
                source_links_text = self._build_source_links(item, is_root_domain)

                formatted_item = f"==== {source} ====\n\n{content}{source_links_text}\n\n"

                for article in item.get('articles', []):
                    if isinstance(article, dict):
                        article_title = article.get('title', 'Article')
                        article_content = article.get('content', '')
                        article_url = article.get('url', '')

                        if article_content and len(article_content) > min_content_length:
                            article_text = f"--- {article_title} ---\n{article_content}\n"
                            if article_url and not is_root_domain(article_url):
                                article_text += f"URL: {article_url}\n"
                            formatted_item += article_text + "\n"

                formatted_content.append(formatted_item)
        else:
            scale_factor = max(available_chars / total_content_length, 0.7)
            logger.info(f"Scaling content by factor {scale_factor:.2f} to fit token limit")

            for item in sorted_content:
                content = item.get('content', '')
                if not isinstance(content, str) or len(content) < min_content_length:
                    continue

                item_length = len(content)
                scaled_length = int(item_length * scale_factor)
                scaled_length = max(scaled_length, min(2000, item_length))

                if scaled_length >= item_length:
                    truncated_content = content
                else:
                    sentence_end_pos = content.rfind('. ', 0, scaled_length)
                    if sentence_end_pos > 0 and (scaled_length - sentence_end_pos) < 100:
                        truncated_content = content[:sentence_end_pos + 1]
                    else:
                        truncated_content = content[:scaled_length]

                source = item.get('source', 'Unknown Source')
                source_links_text = self._build_source_links(item, is_root_domain)

                formatted_item = f"==== {source} ====\n\n{truncated_content}{source_links_text}\n\n"

                for article in item.get('articles', []):
                    if isinstance(article, dict):
                        article_title = article.get('title', 'Article')
                        article_content = article.get('content', '')
                        article_url = article.get('url', '')

                        if article_content and len(article_content) > min_content_length:
                            article_length = len(article_content)
                            article_scaled = int(article_length * scale_factor)
                            article_scaled = max(article_scaled, min(1000, article_length))

                            if article_scaled >= article_length:
                                article_truncated = article_content
                            else:
                                sentence_end = article_content.rfind('. ', 0, article_scaled)
                                if sentence_end > 0 and (article_scaled - sentence_end) < 100:
                                    article_truncated = article_content[:sentence_end + 1]
                                else:
                                    article_truncated = article_content[:article_scaled]

                            article_text = f"--- {article_title} ---\n{article_truncated}\n"
                            if article_url and not is_root_domain(article_url):
                                article_text += f"URL: {article_url}\n"
                            formatted_item += article_text + "\n"

                formatted_content.append(formatted_item)

        return "\n".join(formatted_content)

    def _build_source_links(self, item, is_root_domain):
        """Collect and format source-link annotations for a content item."""
        content = item.get('content', '')
        all_urls = []
        primary_url = None

        if 'url' in item and item['url']:
            item_url = item['url']
            if not self._is_tracking_url(item_url) and not is_root_domain(item_url):
                primary_url = item_url
                all_urls.append(item_url)

        if 'articles' in item and isinstance(item['articles'], list):
            for article in item['articles']:
                if isinstance(article, dict) and 'url' in article and article['url']:
                    article_url = article['url']
                    if (not self._is_tracking_url(article_url)
                            and not is_root_domain(article_url)
                            and article_url not in all_urls):
                        all_urls.append(article_url)
                        if not primary_url:
                            primary_url = article_url

        if 'urls' in item and item['urls']:
            for url in item['urls']:
                if (not self._is_tracking_url(url)
                        and not is_root_domain(url)
                        and url not in all_urls):
                    all_urls.append(url)
                    if not primary_url:
                        primary_url = url

        if isinstance(content, str):
            url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
            content_urls = re.findall(url_pattern, content)
            content_urls = self.filter_urls(content_urls)
            for url in content_urls:
                if (not self._is_tracking_url(url)
                        and not is_root_domain(url)
                        and url not in all_urls):
                    all_urls.append(url)
                    if not primary_url:
                        primary_url = url

        if not all_urls:
            return ""

        clean_urls = []
        seen_clean = set()
        for url in all_urls:
            clean_url = url.split('?')[0] if '?' in url else url
            normalized = clean_url.rstrip('/')
            if normalized not in seen_clean and not is_root_domain(normalized):
                clean_urls.append(clean_url)
                seen_clean.add(normalized)

        if not clean_urls:
            return ""

        primary_clean = clean_urls[0].split('?')[0] if '?' in clean_urls[0] else clean_urls[0]
        source_links_text = f"\n\n**PRIMARY SOURCE URL (USE THIS FOR 'READ MORE' LINK):**\n{primary_clean}\n"

        if len(clean_urls) > 1:
            source_links_text += "\n**ALL ADDITIONAL SOURCE URLs (INCLUDE ALL OF THESE IN YOUR SUMMARY):**\n"
            for url in clean_urls[1:]:
                source_links_text += f"- {url}\n"

        return source_links_text

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
            'utm_source=',
            'utm_medium=',
            'utm_campaign=',
            'referrer=',
            '/ss/c/',
            'CL0/',
            'link.alphasignal.ai',
        ]

        for pattern in redirect_patterns:
            if pattern in url:
                return True

        return False

    def _unwrap_tracking_url(self, url):
        """Extract the actual destination URL from a tracking/redirect URL."""
        if not url or not isinstance(url, str):
            return url

        if not self._is_tracking_url(url):
            return url

        try:
            if 'beehiiv.com' in url or 'link.mail.beehiiv.com' in url:
                logger.info(f"Found beehiiv tracking URL: {url}")

                if 'redirect=' in url:
                    parts = url.split('redirect=', 1)
                    if len(parts) > 1:
                        destination = parts[1]
                        if '&' in destination:
                            destination = destination.split('&', 1)[0]
                        if destination.startswith('http'):
                            logger.info(f"Extracted beehiiv destination URL from redirect param: {destination}")
                            return destination

                if '/to/' in url:
                    parts = url.split('/to/', 1)
                    if len(parts) > 1:
                        destination = parts[1]
                        if destination.startswith('http'):
                            logger.info(f"Extracted beehiiv destination URL from /to/ pattern: {destination}")
                            return destination

                url_pattern = r'https?://(?!link\.mail\.beehiiv\.com|beehiiv\.com)(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                embedded_urls = re.findall(url_pattern, url)

                if embedded_urls:
                    destination = embedded_urls[-1]
                    logger.info(f"Extracted beehiiv destination URL using regex: {destination}")
                    return destination

                logger.warning(f"Could not extract destination from beehiiv URL: {url}")
                return None

            if 'tracking.tldrnewsletter.com/CL0/' in url:
                parts = url.split('CL0/', 1)
                if len(parts) > 1:
                    actual_url = parts[1].split('/', 1)[0] if '/' in parts[1] else parts[1]
                    return actual_url

            embedded_urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', url)

            if embedded_urls:
                for embedded_url in embedded_urls:
                    is_tracking = any(domain in embedded_url for domain in [
                        'beehiiv.com', 'substack.com', 'mailchimp.com',
                        'tracking.tldrnewsletter.com', 'link.mail.beehiiv.com',
                    ])
                    if not is_tracking:
                        return embedded_url

            return None

        except Exception as e:
            logger.error(f"Error unwrapping tracking URL {url}: {e}", exc_info=True)
            return None

    def filter_urls(self, urls, max_urls=50):
        """Filter a list of URLs, removing tracking links and root domains."""
        if not urls:
            return []

        unique_urls = list(set(urls))

        if len(unique_urls) > max_urls:
            logger.info(f"Limiting URL filtering from {len(unique_urls)} to {max_urls} URLs")
            unique_urls = unique_urls[:max_urls]

        filtered = []
        filtered_count = 0

        problematic_domains = [
            'media.beehiiv.com', 'link.mail.beehiiv.com',
            'mailchimp.com',
            'link.genai.works',
        ]

        for url in unique_urls:
            if not isinstance(url, str):
                continue

            if not url.lower().startswith(('http://', 'https://')):
                continue

            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            if any(domain.endswith(prob) for prob in problematic_domains):
                filtered_count += 1
                if filtered_count <= 3:
                    logger.info(f"Filtering out tracking domain URL: {url}")
                elif filtered_count == 4:
                    logger.info("Filtering out additional tracking domain URLs (limiting log output)")
                continue

            filtered.append(url)

        return filtered
