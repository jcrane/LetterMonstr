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

from src.database.models import get_session, Summary

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
            self._store_summary(summary_text, processed_content)
            
            return summary_text
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}", exc_info=True)
            return "Error generating summary. Please check logs for details."
    
    def _prepare_content_for_summary(self, processed_content):
        """Prepare content for summarization."""
        formatted_content = []
        
        # Add each content item
        for item in processed_content:
            # Format basic item information
            item_text = f"SOURCE: {item.get('source', 'Unknown')}\n"
            item_text += f"DATE: {item.get('date', datetime.now()).strftime('%Y-%m-%d')}\n"
            
            # Add source URLs if available
            email_content = item.get('original_email', {})
            source_links = []
            
            # Check if there's a web version link in the email
            if isinstance(email_content, dict) and 'links' in email_content:
                for link in email_content.get('links', []):
                    # Look for typical "View in browser" or "Web version" links
                    title = link.get('title', '').lower()
                    url = link.get('url', '')
                    if url and ('web' in title or 'browser' in title or 'view' in title):
                        source_links.append(f"WEB VERSION: {url}")
                        break
            
            # Add article URLs
            articles = item.get('articles', [])
            for article in articles:
                article_url = article.get('url', '')
                article_title = article.get('title', '')
                if article_url and article_title:
                    source_links.append(f"ARTICLE: {article_title} - {article_url}")
            
            # Add source links to the content
            if source_links:
                item_text += "\nSOURCE LINKS:\n" + "\n".join(source_links) + "\n"
            
            item_text += "\n"
            
            # If this is a merged item, include all sources
            if item.get('is_merged', False) and 'sources' in item:
                item_text += f"MERGED FROM SOURCES: {', '.join(item['sources'])}\n\n"
            
            # Add main content
            # If the content is very long, we'll truncate it to not exceed token limits
            content = item.get('content', '')
            max_content_chars = 15000  # Arbitrary limit to avoid excessive tokens
            if len(content) > max_content_chars:
                content = content[:max_content_chars] + "... [CONTENT TRUNCATED]"
            
            item_text += f"CONTENT:\n{content}\n\n"
            
            # Add to formatted content
            formatted_content.append(item_text)
        
        # Join all items with a separator
        return "\n\n" + "-" * 50 + "\n\n".join(formatted_content)
    
    def _create_summary_prompt(self, content):
        """Create a prompt for Claude to generate a summary."""
        prompt = f"""
You are a newsletter summarization assistant for the LetterMonstr application.
Your task is to create a clear, concise summary of the following newsletter content.

Follow these guidelines:
1. Focus on factual information and key insights.
2. Remove any redundancy or duplicate information across different sources.
3. Organize information by topic, not by source.
4. Remove any content that appears to be advertising or sponsored.
5. Include important details like dates, statistics, and key findings.
6. Present a balanced view without injecting your own opinions.
7. Use bullet points for clarity where appropriate.
8. IMPORTANT: Include relevant source links in your summary, especially for articles or newsletter web versions.
9. Format the links in a way that will be clickable in an HTML email (use markdown style links like [Title](URL)).
10. For each major topic or article you summarize, try to include a relevant link where the reader can learn more.

The summary should be comprehensive yet concise, focusing on the most important information.
Make sure to maintain all web links so readers can dive deeper into topics they find interesting.

CONTENT TO SUMMARIZE:
{content}

Please provide a well-structured summary of the above content, organized by topic and including relevant source links.
"""
        return prompt
    
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
        """Store the generated summary in the database."""
        try:
            # Calculate period start and end dates
            dates = [item.get('date', datetime.now()) for item in processed_content]
            period_start = min(dates) if dates else datetime.now()
            period_end = max(dates) if dates else datetime.now()
            
            # Determine summary type based on timespan
            days_span = (period_end - period_start).days
            if days_span <= 1:
                summary_type = 'daily'
            elif days_span <= 7:
                summary_type = 'weekly'
            else:
                summary_type = 'monthly'
            
            # Create summary entry
            session = get_session(self.db_path)
            
            try:
                summary = Summary(
                    period_start=period_start,
                    period_end=period_end,
                    summary_type=summary_type,
                    summary_text=summary_text,
                    creation_date=datetime.now(),
                    sent=False
                )
                
                session.add(summary)
                session.commit()
                
                logger.info(f"Stored {summary_type} summary in database")
                
            except Exception as e:
                session.rollback()
                logger.error(f"Error storing summary: {e}", exc_info=True)
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error in _store_summary: {e}", exc_info=True) 