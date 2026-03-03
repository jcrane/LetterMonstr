"""
Summary generator for LetterMonstr application.

This module uses the Anthropic Claude API to generate summaries.
"""

import os
import logging
import time
import json
from datetime import datetime, timedelta
from anthropic import Anthropic
import hashlib
import re

from src.database.models import get_session, Summary, ProcessedContent
from src.summarize.claude_summarizer import create_claude_prompt

logger = logging.getLogger(__name__)

# Define the system prompts for different summary formats
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
"""
}

class SummaryGenerator:
    """Generates summaries using Claude API."""
    
    def __init__(self, config):
        """Initialize with LLM configuration."""
        self.api_key = config['anthropic_api_key']
        self.model = config['model']
        self.max_tokens = config['max_tokens']
        self.temperature = config['temperature']
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'lettermonstr.db')
        self.client = None
        if self.api_key:
            # Updated to work with newer Anthropic client
            self.client = Anthropic(api_key=self.api_key)
    
    def _get_recent_topic_headlines(self, days=5):
        """Load topic headlines from the last N days of summaries.
        
        Parses previous summary HTML/text to extract section headings,
        giving Claude context about what has already been covered recently.
        
        Returns:
            list[dict]: Each entry has 'topic' (str) and 'date' (str).
        """
        session = get_session(self.db_path)
        try:
            threshold = datetime.now() - timedelta(days=days)
            recent_summaries = (
                session.query(Summary)
                .filter(Summary.creation_date >= threshold, Summary.sent == True)
                .order_by(Summary.creation_date.desc())
                .all()
            )

            if not recent_summaries:
                return []

            headlines = []
            for summary in recent_summaries:
                text = summary.summary_text or ''
                date_str = summary.creation_date.strftime('%b %d') if summary.creation_date else ''

                # Extract <h2> headings from HTML output
                h2_matches = re.findall(r'<h2[^>]*>(.*?)</h2>', text, re.IGNORECASE | re.DOTALL)
                for heading in h2_matches:
                    clean = re.sub(r'<[^>]+>', '', heading).strip()
                    if clean and len(clean) > 5:
                        headlines.append({'topic': clean, 'date': date_str})

                # Also try <h3> if no h2 found
                if not h2_matches:
                    h3_matches = re.findall(r'<h3[^>]*>(.*?)</h3>', text, re.IGNORECASE | re.DOTALL)
                    for heading in h3_matches:
                        clean = re.sub(r'<[^>]+>', '', heading).strip()
                        if clean and len(clean) > 5:
                            headlines.append({'topic': clean, 'date': date_str})

                # Fallback: try markdown headings
                if not h2_matches:
                    md_matches = re.findall(r'^#{1,3}\s+(.+)$', text, re.MULTILINE)
                    for heading in md_matches:
                        clean = heading.strip()
                        if clean and len(clean) > 5:
                            headlines.append({'topic': clean, 'date': date_str})

            # Deduplicate while preserving order
            seen = set()
            unique_headlines = []
            for h in headlines:
                key = h['topic'].lower()
                if key not in seen:
                    seen.add(key)
                    unique_headlines.append(h)

            logger.info(f"Extracted {len(unique_headlines)} recent topic headlines from last {days} days")
            return unique_headlines

        except Exception as e:
            logger.error(f"Error loading recent topic headlines: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def _build_recent_topics_context(self, headlines):
        """Format recent topic headlines into a context block for the LLM prompt."""
        if not headlines:
            return ""

        lines = ["RECENTLY COVERED TOPICS (last 5 days):"]
        for h in headlines[:50]:
            lines.append(f'- "{h["topic"]}" (covered {h["date"]})')

        lines.append("")
        lines.append("DEDUPLICATION INSTRUCTIONS:")
        lines.append("- If a content item reports the EXACT SAME news as a recently covered topic with NO new information, SKIP it entirely — do not include it in your summary.")
        lines.append("- If a content item has NEW information, a different perspective, or a meaningful UPDATE on a recently covered topic, include it BRIEFLY as an update, noting what is new.")
        lines.append("- If a content item covers a topic NOT in the recent list above, include it fully.")
        lines.append("- When multiple content items in THIS batch cover the same story, CONSOLIDATE them into one section with all unique perspectives and ALL source links.")
        lines.append("")

        return "\n".join(lines)

    def generate_summary(self, processed_content, format_preferences=None):
        """Generate a summary of the processed content."""
        logger.info(f"Generating summary for {len(processed_content)} content items")
        
        prepared_content = self._prepare_content_for_summary(processed_content)
        
        if prepared_content.startswith("NO CONTENT"):
            logger.error("No content available for summarization")
            return {
                "summary": prepared_content,
                "title": "No Content Available",
                "categories": [],
                "key_points": []
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
            system_prompt += f"\n\nNOTE: You are summarizing a very large amount of content ({content_length} characters). Keep your summary CONCISE and HIGH-LEVEL - focus on essential key findings only, not exhaustive details."
        
        # Inject recent topic context so the LLM can skip/consolidate already-covered stories
        recent_headlines = self._get_recent_topic_headlines(days=5)
        recent_topics_block = self._build_recent_topics_context(recent_headlines)
        if recent_topics_block:
            system_prompt += "\n\n" + recent_topics_block
        
        prompt = self._create_summary_prompt(prepared_content, system_prompt)
        
        summary_text = self._call_claude_api(prompt)
        
        title, categories, key_points = self._extract_metadata(summary_text)
        
        summary_text = self._clean_summary(summary_text)
        
        return {
            "summary": summary_text,
            "title": title,
            "categories": categories,
            "key_points": key_points
        }
    
    def _prepare_content_for_summary(self, processed_content):
        """Prepare content for summarization with intelligent token management."""
        formatted_content = []
        
        # Ensure we have actual content to process
        if not processed_content:
            logger.error("No content provided for summarization")
            return "NO CONTENT AVAILABLE FOR SUMMARIZATION"
        
        # Check if we have meaningful content in the items
        has_meaningful_content = False
        total_content_length = 0
        min_content_length = 100  # Minimum threshold for meaningful content
        
        # Count meaningful content items
        meaningful_items = 0
        
        # Helper function to check if a URL is just a root domain (not a specific article)
        def is_root_domain(url):
            if not url or not isinstance(url, str):
                return True
            
            # Check if it's a tracking URL first
            if self._is_tracking_url(url):
                return True
                
            # Parse the URL
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            
            # Check if it's just a root domain
            # Require at least a meaningful path (more than just /)
            path = parsed_url.path.strip('/')
            return (not path or 
                    parsed_url.path.lower() in ['/', '/index.html', '/index.php', '/home', '/homepage'] or
                    len(path) < 5 or
                    # Filter out common homepage patterns
                    path.lower() in ['index', 'home', 'homepage', 'default'])
        
        # Store the is_root_domain function for other methods to use
        self.is_root_domain = is_root_domain
        
        # Sort items by date if available, otherwise preserve original order
        sorted_content = sorted(
            processed_content,
            key=lambda x: x.get('date', ''),
            reverse=True  # Most recent first
        )
        
        # First pass: calculate total content length and count meaningful items
        for item in sorted_content:
            # Skip items with no content
            content = item.get('content', '')
            if not content or not isinstance(content, str):
                continue
            
            # Calculate the total length of this item including any articles
            item_total_length = len(content)
            
            # Count article content if present
            if 'articles' in item and isinstance(item['articles'], list):
                for article in item['articles']:
                    if isinstance(article, dict) and 'content' in article:
                        article_content = article.get('content', '')
                        if isinstance(article_content, str):
                            item_total_length += len(article_content)
            
            # If this item has meaningful content, count it
            if item_total_length > min_content_length:
                has_meaningful_content = True
                meaningful_items += 1
                total_content_length += item_total_length
                
                # Extract any URLs from raw content for later use
                if 'urls' not in item and isinstance(item.get('content', ''), str):
                    try:
                        import re
                        url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                        content_urls = re.findall(url_pattern, item['content'])
                        item['urls'] = self.filter_urls(content_urls)
                    except Exception as e:
                        logger.warning(f"Error extracting URLs from content: {e}")
                        
                # Extract URLs from articles if present
                if 'articles' in item:
                    for article in item['articles']:
                        if isinstance(article, dict) and 'url' in article:
                            article_url = article['url']
                            # Add URL to item URLs if it's not a root domain
                            if not is_root_domain(article_url):
                                if 'urls' not in item:
                                    item['urls'] = []
                                if article_url not in item['urls']:
                                    item['urls'].append(article_url)
        
        # Check if we have any meaningful content
        if not has_meaningful_content:
            logger.error("No meaningful content found for summarization")
            return "NO MEANINGFUL CONTENT AVAILABLE FOR SUMMARIZATION"
        
        # Estimate available characters for the content based on typical token sizes
        # Anthropic models can handle 200k tokens total, but we need space for prompt and response
        # 1 token is roughly 4 characters in English text
        max_tokens = 150000  # Reserve 50k tokens for prompt overhead and response
        available_chars = max_tokens * 4  # Approx 600k characters
        
        logger.info(f"Prepared content for summary: {total_content_length} characters, ~{total_content_length // 4} tokens")
        
        if total_content_length <= available_chars:
            # If total content fits within token limit, include everything
            for item in sorted_content:
                # Skip items with no meaningful content
                content = item.get('content', '')
                if not isinstance(content, str) or len(content) < min_content_length:
                    continue
                
                # Format this item
                source = item.get('source', 'Unknown Source')
                
                # Extract URLs from the content or item for "Read more" links
                # Collect ALL URLs from all sources - prioritize but don't limit
                all_urls = []
                primary_url = None
                
                # Try to find the primary URL (most specific) from item URL
                if 'url' in item and item['url']:
                    item_url = item['url']
                    # Filter out tracking URLs and root domains
                    if not self._is_tracking_url(item_url) and not is_root_domain(item_url):
                        primary_url = item_url
                        all_urls.append(item_url)
                
                # Collect ALL URLs from articles (these are often the actual content URLs)
                if 'articles' in item and isinstance(item['articles'], list):
                    for article in item['articles']:
                        if isinstance(article, dict) and 'url' in article and article['url']:
                            article_url = article['url']
                            # Filter out tracking URLs and root domains
                            if (not self._is_tracking_url(article_url) and 
                                not is_root_domain(article_url) and 
                                article_url not in all_urls):
                                all_urls.append(article_url)
                                # Set first article URL as primary if we don't have one yet
                                if not primary_url:
                                    primary_url = article_url
                
                # Get additional URLs from the item if we extracted them earlier
                if 'urls' in item and item['urls']:
                    for url in item['urls']:
                        # Filter out tracking URLs and root domains
                        if (not self._is_tracking_url(url) and 
                            not is_root_domain(url) and 
                            url not in all_urls):
                            all_urls.append(url)
                            if not primary_url:
                                primary_url = url
                
                # Extract URLs from the content using regex (last resort)
                if isinstance(content, str):
                    import re
                    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                    content_urls = re.findall(url_pattern, content)
                    content_urls = self.filter_urls(content_urls)
                    for url in content_urls:
                        # Filter out tracking URLs and root domains
                        if (not self._is_tracking_url(url) and 
                            not is_root_domain(url) and 
                            url not in all_urls):
                            all_urls.append(url)
                            if not primary_url:
                                primary_url = url
                
                # Format the source links section with clear PRIMARY URL and ALL additional URLs
                source_links_text = ""
                if all_urls:
                    # Remove tracking parameters and deduplicate
                    clean_urls = []
                    seen_clean = set()
                    for url in all_urls:
                        clean_url = url.split('?')[0] if '?' in url else url
                        # Normalize URL for comparison (remove trailing slash)
                        normalized = clean_url.rstrip('/')
                        if normalized not in seen_clean and not is_root_domain(normalized):
                            clean_urls.append(clean_url)
                            seen_clean.add(normalized)
                    
                    if clean_urls:
                        # Use first URL as primary, rest as secondary
                        primary_clean = clean_urls[0].split('?')[0] if '?' in clean_urls[0] else clean_urls[0]
                        source_links_text = f"\n\n**PRIMARY SOURCE URL (USE THIS FOR 'READ MORE' LINK):**\n{primary_clean}\n"
                        
                        # Include ALL remaining URLs (no limit)
                        if len(clean_urls) > 1:
                            source_links_text += "\n**ALL ADDITIONAL SOURCE URLs (INCLUDE ALL OF THESE IN YOUR SUMMARY):**\n"
                            for url in clean_urls[1:]:
                                source_links_text += f"- {url}\n"
                
                formatted_item = f"==== {source} ====\n\n{content}{source_links_text}\n\n"
                
                # Add articles if present
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
            # Scale down content if it exceeds token limit
            scale_factor = available_chars / total_content_length
            logger.info(f"Scaling content by factor {scale_factor:.2f} to fit token limit")
            
            # Aim to include more important content with a higher minimum scale
            min_scale_factor = 0.7  # Increased from 0.5 to ensure we include at least 70% of each item
            scale_factor = max(scale_factor, min_scale_factor)  
            
            for item in sorted_content:
                # Skip items with no meaningful content
                content = item.get('content', '')
                if not isinstance(content, str) or len(content) < min_content_length:
                    continue
                
                # Calculate scaled length for this item
                item_length = len(content)
                scaled_length = int(item_length * scale_factor)
                
                # Ensure we include at least some of each item
                min_scaled_length = min(2000, item_length)  # Increased from 1000 to 2000 chars
                scaled_length = max(scaled_length, min_scaled_length)
                
                # Use the whole content if possible, only truncate if necessary
                if scaled_length >= item_length:
                    truncated_content = content
                else:
                    # Try to truncate at a sentence boundary if possible
                    sentence_end_pos = content.rfind('. ', 0, scaled_length)
                    if sentence_end_pos > 0 and (scaled_length - sentence_end_pos) < 100:
                        truncated_content = content[:sentence_end_pos+1]
                    else:
                        truncated_content = content[:scaled_length]
                
                # Format this item
                source = item.get('source', 'Unknown Source')
                
                # Extract URLs from the content or item for "Read more" links
                # Collect ALL URLs from all sources - prioritize but don't limit
                all_urls = []
                primary_url = None
                
                # Try to find the primary URL (most specific) from item URL
                if 'url' in item and item['url']:
                    item_url = item['url']
                    # Filter out tracking URLs and root domains
                    if not self._is_tracking_url(item_url) and not is_root_domain(item_url):
                        primary_url = item_url
                        all_urls.append(item_url)
                
                # Collect ALL URLs from articles (these are often the actual content URLs)
                if 'articles' in item and isinstance(item['articles'], list):
                    for article in item['articles']:
                        if isinstance(article, dict) and 'url' in article and article['url']:
                            article_url = article['url']
                            # Filter out tracking URLs and root domains
                            if (not self._is_tracking_url(article_url) and 
                                not is_root_domain(article_url) and 
                                article_url not in all_urls):
                                all_urls.append(article_url)
                                # Set first article URL as primary if we don't have one yet
                                if not primary_url:
                                    primary_url = article_url
                
                # Get additional URLs from the item if we extracted them earlier
                if 'urls' in item and item['urls']:
                    for url in item['urls']:
                        # Filter out tracking URLs and root domains
                        if (not self._is_tracking_url(url) and 
                            not is_root_domain(url) and 
                            url not in all_urls):
                            all_urls.append(url)
                            if not primary_url:
                                primary_url = url
                
                # Extract URLs from the content using regex (last resort)
                if isinstance(content, str):
                    import re
                    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                    content_urls = re.findall(url_pattern, content)
                    content_urls = self.filter_urls(content_urls)
                    for url in content_urls:
                        # Filter out tracking URLs and root domains
                        if (not self._is_tracking_url(url) and 
                            not is_root_domain(url) and 
                            url not in all_urls):
                            all_urls.append(url)
                            if not primary_url:
                                primary_url = url
                
                # Format the source links section with clear PRIMARY URL and ALL additional URLs
                source_links_text = ""
                if all_urls:
                    # Remove tracking parameters and deduplicate
                    clean_urls = []
                    seen_clean = set()
                    for url in all_urls:
                        clean_url = url.split('?')[0] if '?' in url else url
                        # Normalize URL for comparison (remove trailing slash)
                        normalized = clean_url.rstrip('/')
                        if normalized not in seen_clean and not is_root_domain(normalized):
                            clean_urls.append(clean_url)
                            seen_clean.add(normalized)
                    
                    if clean_urls:
                        # Use first URL as primary, rest as secondary
                        primary_clean = clean_urls[0].split('?')[0] if '?' in clean_urls[0] else clean_urls[0]
                        source_links_text = f"\n\n**PRIMARY SOURCE URL (USE THIS FOR 'READ MORE' LINK):**\n{primary_clean}\n"
                        
                        # Include ALL remaining URLs (no limit)
                        if len(clean_urls) > 1:
                            source_links_text += "\n**ALL ADDITIONAL SOURCE URLs (INCLUDE ALL OF THESE IN YOUR SUMMARY):**\n"
                            for url in clean_urls[1:]:
                                source_links_text += f"- {url}\n"
                
                formatted_item = f"==== {source} ====\n\n{truncated_content}{source_links_text}\n\n"
                
                # Add articles if present - using the same scaling approach
                for article in item.get('articles', []):
                    if isinstance(article, dict):
                        article_title = article.get('title', 'Article')
                        article_content = article.get('content', '')
                        article_url = article.get('url', '')
                        
                        if article_content and len(article_content) > min_content_length:
                            # Apply the same scaling to article content
                            article_length = len(article_content)
                            article_scaled_length = int(article_length * scale_factor)
                            article_min_length = min(1000, article_length)
                            article_scaled_length = max(article_scaled_length, article_min_length)
                            
                            # Use full content or truncate as needed
                            if article_scaled_length >= article_length:
                                article_truncated = article_content
                            else:
                                # Try to truncate at a sentence boundary
                                sentence_end = article_content.rfind('. ', 0, article_scaled_length)
                                if sentence_end > 0 and (article_scaled_length - sentence_end) < 100:
                                    article_truncated = article_content[:sentence_end+1]
                                else:
                                    article_truncated = article_content[:article_scaled_length]
                            
                            article_text = f"--- {article_title} ---\n{article_truncated}\n"
                            if article_url and not is_root_domain(article_url):
                                article_text += f"URL: {article_url}\n"
                            formatted_item += article_text + "\n"
                
                formatted_content.append(formatted_item)
        
        # Join all formatted items together
        result = "\n".join(formatted_content)
        
        return result
    
    def _create_summary_prompt(self, content, system_prompt=None):
        """Create a prompt for Claude summarization."""
        # Use the provided system prompt or the default one
        if not system_prompt:
            system_prompt = LLM_SYSTEM_PROMPTS['newsletter']
            
        # Return a dictionary structure instead of calling create_claude_prompt
        return {
            "system": system_prompt,
            "user": f"Please summarize the following newsletter content:\n\n{content}"
        }
    
    def _call_claude_api(self, prompt):
        """Call Claude API to generate a summary."""
        try:
            logger.info(f"Calling Claude API with model {self.model} and max_tokens {self.max_tokens}")
            
            if not self.client:
                logger.error("Claude API client is not initialized - check your API key configuration")
                return "Error: Claude API client is not initialized. Please check your API key configuration."
            
            # Log prompt size for debugging
            system_chars = len(prompt['system']) if 'system' in prompt else 0
            user_chars = len(prompt['user']) if 'user' in prompt else 0
            logger.info(f"Prompt size: system={system_chars} chars, user={user_chars} chars")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,  # Use value from config instead of hardcoding
                system=prompt['system'],
                messages=[
                    {"role": "user", "content": prompt['user']}
                ]
            )
            
            # Extract the summary from the response
            summary = response.content[0].text
            logger.info(f"Claude API responded with {len(summary)} characters")
            
            return summary
        except Exception as e:
            logger.error(f"Error calling Claude API: {e}", exc_info=True)
            return "Error generating summary. Please check logs for details."
    
    def _extract_metadata(self, summary_text):
        """Extract title, categories, and key points from the summary."""
        title = "Newsletter Summary"
        categories = []
        key_points = []
        
        # Try to extract a title from the first line
        lines = summary_text.split('\n')
        if lines and lines[0].strip():
            # Check if first line looks like a title (no period at end, relatively short)
            first_line = lines[0].strip()
            if len(first_line) < 100 and not first_line.endswith('.'):
                title = first_line
        
        # Extract categories (headings)
        category_pattern = r'(?:^|\n)#+\s+(.+?)(?:\n|$)'
        category_matches = re.findall(category_pattern, summary_text)
        if category_matches:
            categories = [cat.strip() for cat in category_matches if cat.strip()]
        
        # Extract key points (bullet points)
        bullet_pattern = r'(?:^|\n)[*\-•]\s+(.+?)(?:\n|$)'
        bullet_matches = re.findall(bullet_pattern, summary_text)
        if bullet_matches:
            key_points = [point.strip() for point in bullet_matches if point.strip()]
        
        return title, categories, key_points
    
    def _clean_summary(self, summary_text):
        """Clean up the summary text by removing any placeholder text or assistant-style responses."""
        # Remove any "Here's a summary..." or "I've summarized..." phrases
        prefixes_to_remove = [
            "Here's a summary",
            "I've summarized",
            "Here is a summary",
            "I have summarized",
            "Below is a summary",
            "The following is a summary"
        ]
        
        for prefix in prefixes_to_remove:
            if summary_text.startswith(prefix):
                # Find the first paragraph break after the prefix
                first_para_end = summary_text.find('\n\n', len(prefix))
                if first_para_end > 0:
                    summary_text = summary_text[first_para_end:].strip()
                break
                
        return summary_text
    
    def _store_summary(self, summary_text, processed_content):
        """Store the summary in the database and mark content as summarized."""
        logger.info("Storing summary in database")
        
        session = get_session(self.db_path)
        max_retries = 3
        retry_count = 0
        retry_delay = 1
        
        while retry_count <= max_retries:
            try:
                # Create a new summary entry
                summary = Summary(
                    content=summary_text,
                    date_generated=datetime.now(),
                    sent=False
                )
                
                session.add(summary)
                session.flush()  # Get the ID without committing
                
                # Mark the content items as summarized
                content_ids = []
                for item in processed_content:
                    try:
                        # Handle both ProcessedContent objects and dictionaries
                        if hasattr(item, 'id'):
                            item_id = item.id
                        elif isinstance(item, dict) and 'id' in item:
                            item_id = item['id']
                        elif hasattr(item, 'db_id'):
                            item_id = item.db_id
                        else:
                            logger.warning(f"Cannot identify ID for content item: {item}")
                            continue
                        
                        # Update the ProcessedContent record
                        content_item = session.query(ProcessedContent).get(item_id)
                        if content_item:
                            content_item.is_summarized = True
                            content_item.summary_id = summary.id
                            content_ids.append(item_id)
                        else:
                            logger.warning(f"ProcessedContent with ID {item_id} not found")
                    except Exception as e:
                        logger.error(f"Error updating ProcessedContent item: {e}")
                
                # Commit all the changes in a single transaction
                session.commit()
                logger.info(f"Summary stored with ID: {summary.id}, marked {len(content_ids)} content items as summarized")
                return summary.id
                
            except Exception as e:
                session.rollback()
                retry_count += 1
                
                if "database is locked" in str(e) and retry_count <= max_retries:
                    logger.warning(f"Database locked during summary storage, retrying in {retry_delay}s (attempt {retry_count}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(f"Error storing summary: {e}", exc_info=True)
                    break
            finally:
                if session:
                    session.close()
        
        logger.error("Failed to store summary after multiple attempts")
        return None
    
    def combine_summaries(self, summaries):
        """Combine multiple summaries into one comprehensive summary."""
        if not summaries:
            return "No summaries to combine"
        
        if len(summaries) == 1:
            return summaries[0]
        
        # Format the summaries for combining
        formatted_content = ""
        for i, summary in enumerate(summaries):
            formatted_content += f"=== SUMMARY BATCH {i+1} ===\n\n{summary}\n\n"
        
        try:
            # Call Claude API with the combined prompt
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
                "user": f"Please combine these newsletter summaries into one CONCISE, HIGH-LEVEL summary that preserves all unique key findings and source links with their descriptive text from each batch:\n\n{formatted_content}"
            }
            combined_summary = self._call_claude_api(combined_prompt)
            return combined_summary
        except Exception as e:
            logger.error(f"Error combining summaries: {e}", exc_info=True)
            # Fallback: just join them with section headers
            fallback = "# COMBINED NEWSLETTER SUMMARY\n\n"
            for i, summary in enumerate(summaries):
                fallback += f"## Batch {i+1} Summary\n\n{summary}\n\n---\n\n"
            return fallback

    def _is_tracking_url(self, url):
        """Check if a URL is a tracking or redirect URL."""
        if not url or not isinstance(url, str):
            return False
            
        # List of known tracking/redirect domains
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
        
        # Check if the URL contains any of the tracking domains
        for domain in tracking_domains:
            if domain in url:
                return True
                
        # Check for typical redirect URL patterns
        redirect_patterns = [
            '/redirect/', 
            '/track/', 
            '/click?', 
            'utm_source=', 
            'utm_medium=', 
            'utm_campaign=',
            'referrer=',
            '/ss/c/',  # Beehiiv specific pattern
            'CL0/',    # TLDR newsletter pattern
            'link.alphasignal.ai', # Another common newsletter service
        ]
        
        for pattern in redirect_patterns:
            if pattern in url:
                return True
                
        return False

    def _unwrap_tracking_url(self, url):
        """Extract the actual destination URL from a tracking/redirect URL."""
        if not url or not isinstance(url, str):
            return url
            
        # Don't try to unwrap if it's not a tracking URL
        if not self._is_tracking_url(url):
            return url
            
        try:
            # Special handling for beehiiv URLs which often don't contain the actual destination
            # in an easily extractable format - these URLs are challenging to unwrap
            if 'beehiiv.com' in url or 'link.mail.beehiiv.com' in url:
                logger.info(f"Found beehiiv tracking URL: {url}")
                
                # For beehiiv, we need to check if we can find an embedded destination URL
                # using multiple patterns as beehiiv formats vary
                
                # Try pattern 1: URLs sometimes contain a parameter with the destination
                if 'redirect=' in url:
                    parts = url.split('redirect=', 1)
                    if len(parts) > 1:
                        destination = parts[1]
                        if '&' in destination:
                            destination = destination.split('&', 1)[0]
                        if destination.startswith('http'):
                            logger.info(f"Extracted beehiiv destination URL from redirect param: {destination}")
                            return destination
                
                # Try pattern 2: Look for patterns like /to/ followed by a URL
                if '/to/' in url:
                    parts = url.split('/to/', 1)
                    if len(parts) > 1:
                        destination = parts[1]
                        if destination.startswith('http'):
                            logger.info(f"Extracted beehiiv destination URL from /to/ pattern: {destination}")
                            return destination
                
                # Try to find any embedded URLs in the beehiiv link - this is a fallback
                import re
                url_pattern = r'https?://(?!link\.mail\.beehiiv\.com|beehiiv\.com)(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
                embedded_urls = re.findall(url_pattern, url)
                
                if embedded_urls:
                    # Get the last URL which is most likely to be the destination
                    destination = embedded_urls[-1]
                    logger.info(f"Extracted beehiiv destination URL using regex: {destination}")
                    return destination
                
                # If we can't extract a URL, log this and consider fetching the URL to resolve the redirect
                logger.warning(f"Could not extract destination from beehiiv URL: {url}")
                
                # At this point we can't reliably extract the destination, so we should 
                # omit this link from the summary rather than showing a tracking URL
                return None
            
            # Handle TLDR newsletter style URLs
            if 'tracking.tldrnewsletter.com/CL0/' in url:
                # Extract the URL after CL0/
                parts = url.split('CL0/', 1)
                if len(parts) > 1:
                    # The actual URL is everything after CL0/ and before an optional trailing parameter
                    actual_url = parts[1].split('/', 1)[0] if '/' in parts[1] else parts[1]
                    return actual_url
            
            # Look for http or https in the URL, which often indicates the start of the actual destination
            import re
            embedded_urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', url)
            
            if embedded_urls:
                # Get the last http(s) URL in the string, which is typically the destination
                # Skip the first one if it's the tracking domain itself
                for embedded_url in embedded_urls:
                    # Skip if it's one of our known tracking domains
                    is_tracking = any(domain in embedded_url for domain in [
                        'beehiiv.com', 'substack.com', 'mailchimp.com', 
                        'tracking.tldrnewsletter.com', 'link.mail.beehiiv.com'
                    ])
                    
                    if not is_tracking:
                        return embedded_url
                        
            # If we can't extract a clear URL, return None
            return None
            
        except Exception as e:
            logger.error(f"Error unwrapping tracking URL {url}: {e}", exc_info=True)
            return None

    def filter_urls(self, urls, max_urls=50):
        """Filter URLs to remove tracking links and root domains.
        
        Args:
            urls: List of URLs to filter
            max_urls: Maximum number of URLs to process to prevent infinite loops
        
        Returns:
            List of filtered URLs
        """
        if not urls:
            return []
        
        # Deduplicate URLs first to reduce processing
        unique_urls = list(set(urls))
        
        # Limit maximum URLs to process
        if len(unique_urls) > max_urls:
            logger.info(f"Limiting URL filtering from {len(unique_urls)} to {max_urls} URLs")
            unique_urls = unique_urls[:max_urls]
            
        filtered = []
        filtered_count = 0
        
        # Reduce the list of problematic domains to only filter tracking/media domains
        problematic_domains = [
            'media.beehiiv.com', 'link.mail.beehiiv.com',
            'mailchimp.com',
            'link.genai.works'
        ]
        
        for url in unique_urls:
            # Skip if not a string
            if not isinstance(url, str):
                continue
            
            # Skip if not http(s)
            if not url.lower().startswith(('http://', 'https://')):
                continue
            
            # Parse the URL
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            
            # Skip if it's a problematic tracking domain
            domain = parsed_url.netloc.lower()
            if any(domain.endswith(prob) for prob in problematic_domains):
                # Log only the first few filtered URLs to avoid log spam
                filtered_count += 1
                if filtered_count <= 3:
                    logger.info(f"Filtering out tracking domain URL: {url}")
                elif filtered_count == 4:
                    logger.info(f"Filtering out additional tracking domain URLs (limiting log output)")
                continue
            
            filtered.append(url)
        
        return filtered