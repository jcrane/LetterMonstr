"""
Email parser for LetterMonstr application.

This module handles parsing email content and extracting links.
"""

import re
import logging
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime

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
            from sqlalchemy import text
            session.execute(text("PRAGMA busy_timeout = 5000"))  # Set timeout to 5 seconds
            
            # Extract content from email
            content = email_data['content']
            
            # Log content details for debugging
            logger.debug(f"Email content keys: {content.keys() if isinstance(content, dict) else 'not a dict'}")
            logger.debug(f"Email subject: {email_data.get('subject', 'No subject')}")
            logger.debug(f"Email HTML content length: {len(content.get('html', ''))} chars")
            logger.debug(f"Email text content length: {len(content.get('text', ''))} chars")
            
            # Determine which content to use, preferring HTML
            if content.get('html'):
                main_content = self._clean_html(content['html'])
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
                
                # Check if it might be a Gmail forwarded message with different structure
                for key, value in content.items():
                    if isinstance(value, str) and len(value) > len(main_content):
                        main_content = value
                        content_type = 'text' if '<html' not in value.lower() else 'html'
                        logger.debug(f"Found larger content in key '{key}', length: {len(main_content)} chars")
                
                if not main_content:
                    logger.warning(f"No content found in email: {email_data['subject']}")
                    # Still proceed to create an entry but with empty content
                    main_content = f"[No content extracted from email: {email_data['subject']}]"
            
            # Store content in database
            email_id = self._get_email_id(session, email_data['message_id'])
            
            if email_id:
                # Clean HTML content if that's what we have
                if content_type == 'html' and '<html' in main_content.lower():
                    main_content = self._clean_html(main_content)
                
                email_content = EmailContent(
                    email_id=email_id,
                    content_type=content_type,
                    content=main_content
                )
                
                session.add(email_content)
                session.commit()
                
                # Extract and store links
                links = self.extract_links(main_content, content_type)
                self._store_links(session, email_content.id, links)
                
                # Always return the content
                return {
                    'id': email_content.id,
                    'content': main_content,
                    'content_type': content_type,
                    'links': links
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
                        
                        if href and self._is_valid_url(href):
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
            
            # Remove duplicates by URL
            unique_links = []
            seen_urls = set()
            
            for link in links:
                if link['url'] not in seen_urls:
                    seen_urls.add(link['url'])
                    unique_links.append(link)
            
            return unique_links
            
        except Exception as e:
            logger.error(f"Error extracting links: {e}", exc_info=True)
            return []
    
    def _extract_links_with_regex(self, content):
        """Extract links using regular expressions as a fallback."""
        links = []
        # This is a simple regex for URLs, not perfect but functional
        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
        
        try:
            # Ensure content is a string
            if not isinstance(content, str):
                content = str(content) if content is not None else ""
                
            found_urls = re.findall(url_pattern, content)
            
            for url in found_urls:
                if self._is_valid_url(url):
                    links.append({
                        'url': url,
                        'title': url
                    })
            
            return links
        except Exception as e:
            logger.error(f"Error in regex link extraction: {e}", exc_info=True)
            return []
    
    def _clean_html(self, html_content):
        """Clean HTML content by removing scripts, styles, etc. while preserving important content."""
        try:
            # Ensure content is a string
            if not isinstance(html_content, str):
                html_content = str(html_content) if html_content is not None else ""
            
            # Check for common Gmail forwarded email markers
            is_forwarded = False
            # Check if forwarded flag is in the current email data
            email_data = getattr(self, 'current_email_data', {})
            if email_data.get('is_forwarded', False):
                is_forwarded = True
                logger.debug("Detected forwarded email from email data flag")
            # Also check for the marker in the content itself
            elif "---------- Forwarded message ---------" in html_content:
                is_forwarded = True
                logger.debug("Detected Gmail forwarded message marker in HTML")
            
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
            
            # Save a copy of the original soup after basic cleaning for fallback
            cleaned_soup = str(soup)
                
            # Handle Gmail's specific forwarded email format
            if is_forwarded:
                # Gmail typically wraps the forwarded content in a blockquote or div
                # First, try to find the main content area
                main_content = None
                
                # Look for the forwarded content container in Gmail
                # Try several strategies
                
                # Strategy 1: Look for div with specific class related to content
                for div in soup.find_all('div', class_=lambda x: x and ('content' in x.lower())):
                    if len(str(div)) > 200:  # Arbitrary size threshold for meaningful content
                        main_content = div
                        logger.debug("Found main content div with 'content' in class name")
                        break
                
                # Strategy 2: Look for largest div after the forwarded marker
                if not main_content:
                    forwarded_marker = soup.find(string=lambda s: s and "---------- Forwarded message ---------" in s)
                    if forwarded_marker:
                        parent = forwarded_marker.parent
                        # Get the next significant div after the marker
                        next_divs = parent.find_next_siblings('div')
                        if next_divs:
                            largest_div = max(next_divs, key=lambda x: len(str(x)))
                            if len(str(largest_div)) > 200:
                                main_content = largest_div
                                logger.debug("Found main content div after forwarded marker")
                
                # Strategy 3: Look for blockquote which often contains the forwarded content
                if not main_content:
                    blockquotes = soup.find_all('blockquote')
                    if blockquotes:
                        largest_blockquote = max(blockquotes, key=lambda x: len(str(x)))
                        if len(str(largest_blockquote)) > 200:
                            main_content = largest_blockquote
                            logger.debug("Found main content in blockquote")
                
                # Strategy 4: Look for the largest div overall
                if not main_content:
                    divs = soup.find_all('div')
                    if divs:
                        largest_div = max(divs, key=lambda x: len(str(x)))
                        if len(str(largest_div)) > 200:
                            main_content = largest_div
                            logger.debug("Found main content using largest div strategy")
                
                # If we found a main content section, use that instead of the whole document
                if main_content:
                    logger.debug(f"Using extracted main content from forwarded email, size: {len(str(main_content))}")
                    clean_html = str(main_content)
                else:
                    logger.debug("Could not identify main content section in forwarded email")
                    clean_html = cleaned_soup
            else:
                # For non-forwarded emails, preserve more content
                # Check if there's a specific newsletter content area
                newsletter_content = None
                
                # Look for common newsletter content containers
                content_containers = soup.find_all(['div', 'table'], class_=lambda x: x and 
                                                  any(term in (x.lower() if x else '') for term in 
                                                      ['content', 'body', 'article', 'main', 'newsletter']))
                
                if content_containers:
                    # Use the largest content container
                    newsletter_content = max(content_containers, key=lambda x: len(str(x)))
                
                if newsletter_content and len(str(newsletter_content)) > len(cleaned_soup) * 0.4:  # At least 40% of original
                    clean_html = str(newsletter_content)
                    logger.debug(f"Using extracted newsletter content, size: {len(clean_html)}")
                else:
                    # If no suitable content container found, use the entire document
                    clean_html = cleaned_soup
                    logger.debug("Using entire document as content (no specific content area found)")
            
            return clean_html
            
        except Exception as e:
            logger.error(f"Error cleaning HTML: {e}", exc_info=True)
            return html_content
    
    def _is_valid_url(self, url):
        """Check if a URL is valid."""
        if not url:
            return False
        
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
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
    
    def _store_links(self, session, content_id, links):
        """Store extracted links in the database."""
        try:
            for link_data in links:
                link = Link(
                    content_id=content_id,
                    url=link_data['url'],
                    title=link_data['title'],
                    crawled=False
                )
                
                session.add(link)
            
            session.commit()
            
        except Exception as e:
            logger.error(f"Error storing links: {e}", exc_info=True)
            session.rollback() 