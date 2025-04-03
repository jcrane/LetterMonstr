"""
Summary generator for LetterMonstr application.

This module uses the Anthropic Claude API to generate summaries.
"""

import os
import logging
import time
import json
from datetime import datetime
from anthropic import Anthropic
import hashlib

from src.database.models import get_session, Summary, ProcessedContent
from src.summarize.claude_summarizer import create_claude_prompt

logger = logging.getLogger(__name__)

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
    
    def generate_summary(self, processed_content):
        """Generate a summary of processed content."""
        if not processed_content:
            logger.warning("No content to summarize")
            return ""
        
        try:
            # Convert processed content to string format for the prompt
            content_for_summary = self._prepare_content_for_summary(processed_content)
            
            # Create prompt for Claude
            prompt = self._create_summary_prompt(content_for_summary)
            
            # Call Claude API to generate summary
            summary_text = self._call_claude_api(prompt)
            
            # Store the summary in the database
            summary_id = self._store_summary(summary_text, processed_content)
            
            # Store content signatures for future deduplication
            from src.summarize.processor import ContentProcessor
            content_processor = ContentProcessor({'ad_keywords': []})
            content_processor.store_summarized_content(summary_id, processed_content)
            
            return summary_text
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}", exc_info=True)
            return "Error generating summary. Please check logs for details."
    
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
        
        for item in processed_content:
            content = item.get('content', '')
            if isinstance(content, str) and len(content) > min_content_length:
                has_meaningful_content = True
                total_content_length += len(content)
                meaningful_items += 1
        
        if not has_meaningful_content:
            logger.error("No meaningful content found in processed items")
            # Create a clear message about the empty content
            empty_message = "NO MEANINGFUL NEWSLETTER CONTENT TO SUMMARIZE\n\n"
            
            # Add details about what was received
            empty_message += f"Received {len(processed_content)} content items, but none contained meaningful text.\n"
            empty_message += "Content sources:\n"
            
            for item in processed_content:
                source = item.get('source', 'Unknown')
                content_len = len(item.get('content', '')) if isinstance(item.get('content', ''), str) else 0
                empty_message += f"- {source}: {content_len} characters\n"
            
            return empty_message
        
        logger.info(f"Found {meaningful_items} meaningful content items with total length of {total_content_length} characters")
        
        # Estimate tokens per character (approximation)
        tokens_per_char = 0.25  # A rough estimate: ~4 characters per token for English
        
        # Target maximum tokens for the content portion (leaving room for instructions and other parts)
        max_content_tokens = 180000  # Approximately 180K tokens for Claude 3.7 Sonnet
        
        # Reserve tokens for instructions and overhead
        reserved_tokens = 20000  # Reserve 20K tokens for instructions and other parts
        
        # Available tokens for content
        available_tokens = max_content_tokens - reserved_tokens
        
        # Estimate total content size
        total_chars = total_content_length
        estimated_tokens = total_chars * tokens_per_char
        
        logger.info(f"Estimated content size: {total_chars} chars, ~{int(estimated_tokens)} tokens")
        
        # Calculate scaling factor if we need to reduce content
        scaling_factor = 1.0
        if estimated_tokens > available_tokens:
            scaling_factor = available_tokens / estimated_tokens
            logger.warning(f"Content too large, scaling down to {scaling_factor:.2f} of original size")
        
        # Add each content item with scaled sizes
        for item in processed_content:
            # Add basic item information
            item_text = f"SOURCE: {item.get('source', 'Unknown')}\n"
            
            # Handle date which could be a string or datetime object
            date_value = item.get('date', datetime.now())
            if isinstance(date_value, str):
                # If it's a string, just use it directly
                item_text += f"DATE: {date_value}\n"
            else:
                # If it's a datetime object, format it
                try:
                    item_text += f"DATE: {date_value.strftime('%Y-%m-%d')}\n"
                except Exception as e:
                    # Fallback to current date if there's any error
                    logger.warning(f"Error formatting date: {e}, using current date")
                    item_text += f"DATE: {datetime.now().strftime('%Y-%m-%d')}\n"
            
            item_text += "\n"
            
            # If this is a merged item, include all sources
            if item.get('is_merged', False) and 'sources' in item:
                item_text += f"MERGED FROM SOURCES: {', '.join(item['sources'])}\n\n"
            
            # Add main content with intelligent size management
            content = item.get('content', '')
            content_size = len(content)
            
            # Calculate maximum allowed size for this content based on scaling
            if scaling_factor < 1.0:
                # Scale down content size based on its proportion of the total
                max_content_chars = int(content_size * scaling_factor)
                
                # Ensure minimum reasonable size
                max_content_chars = max(3000, max_content_chars)
                
                if content_size > max_content_chars:
                    # Intelligent truncation - include beginning and end
                    first_portion = content[:max_content_chars // 2]
                    second_portion = content[-(max_content_chars // 2):]
                    content = first_portion + "\n\n[...CONTENT ABBREVIATED...]\n\n" + second_portion
                    logger.debug(f"Truncated content for '{item.get('source', 'Unknown')}' from {content_size} to {len(content)} chars")
            
            item_text += f"CONTENT:\n{content}\n\n"
            
            # Add source URLs if available - AFTER the content
            email_content = item.get('original_email', {})
            source_links = []
            
            # Check if there's a web version link in the email
            if isinstance(email_content, dict) and 'links' in email_content:
                for link in email_content.get('links', []):
                    # Look for typical "View in browser" or "Web version" links
                    title = link.get('title', '').lower()
                    url = link.get('url', '')
                    
                    # Filter out tracking/redirect URLs
                    if self._is_tracking_url(url):
                        # Try to unwrap the tracking URL
                        unwrapped_url = self._unwrap_tracking_url(url)
                        if unwrapped_url:
                            url = unwrapped_url
                        else:
                            logger.warning(f"Skipping tracking URL that couldn't be unwrapped: {url}")
                            continue
                        
                    if url and ('web' in title or 'browser' in title or 'view' in title):
                        source_links.append(f"WEB VERSION: {link.get('title', 'Web Version')} - {url}")
                        break
            
            # Add article URLs
            articles = item.get('articles', [])
            for article in articles:
                article_url = article.get('url', '')
                article_title = article.get('title', '')
                
                # Filter out tracking/redirect URLs or unwrap them
                if self._is_tracking_url(article_url):
                    # Try to unwrap the tracking URL
                    unwrapped_url = self._unwrap_tracking_url(article_url)
                    if unwrapped_url:
                        article_url = unwrapped_url
                    else:
                        logger.warning(f"Skipping tracking URL for article '{article_title}': {article_url}")
                        continue
                    
                if article_url and article_title:
                    source_links.append(f"ARTICLE: {article_title} - {article_url}")
            
            # Add source links to the content
            if source_links:
                item_text += "SOURCE LINKS:\n" + "\n".join(source_links) + "\n"
                
                # Also add a more explicit message about using these links for "Read more" links
                item_text += "\nIMPORTANT: For the article summaries in this section, use the above URLs as 'Read more' links.\n"
                item_text += "DO NOT use any tracking URLs that contain 'beehiiv', 'mailchimp', 'constantcontact', etc. Only use direct article URLs.\n"
            
            # Add to formatted content
            formatted_content.append(item_text)
        
        # Join all items with a separator
        final_content = "\n\n" + "-" * 50 + "\n\n".join(formatted_content)
        
        # Final safety check
        final_size = len(final_content)
        final_tokens = int(final_size * tokens_per_char)
        logger.info(f"Final prepared content: {final_size} chars, ~{final_tokens} tokens")
        
        return final_content
    
    def _create_summary_prompt(self, content):
        """Create a prompt for Claude to generate a summary."""
        instructions = """
Follow these guidelines:
1. MOST IMPORTANT: Be thorough and comprehensive - include ALL meaningful content, stories, and insights from the source material.
2. Do not omit any significant articles, stories or topics from the newsletters.
3. Focus on factual information and key insights.
4. AGGRESSIVELY REMOVE DUPLICATES: Many articles will appear multiple times across different newsletters.
   - When you see the same story covered in multiple sources, combine them into a SINGLE summary
   - Identify articles with the same topic or subject matter even if the titles differ
   - Look for identical or nearly identical content and only include it once
   - Include all unique details, but don't repeat the same information
   - Mention if an item was covered by multiple sources, but only summarize it once
5. Organize information by topic, not by source.
6. Remove any content that appears to be advertising or sponsored.
7. Include important details like dates, statistics, and key findings.
8. Present a balanced view without injecting your own opinions.
9. Use proper HTML formatting for email:
   - Use <h2> tags for main section headers (e.g., "AI NEWS AND UPDATES")
   - Use <h3> tags for subsections
   - Use <ul> and <li> tags for lists
   - Use compact spacing - avoid excessive blank lines between sections
   - Use <hr> tags to separate major sections
10. For EACH article or story from the newsletters, include a brief summary - don't skip any articles.
11. IMPORTANT LINK FORMATTING: 
   - After each summarized article or story, include a "Read more" link to the original article
   - Format each link as: <a href="ACTUAL_URL">Read more →</a>
   - Use the article URLs from the SOURCE LINKS section at the end of each content block
   - Each summarized item should have its own "Read more" link that points to its specific source
   - Place these links right after each article summary with minimal spacing
12. If you find yourself omitting content due to length, create a separate "ADDITIONAL STORIES" section rather than leaving items out completely.

The summary should be thorough and detailed, prioritizing completeness over brevity.
Make sure all "Read more" links are properly formatted as HTML <a> tags so they're clickable in the email.

IMPORTANT: Format for proper HTML email display. DO include HTML formatting and ensure all links are properly formatted as <a href="url">link text</a>.
"""
        # Use the shared prompt generator with our specific instructions
        return create_claude_prompt(instructions, content)
    
    def _call_claude_api(self, prompt):
        """Call Claude API to generate summary."""
        if not self.client:
            logger.error("Claude API client not initialized, API key may be missing")
            return "Error: Claude API not configured properly. Please check your API key."
        
        try:
            # Rate limiting - Claude may have rate limits
            time.sleep(1)
            
            # Call Claude API with updated API format for newer Anthropic version
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract and return the summary text
            # Updated to match the newer response format
            if hasattr(response, 'content') and len(response.content) > 0:
                summary_text = response.content[0].text
                return summary_text
            else:
                logger.error("Unexpected response format from Claude API")
                return "Error: Unexpected response format from Claude API"
            
        except Exception as e:
            logger.error(f"Error calling Claude API: {e}", exc_info=True)
            return f"Error generating summary: {str(e)}"
    
    def _store_summary(self, summary_text, processed_content):
        """Store the summary and mark content as summarized."""
        if not summary_text or not processed_content:
            return None
            
        # Open database session
        session = get_session(self.db_path)
        try:
            # Create summary record
            summary = Summary(
                summary_type='daily',
                summary_text=summary_text,
                period_start=datetime.now(),
                period_end=datetime.now(),
                creation_date=datetime.now(),
                sent=False
            )
            
            session.add(summary)
            session.flush()  # Get the ID
            
            # Update processed content records to mark them as summarized
            content_hashes = []
            for item in processed_content:
                # Create content hash for lookup
                content = item.get('content', '')
                title = item.get('source', '')
                content_hash = hashlib.md5((title + content[:100]).encode('utf-8')).hexdigest()
                content_hashes.append(content_hash)
            
            # Update the processed content items
            session.query(ProcessedContent).filter(
                ProcessedContent.content_hash.in_(content_hashes)
            ).update(
                {
                    'is_summarized': True,
                    'summary_id': summary.id
                },
                synchronize_session=False
            )
            
            # Commit changes
            session.commit()
            logger.info(f"Stored summary {summary.id} and marked {len(content_hashes)} content items as summarized")
            
            return summary.id
            
        except Exception as e:
            logger.error(f"Error storing summary: {e}", exc_info=True)
            session.rollback()
            return None
        finally:
            session.close()
    
    def combine_summaries(self, summaries):
        """Combine multiple summaries into one comprehensive summary."""
        if not summaries:
            return ""
        
        if len(summaries) == 1:
            return summaries[0]
        
        # Format the summaries with separators
        formatted_content = ""
        for i, summary in enumerate(summaries):
            formatted_content += f"\n{'==='*20}\n{summary}\n{'==='*20}\n\n"
        
        # Create instructions for combining summaries
        instructions = """
You are a newsletter summarization assistant for the LetterMonstr application.
Your task is to combine multiple newsletter summaries into one comprehensive summary.

The summaries below are from different batches of newsletters that have been processed separately.
Please combine these summaries into a single coherent summary that:

1. Eliminates redundancy between the different summaries
2. Organizes information by topic, not by summary batch
3. Preserves all important information from each summary
4. Maintains a clear structure with section headers
5. Keeps all relevant links
6. Improves the overall flow and readability

Please provide a single comprehensive and well-organized summary that combines all of the above information,
eliminating redundancy while preserving all significant content and links.
"""
        
        try:
            # Call Claude API with the combined prompt
            logger.info(f"Combining {len(summaries)} summaries into one")
            combined_prompt = create_claude_prompt(instructions, formatted_content)
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