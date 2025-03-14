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
        """Prepare content for summarization with intelligent token management."""
        formatted_content = []
        
        # Estimate tokens per character (approximation)
        tokens_per_char = 0.25  # A rough estimate: ~4 characters per token for English
        
        # Target maximum tokens for the content portion (leaving room for instructions and other parts)
        max_content_tokens = 180000  # Approximately 180K tokens for Claude 3.7 Sonnet
        
        # Reserve tokens for instructions and overhead
        reserved_tokens = 20000  # Reserve 20K tokens for instructions and other parts
        
        # Available tokens for content
        available_tokens = max_content_tokens - reserved_tokens
        
        # Estimate total content size
        total_chars = sum(len(item.get('content', '')) for item in processed_content)
        estimated_tokens = total_chars * tokens_per_char
        
        logger.info(f"Estimated content size: {total_chars} chars, ~{int(estimated_tokens)} tokens")
        
        # Calculate scaling factor if we need to reduce content
        scaling_factor = 1.0
        if estimated_tokens > available_tokens:
            scaling_factor = available_tokens / estimated_tokens
            logger.warning(f"Content too large, scaling down to {scaling_factor:.2f} of original size")
        
        # Add each content item with scaled sizes
        for item in processed_content:
            # Format basic item information
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
        prompt = f"""
You are a newsletter summarization assistant for the LetterMonstr application.
Your task is to create a COMPREHENSIVE summary of the following newsletter content.

Follow these guidelines:
1. MOST IMPORTANT: Be thorough and comprehensive - include ALL meaningful content, stories, and insights from the source material.
2. Do not omit any significant articles, stories or topics from the newsletters.
3. Focus on factual information and key insights.
4. Remove any redundancy or duplicate information across different sources.
5. Organize information by topic, not by source.
6. Remove any content that appears to be advertising or sponsored.
7. Include important details like dates, statistics, and key findings.
8. Present a balanced view without injecting your own opinions.
9. Use plain text formatting that works well in Gmail and other email clients:
   - Use UPPERCASE for main section headers (e.g., "AI NEWS AND UPDATES")
   - Use CAPITALIZED section titles with underlines using equal signs for subsections (e.g., "Google's Gemma 3 Model" followed by "======================")
   - Use asterisks (*) instead of bullet points
   - Use indentation with spaces (4 spaces) for lists
   - Use clear spacing between sections (double line breaks)
   - Use dividers with dashes (-----) to separate major sections
10. For EACH article or story from the newsletters, include a brief summary - don't skip any articles.
11. Include relevant source links for all articles in plain text format (Source: URL).
12. If you find yourself omitting content due to length, create a separate "ADDITIONAL STORIES" section rather than leaving items out completely.

The summary should be thorough and detailed, prioritizing completeness over brevity.
Make sure to maintain all web links so readers can dive deeper into topics they find interesting.

IMPORTANT: Format the output to be easily readable in a plain-text email client. Do NOT use markdown or HTML formatting.

CONTENT TO SUMMARIZE:
{content}

Please provide a detailed and comprehensive summary of the above content, organized by topic and including ALL significant stories and articles with their relevant source links.
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
            dates = []
            for item in processed_content:
                date_value = item.get('date', datetime.now())
                # Convert string dates to datetime objects
                if isinstance(date_value, str):
                    try:
                        # Try to parse the date string - handle different formats
                        # First try ISO format
                        try:
                            date_value = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                        except ValueError:
                            # If that fails, try a more flexible approach
                            import dateutil.parser
                            date_value = dateutil.parser.parse(date_value)
                        dates.append(date_value)
                    except Exception as e:
                        logger.warning(f"Could not parse date string '{date_value}': {e}")
                        # Use current time as fallback
                        dates.append(datetime.now())
                else:
                    dates.append(date_value)
            
            # Use current time if no valid dates found
            if not dates:
                period_start = period_end = datetime.now()
            else:
                period_start = min(dates)
                period_end = max(dates)
            
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
            
    def combine_summaries(self, summaries):
        """Combine multiple summaries into one comprehensive summary."""
        if not summaries:
            return ""
        
        if len(summaries) == 1:
            return summaries[0]
        
        # Create a prompt to combine the summaries
        combined_prompt = f"""
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

SUMMARIES TO COMBINE:

{'==='*20}
{summaries[0]}
{'==='*20}

{'==='*20}
{summaries[1]}
{'==='*20}

"""
        
        # If there are more than 2 summaries, add them with separators
        if len(summaries) > 2:
            for i in range(2, len(summaries)):
                combined_prompt += f"""
{'==='*20}
{summaries[i]}
{'==='*20}

"""
        
        # Complete the prompt
        combined_prompt += """
Please provide a single comprehensive and well-organized summary that combines all of the above information,
eliminating redundancy while preserving all significant content and links.
"""
        
        try:
            # Call Claude API
            logger.info(f"Combining {len(summaries)} summaries into one")
            combined_summary = self._call_claude_api(combined_prompt)
            return combined_summary
        except Exception as e:
            logger.error(f"Error combining summaries: {e}", exc_info=True)
            # Fallback: just join them with section headers
            fallback = "# COMBINED NEWSLETTER SUMMARY\n\n"
            for i, summary in enumerate(summaries):
                fallback += f"## Batch {i+1} Summary\n\n{summary}\n\n---\n\n"
            return fallback 