"""
Email parser for LetterMonstr application.

This module handles parsing email content and extracting links.
"""

import re
import logging
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from src.database.models import get_session, EmailContent, Link

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
            session = get_session(self.db_path)
            
            # Extract content from email
            content = email_data['content']
            
            # Determine which content to use, preferring HTML
            if content['html']:
                main_content = self._clean_html(content['html'])
                content_type = 'html'
            elif content['text']:
                main_content = content['text']
                content_type = 'text'
            else:
                logger.warning(f"No content found in email: {email_data['subject']}")
                return None
            
            # Store content in database
            email_id = self._get_email_id(session, email_data['message_id'])
            
            if email_id:
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
                
                return {
                    'id': email_content.id,
                    'content': main_content,
                    'content_type': content_type,
                    'links': links
                }
            
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
                # Parse HTML content
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
            else:
                # Extract links from text content
                # This is a simple regex for URLs, not perfect but functional
                url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
                found_urls = re.findall(url_pattern, content)
                
                for url in found_urls:
                    if self._is_valid_url(url):
                        links.append({
                            'url': url,
                            'title': url
                        })
            
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
    
    def _clean_html(self, html_content):
        """Clean HTML content by removing scripts, styles, etc."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove unwanted tags
            for tag in soup(['script', 'style', 'meta', 'link']):
                tag.decompose()
            
            # Return the cleaned HTML
            return str(soup)
            
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
            from src.database.models import ProcessedEmail
            
            email = session.query(ProcessedEmail).filter_by(message_id=message_id).first()
            
            if email:
                return email.id
            
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