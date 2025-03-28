"""
Email parser for LetterMonstr application.

This module handles parsing email content and extracting links.
"""

import re
import uuid
import logging
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime
import time
from sqlalchemy import text

from src.database.models import get_session, EmailContent, Link, ProcessedEmail

logger = logging.getLogger(__name__)

class EmailParser:
    """Parses email content and extracts links."""
    
    def __init__(self):
        """Initialize the parser."""
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'lettermonstr.db')
    
    def parse(self, email_data):
        """Parse the email content and store in the database."""
        try:
            # Store the current email data for reference in other methods
            self.current_email_data = email_data
            
            # Create a session with timeout handling
            session = get_session(self.db_path)
            
            # Use SQLAlchemy text() for raw SQL
            session.execute(text("PRAGMA busy_timeout = 10000"))  # Set timeout to 10 seconds (increased)
            
            # Extract content from email
            content = email_data['content']
            
            # Log content details for debugging
            logger.debug(f"Email content keys: {content.keys() if isinstance(content, dict) else 'not a dict'}")
            logger.debug(f"Email subject: {email_data.get('subject', 'No subject')}")
            logger.debug(f"Email HTML content length: {len(content.get('html', ''))} chars")
            logger.debug(f"Email text content length: {len(content.get('text', ''))} chars")
            
            # Improved forwarded email detection - check multiple indicators
            is_forwarded = False
            subject = email_data.get('subject', '')
            
            # Check various indicators that this might be a forwarded email
            if (subject.startswith('Fwd:') or 
                'forwarded message' in subject.lower() or
                email_data.get('is_forwarded', False) or
                (content.get('html') and "---------- Forwarded message ---------" in content.get('html')) or
                (content.get('html') and "Begin forwarded message:" in content.get('html')) or
                (content.get('text') and "---------- Forwarded message ---------" in content.get('text')) or
                (content.get('text') and "Begin forwarded message:" in content.get('text'))):
                is_forwarded = True
                logger.info(f"Detected forwarded email: {subject}")
            
            # Determine which content to use, preferring HTML for rich content
            if content.get('html'):
                # Pass the is_forwarded flag to _clean_html for specialized processing
                main_content = self._clean_html(content['html'], is_forwarded)
                content_type = 'html'
                logger.debug(f"Using HTML content, cleaned length: {len(main_content)} chars")
            elif content.get('text'):
                main_content = content['text']
                content_type = 'text'
                logger.debug(f"Using text content, length: {len(main_content)} chars")
            else:
                # Try to extract content from other fields in case of different structure
                main_content = ""
                content_type = "text"
                
                # Deep search for content in nested structure
                main_content = self._deep_search_content(content)
                if main_content:
                    content_type = 'text' if '<html' not in main_content.lower() else 'html'
                    logger.debug(f"Found content through deep search, length: {len(main_content)} chars")
                else:
                    logger.warning(f"No content found in email: {email_data['subject']}")
                    # Still proceed to create an entry but with empty content
                    main_content = f"[No content extracted from email: {email_data['subject']}]"
            
            # If this is a forwarded email and content appears to be truncated or very short, 
            # try to extract raw content
            if is_forwarded and len(main_content) < 500:
                logger.info(f"Forwarded email content seems truncated, length: {len(main_content)}")
                
                # Get raw content (might be in different places depending on the email structure)
                raw_content = None
                
                # Try direct content first
                if isinstance(content, dict):
                    if content.get('html') and len(content.get('html', '')) > len(main_content):
                        raw_content = content.get('html')
                    elif content.get('text') and len(content.get('text', '')) > len(main_content):
                        raw_content = content.get('text')
                
                # If no direct content, check if raw_content is available in email_data
                if not raw_content and email_data.get('raw_content'):
                    raw_html = email_data.get('raw_content', {}).get('html', '')
                    raw_text = email_data.get('raw_content', {}).get('text', '')
                    
                    if raw_html and len(raw_html) > len(main_content):
                        raw_content = raw_html
                    elif raw_text and len(raw_text) > len(main_content):
                        raw_content = raw_text
                
                # If we found better raw content, use it
                if raw_content:
                    if '<html' in raw_content.lower():
                        main_content = self._clean_html(raw_content, is_forwarded=True)
                        content_type = 'html'
                    else:
                        main_content = raw_content
                        content_type = 'text'
                    logger.info(f"Used raw content for forwarded email, new length: {len(main_content)}")
            
            # Store content in database
            email_id = self._get_email_id(session, email_data['message_id'])
            
            if email_id:
                # Clean HTML content if that's what we have
                if content_type == 'html' and '<html' in main_content.lower():
                    main_content = self._clean_html(main_content, is_forwarded)
                
                # Final check for meaningful content
                if len(main_content.strip()) < 100 and '[No content extracted' not in main_content:
                    logger.warning(f"Very short content after processing: {len(main_content)} chars")
                    main_content += f"\n[Warning: Original email may have had limited content. Subject: {email_data['subject']}]"
                
                # Log final content size
                logger.info(f"Final content size for email '{email_data.get('subject')}': {len(main_content)} chars")
                
                email_content = self._store_email_content(session, email_id, main_content, content_type, self.extract_links(main_content, content_type))
                
                # Always return the content
                return {
                    'id': email_content.id,
                    'content': main_content,
                    'content_type': content_type,
                    'links': self.extract_links(main_content, content_type)
                }
            else:
                logger.error(f"Could not find email_id for message: {email_data['message_id']}")
                return None
            
        except Exception as e:
            logger.error(f"Error parsing email content: {e}", exc_info=True)
            if 'session' in locals():
                session.rollback()
            return None
        finally:
            if 'session' in locals():
                session.close()
    
    def extract_links(self, content, content_type='html'):
        """Extract links from email content."""
        links = []
        seen_urls = set()  # Track seen URLs to avoid duplicates
        
        try:
            if content_type == 'html':
                try:
                    # Parse HTML content with BeautifulSoup
                    # Add explicit type checking to handle Python 3.13 issues
                    if not isinstance(content, str):
                        content = str(content) if content is not None else ""
                    
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Find all links
                    for a_tag in soup.find_all('a', href=True):
                        href = a_tag['href'].strip()
                        text = a_tag.get_text().strip()
                        
                        # Skip mailto links
                        if href.startswith('mailto:'):
                            continue
                            
                        # Skip image links
                        if href.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
                            continue
                        
                        # Accept any http/https URL
                        if href.startswith('http') or href.startswith('https') or href.startswith('www'):
                            if href not in seen_urls:
                                seen_urls.add(href)
                                links.append({
                                    'url': href,
                                    'title': text if text else href
                                })
                except Exception as bs_error:
                    logger.error(f"BeautifulSoup HTML parsing failed: {bs_error}")
                    # Fall back to regex extraction
                    links.extend(self._extract_links_with_regex(content))
            else:
                # Extract links from text content using regex
                links = self._extract_links_with_regex(content)
            
            # If we haven't found any links, try harder with more permissive regex
            if not links:
                logger.info("No links found with standard methods, trying more aggressive extraction")
                # Look for anything that could be a URL in the text
                text_content = soup.get_text() if 'soup' in locals() else content
                url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+'
                urls = re.findall(url_pattern, text_content)
                
                for url in urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        links.append({
                            'url': url,
                            'title': url
                        })
                
                if links:
                    logger.info(f"Found {len(links)} links using aggressive extraction")
            
            return links
            
        except Exception as e:
            logger.error(f"Error extracting links: {e}", exc_info=True)
            return []
    
    def _extract_links_with_regex(self, content):
        """Extract links using regular expressions as a fallback."""
        links = []
        seen_urls = set()
        
        # More comprehensive URL pattern - catches more variants
        url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+'
        
        try:
            # Ensure content is a string
            if not isinstance(content, str):
                content = str(content) if content is not None else ""
                
            found_urls = re.findall(url_pattern, content)
            
            for url in found_urls:
                # Clean up URL - remove trailing punctuation that might be included
                url = url.rstrip(',.;:\'\"!?)')
                
                # Skip image links
                if url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg')):
                    continue
                
                # Normalize the URL
                if url.startswith('www.'):
                    url = 'http://' + url
                
                if url not in seen_urls:
                    seen_urls.add(url)
                    links.append({
                        'url': url,
                        'title': url
                    })
            
            return links
        except Exception as e:
            logger.error(f"Error in regex link extraction: {e}", exc_info=True)
            return []
    
    def _clean_html(self, html_content, is_forwarded=False):
        """Clean HTML content by removing scripts, styles, etc. while preserving important content."""
        try:
            # Ensure content is a string
            if not isinstance(html_content, str):
                html_content = str(html_content) if html_content is not None else ""
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove definitely unwanted tags that don't contain content
            for tag in soup(['script', 'style', 'meta', 'link']):
                tag.decompose()
            
            # Instead of removing header/footer elements, look for specific non-content indicators
            # This is more conservative to avoid removing important content
            for tag in soup.find_all(class_=lambda x: x and any(term in x.lower() for term in 
                                                              ['unsubscribe', 'disclaimer', 'preference-center'])):
                tag.decompose()
            
            # Be more selective with marketing elements to avoid removing actual content
            marketing_terms = ['advertisement', 'sponsor', 'promotion', 'marketing-banner']
            for tag in soup.find_all(class_=lambda x: x and any(term in x.lower() for term in marketing_terms)):
                tag.decompose()
            
            # Save a copy of the original soup after basic cleaning
            cleaned_soup = str(soup)
            
            if is_forwarded:
                # ===== SIMPLIFIED FORWARDED EMAIL HANDLING =====
                # Keep ALL content from forwarded emails to ensure we don't miss any links
                logger.info("Using simplified forwarded email handling - preserving all content")
                
                # Use the entire cleaned HTML content
                clean_html = cleaned_soup
                
                # Log the content size
                logger.info(f"Using full forwarded content, size: {len(clean_html)} chars")
            else:
                # For regular (non-forwarded) emails
                # Try to find the main content container - typically a large div or table
                content_containers = []
                
                # Look for common newsletter content containers
                for container in soup.find_all(['div', 'table', 'td']):
                    # Skip tiny containers
                    if len(str(container)) < 200:
                        continue
                        
                    # Check if it's a potential content container by looking for paragraphs, links, or headers
                    if container.find_all(['p', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                        # Weight by content length and number of content elements
                        content_elements = len(container.find_all(['p', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']))
                        if content_elements > 5:  # Arbitrary threshold for "meaningful" content
                            content_containers.append(container)
                
                if content_containers:
                    # Get the container with most content
                    newsletter_content = max(content_containers, key=lambda x: len(str(x)))
                    
                    if newsletter_content and len(str(newsletter_content)) > len(html_content) * 0.3:  # At least 30% of original
                        clean_html = str(newsletter_content)
                        logger.debug(f"Using extracted newsletter content, size: {len(clean_html)}")
                    else:
                        # If no suitable content container found, use the entire document
                        clean_html = cleaned_soup
                        logger.debug("Using entire document as content (no large enough specific content area found)")
                else:
                    # Fallback to entire document
                    clean_html = cleaned_soup
                    logger.debug("Using entire document as content (no content containers found)")
            
            # Final cleaning on the selected content
            final_soup = BeautifulSoup(clean_html, 'html.parser')
            
            # Remove some common non-content elements that might still be present
            for selector in [
                '[role="footer"]', 
                '[class*="footer"]',
                '[id*="footer"]',
                '[role="header"]',
                '[class*="header"]',
                '[id*="header"]',
                # Add more selectors as needed
            ]:
                for element in final_soup.select(selector):
                    element.decompose()
            
            # Convert back to string
            clean_html = str(final_soup)
            
            # Return the cleaned HTML
            return clean_html
        except Exception as e:
            logger.error(f"Error cleaning HTML: {e}", exc_info=True)
            return html_content  # Return original if cleaning fails
    
    def _is_valid_url(self, url):
        """Check if a URL is valid."""
        if not url:
            return False
        
        # Accept "www." URLs too
        if url.startswith('www.'):
            url = 'http://' + url
        
        try:
            result = urlparse(url)
            # More permissive URL validation
            return (result.scheme in ['http', 'https'] and result.netloc) or (not result.scheme and result.netloc.startswith("www."))
        except:
            return False
    
    def _get_email_id(self, session, message_id):
        """Get the database ID for a processed email."""
        try:
            # First check if we already have the DB ID in the email data
            # This would be set by the main.py process before calling parse
            email_data = getattr(self, 'current_email_data', None)
            if email_data and 'db_id' in email_data:
                logger.debug(f"Using provided DB ID: {email_data['db_id']}")
                return email_data['db_id']
            
            # Otherwise query the database by message_id
            from src.database.models import ProcessedEmail
            
            email = session.query(ProcessedEmail).filter_by(message_id=message_id).first()
            
            if email:
                return email.id
                
            # Special handling for forwarded emails which might not be in the database yet
            if email_data and 'subject' in email_data and email_data['subject'].startswith('Fwd:'):
                # For forwarded emails, we need to create a ProcessedEmail record first
                logger.info(f"Creating new ProcessedEmail record for forwarded email: {email_data['subject']}")
                try:
                    new_email = ProcessedEmail(
                        message_id=message_id,
                        subject=email_data.get('subject', ''),
                        sender=email_data.get('sender', ''),
                        date_received=email_data.get('date', datetime.now()),
                        date_processed=datetime.now()
                    )
                    session.add(new_email)
                    session.flush()  # Get ID without committing
                    logger.info(f"Created ProcessedEmail record with ID {new_email.id}")
                    return new_email.id
                except Exception as e:
                    logger.error(f"Failed to create ProcessedEmail record: {e}")
                    # Continue with normal flow
            
            logger.warning(f"Could not find email ID for message: {message_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting email ID: {e}", exc_info=True)
            return None
    
    def _store_email_content(self, session, email_id, content, content_type, links):
        """Store email content in the database with better transaction handling."""
        # Use a specific retry pattern for database operations to handle locks
        max_retries = 5
        retry_delay = 2  # seconds
        
        for attempt in range(max_retries):
            try:
                # Create the email content record
                email_content = EmailContent(
                    email_id=email_id,
                    content_type=content_type,
                    content=content
                )
                
                session.add(email_content)
                session.flush()  # Flush to get the ID but don't commit yet
                
                # Store links if any
                if links:
                    for link in links:
                        link_obj = Link(
                            content_id=email_content.id,
                            url=link.get('url', ''),
                            title=link.get('title', '')
                        )
                        session.add(link_obj)
                
                # Explicitly commit the transaction
                session.commit()
                logger.info(f"Successfully stored email content with ID {email_content.id}, size: {len(content)} chars")
                return email_content
            except Exception as e:
                # Handle specific lock errors
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Database lock detected, retry {attempt+1}/{max_retries} after {retry_delay}s delay")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    if hasattr(session, 'rollback'):
                        session.rollback()
                    continue
                else:
                    # For other errors or if we've exhausted retries, log and re-raise
                    logger.error(f"Error storing email content after {attempt+1} attempts: {e}")
                    if hasattr(session, 'rollback'):
                        session.rollback()
                    raise
        
        # If we get here, we've exhausted retries
        logger.error(f"Failed to store email content after {max_retries} attempts")
        return None
    
    def _deep_search_content(self, data, depth=0, max_depth=5):
        """Recursively search for the largest text content in a nested structure."""
        if depth > max_depth:
            return ""
        
        if isinstance(data, str):
            return data
        
        best_content = ""
        
        if isinstance(data, dict):
            # First check common content keys
            for key in ['html', 'text', 'content', 'body']:
                if key in data and isinstance(data[key], str) and len(data[key]) > len(best_content):
                    best_content = data[key]
                
            # Then search all keys
            for key, value in data.items():
                content = self._deep_search_content(value, depth + 1, max_depth)
                if len(content) > len(best_content):
                    best_content = content
                
        elif isinstance(data, list):
            for item in data:
                content = self._deep_search_content(item, depth + 1, max_depth)
                if len(content) > len(best_content):
                    best_content = content
                
        return best_content 