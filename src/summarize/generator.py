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
import re

from src.database.models import get_session, Summary, ProcessedContent
from src.summarize.claude_summarizer import create_claude_prompt

logger = logging.getLogger(__name__)

# Define the system prompts for different summary formats
LLM_SYSTEM_PROMPTS = {
    'newsletter': """You are an expert email summarizer that creates concise, informative summaries of newsletter content. 
Extract the key information, insights, and main points from the provided content.
Organize the summary by category or topic, with clear headings.
Be factual, objective, and comprehensive while maintaining brevity.
Include important details, statistics, and quotes when relevant.
Your summary should be well-structured with short paragraphs, bullet points, and clear formatting.
Write in a professional, engaging style that retains the essence of the original content.
""",
    'weekly': """You are an expert email summarizer that creates weekly digests of newsletter content.
Organize the summary by category (Technology, Business, Science, etc) to help the reader quickly find relevant information.
For each item, include a concise description of the main points, key insights, and any important details.
Use clear headings, short paragraphs, and bullet points for readability.
Be factual, objective, and comprehensive while maintaining brevity.
Write in a professional, engaging style that makes complex topics accessible.
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
    
    def generate_summary(self, processed_content, format_preferences=None):
        """Generate a summary of the processed content."""
        logger.info(f"Generating summary for {len(processed_content)} content items")
        
        # Prepare the content for summarization
        prepared_content = self._prepare_content_for_summary(processed_content)
        
        # If there's no content, return an error message
        if prepared_content.startswith("NO CONTENT"):
            logger.error("No content available for summarization")
            return {
                "summary": prepared_content,
                "title": "No Content Available",
                "categories": [],
                "key_points": []
            }
        
        # Log content size
        logger.info(f"Prepared content length: {len(prepared_content)} characters")
        
        # Get summary using LLM
        format_prefs = format_preferences or {}
        summary_format = format_prefs.get('format', 'newsletter')
        
        # Include day of week in prompt if it's a weekly format
        day_context = ""
        if summary_format == 'weekly':
            today = datetime.today()
            day_context = f"Today is {today.strftime('%A, %B %d')}. "
        
        # Generate summary with the LLM
        system_prompt = LLM_SYSTEM_PROMPTS.get(summary_format, LLM_SYSTEM_PROMPTS['newsletter'])
        
        # For weekly summaries, add context about the day
        if summary_format == 'weekly':
            system_prompt = day_context + system_prompt
        
        # Adjust prompt based on content length
        content_length = len(prepared_content)
        token_estimate = content_length // 4  # Rough estimate of tokens
        
        # For very large content, adjust the prompt to request more concise summaries
        if token_estimate > 10000:
            system_prompt += f"\n\nNOTE: You are summarizing a very large amount of content ({content_length} characters). Please be concise and focus on the most important points."
        
        # Create the prompt for Claude
        prompt = self._create_summary_prompt(prepared_content, system_prompt)
        
        # Call Claude API to generate summary
        summary_text = self._call_claude_api(prompt)
        
        # Extract title, categories, and key points
        title, categories, key_points = self._extract_metadata(summary_text)
        
        # Remove any placeholder or assistant-style text
        summary_text = self._clean_summary(summary_text)
        
        # Return the summary and metadata
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
        
        # First pass: Calculate total content length from all sources
        for item in processed_content:
            item_total_length = 0
            
            # If item is a ProcessedContent object, use get_processed_content method to access content
            if hasattr(item, 'get_processed_content'):
                db_item = item.get_processed_content()
                if isinstance(db_item, dict):
                    item = db_item
                elif isinstance(db_item, str) and len(db_item) > 100:
                    # If we got a large string, use it directly as content
                    item = {'content': db_item, 'source': item.source}
            
            # Check main content
            content = item.get('content', '')
            if isinstance(content, str):
                item_total_length += len(content)
            
            # Check for raw HTML content which might be stored directly
            html_content = item.get('html', '')
            if isinstance(html_content, str) and len(html_content) > len(content):
                item_total_length = max(item_total_length, len(html_content))
                # Replace the content with HTML for better processing
                if len(html_content) > 1000:  # Only if it's substantial HTML
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html_content, 'html.parser')
                        text_content = soup.get_text(separator='\n', strip=True)
                        # Use the HTML text if it's longer/better than current content
                        if len(text_content) > len(content):
                            item['content'] = text_content
                            logger.info(f"Extracted {len(text_content)} chars from HTML for item {item.get('source', 'Unknown')}")
                    except Exception as e:
                        logger.warning(f"Error extracting text from HTML: {e}")
            
            # Check original email content
            if 'original_email' in item and isinstance(item['original_email'], dict):
                email_content = item['original_email'].get('content', '')
                if isinstance(email_content, str):
                    item_total_length = max(item_total_length, len(email_content))
                    
                # Also check HTML in original email
                email_html = item['original_email'].get('html', '')
                if isinstance(email_html, str) and len(email_html) > 1000:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(email_html, 'html.parser')
                        email_text = soup.get_text(separator='\n', strip=True)
                        if len(email_text) > len(item.get('content', '')):
                            item['content'] = email_text
                            logger.info(f"Using original email HTML content: {len(email_text)} chars")
                    except Exception as e:
                        logger.warning(f"Error extracting text from email HTML: {e}")
            
            # Check articles
            for article in item.get('articles', []):
                if isinstance(article, dict) and isinstance(article.get('content'), str):
                    article_content = article.get('content', '')
                    item_total_length += len(article_content)
            
            # If this item has meaningful content, count it
            if item_total_length > min_content_length:
                has_meaningful_content = True
                meaningful_items += 1
                total_content_length += item_total_length
        
        if not has_meaningful_content:
            logger.error("No meaningful content found in processed items")
            # Create a clear message about the empty content
            empty_message = "NO MEANINGFUL NEWSLETTER CONTENT TO SUMMARIZE\n\n"
            empty_message += f"Received {len(processed_content)} content items, but none contained meaningful text.\n"
            empty_message += "Content sources:\n"
            for item in processed_content:
                source = item.get('source', 'Unknown')
                content_len = len(item.get('content', '')) if isinstance(item.get('content', ''), str) else 0
                empty_message += f"- {source}: {content_len} characters\n"
            return empty_message
        
        logger.info(f"Found {meaningful_items} meaningful content items with total length of {total_content_length} characters")
        
        # Second pass: Format content for summary
        # Calculate available tokens for each item
        max_tokens = 12000  # Assuming a max of 8000 tokens for Claude
        token_margin = 1000  # Leave some margin for prompt and response
        available_tokens = max_tokens - token_margin
        
        # Rough estimate: 1 token ≈ 4 characters on average
        chars_per_token = 4
        available_chars = available_tokens * chars_per_token
        
        if total_content_length <= available_chars:
            # If total content fits within token limit, include everything
            for item in processed_content:
                # Skip items with no meaningful content
                content = item.get('content', '')
                if not isinstance(content, str) or len(content) < min_content_length:
                    continue
                
                # Format this item
                source = item.get('source', 'Unknown Source')
                formatted_item = f"==== {source} ====\n\n{content}\n\n"
                
                # Add articles if present
                for article in item.get('articles', []):
                    if isinstance(article, dict):
                        article_title = article.get('title', 'Article')
                        article_content = article.get('content', '')
                        if article_content and len(article_content) > min_content_length:
                            formatted_item += f"--- {article_title} ---\n{article_content}\n\n"
                
                formatted_content.append(formatted_item)
        else:
            # Scale down content if it exceeds token limit
            scale_factor = available_chars / total_content_length
            logger.info(f"Scaling content by factor {scale_factor:.2f} to fit token limit")
            
            for item in processed_content:
                # Skip items with no meaningful content
                content = item.get('content', '')
                if not isinstance(content, str) or len(content) < min_content_length:
                    continue
                
                # Calculate scaled length for this item
                item_length = len(content)
                scaled_length = int(item_length * scale_factor)
                
                # Ensure we include at least some of each item
                min_scaled_length = min(500, item_length)
                scaled_length = max(scaled_length, min_scaled_length)
                
                # Truncate content to scaled length
                truncated_content = content[:scaled_length]
                
                # Format this item
                source = item.get('source', 'Unknown Source')
                formatted_item = f"==== {source} ====\n\n{truncated_content}\n\n"
                
                # Scale and add articles if present
                for article in item.get('articles', []):
                    if isinstance(article, dict):
                        article_title = article.get('title', 'Article')
                        article_content = article.get('content', '')
                        
                        if article_content and len(article_content) > min_content_length:
                            article_length = len(article_content)
                            article_scaled_length = int(article_length * scale_factor)
                            article_min_length = min(300, article_length)
                            article_scaled_length = max(article_scaled_length, article_min_length)
                            
                            truncated_article = article_content[:article_scaled_length]
                            formatted_item += f"--- {article_title} ---\n{truncated_article}\n\n"
                
                formatted_content.append(formatted_item)
        
        # Combine all formatted content
        combined_content = "\n".join(formatted_content)
        
        # Log the final content length
        logger.info(f"Prepared content for summary: {len(combined_content)} characters, ~{len(combined_content) // chars_per_token} tokens")
        
        return combined_content
    
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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=prompt['system'],
                messages=[
                    {"role": "user", "content": prompt['user']}
                ]
            )
            
            # Extract the summary from the response
            summary = response.content[0].text
            
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
            return ""
        
        if len(summaries) == 1:
            return summaries[0]
        
        # Format the summaries with separators
        formatted_content = ""
        for i, summary in enumerate(summaries):
            formatted_content += f"\n{'==='*20}\n{summary}\n{'==='*20}\n\n"
        
        try:
            # Call Claude API with the combined prompt
            logger.info(f"Combining {len(summaries)} summaries into one")
            combined_prompt = {
                "system": """You are a newsletter summarization assistant for the LetterMonstr application.
Your task is to combine multiple newsletter summaries into one comprehensive summary.

The summaries below are from different batches of newsletters that have been processed separately.
Please combine these summaries into a single coherent summary that:

1. Eliminates redundancy between the different summaries
2. Organizes information by topic, not by summary batch
3. Preserves all important information from each summary
4. Maintains a clear structure with section headers
5. Keeps all relevant links
6. Improves the overall flow and readability""",
                "user": f"Please combine these newsletter summaries into one comprehensive summary:\n\n{formatted_content}"
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