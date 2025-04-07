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
        """Parse email content and extract links.
        
        This method parses email content, detects forwarded emails,
        extracts the content and links, and returns a structured result.
        
        Args:
            email_data (dict): Email data from the fetcher.
            
        Returns:
            dict: Parsed content with extracted links.
        """
        session = get_session(self.db_path)
        
        try:
            if not email_data:
                logger.warning("Empty email data provided to parser")
                return None
                
            # Ensure we have a title/subject
            if 'subject' not in email_data or not email_data['subject']:
                email_data['subject'] = "No Subject"
                
            subject = email_data.get('subject', '')
            
            # Initialize content fields
            email_data['content'] = None
            email_data['html_content'] = None
            email_data['text_content'] = None
            
            # Check if this is a forwarded email
            is_forwarded = False
            forwarded_markers = ['Fwd:', 'FW:', 'Forwarded:']
            
            if any(marker in subject for marker in forwarded_markers):
                is_forwarded = True
                logger.info(f"Detected forwarded email: {subject}")
                email_data['is_forwarded'] = True
            
            # For forwarded emails, prioritize raw_email content
            if is_forwarded:
                content = email_data.get('content', {})
                
                # First check if we have raw_email directly in the content
                raw_email = None
                
                if isinstance(content, dict) and 'raw_email' in content:
                    raw_email = content['raw_email']
                    logger.info(f"Found raw_email in content dictionary: {len(raw_email)} chars")
                elif isinstance(content, dict) and 'raw_message' in content:
                    raw_email = content['raw_message']
                    logger.info(f"Found raw_message in content dictionary: {len(raw_email)} chars")
                elif 'raw_email' in email_data:
                    raw_email = email_data['raw_email']
                    logger.info(f"Found raw_email in email_data: {len(raw_email)} chars")
                elif 'raw_message' in email_data:
                    raw_email = email_data['raw_message']
                    logger.info(f"Found raw_message in email_data: {len(raw_email)} chars")
                
                # If we found raw email content, process it directly
                if raw_email and len(raw_email) > 500:
                    # Extract content from raw email
                    extracted_content = self._extract_forwarded_content(raw_email)
                    
                    if extracted_content and len(extracted_content) > 200:
                        logger.info(f"Successfully extracted {len(extracted_content)} chars from raw forwarded email")
                        email_data['content'] = extracted_content
                        content_type = 'html' if '<html' in extracted_content.lower() else 'text'
                        email_data['content_type'] = content_type
                        email_data['links'] = self.extract_links(extracted_content, content_type)
                        return email_data
            
            # If we couldn't process raw email or this isn't a forwarded email, continue with normal parsing
            
            # Extract the message body
            message_body = None
            content = email_data.get('content', {})
            
            # Try to get content from multiple sources
            if 'html' in email_data and email_data['html']:
                html_content = email_data['html']
                
                # Clean the HTML
                cleaned_html = self._clean_html(html_content, is_forwarded=is_forwarded, subject=subject)
                
                if cleaned_html:
                    message_body = cleaned_html
                    email_data['html_content'] = cleaned_html
            
            # If we don't have HTML or cleaned HTML is empty, try text
            if not message_body and 'text' in email_data and email_data['text']:
                text_content = email_data['text']
                
                # Clean the text
                cleaned_text = self._clean_text(text_content)
                
                if cleaned_text:
                    message_body = cleaned_text
                    email_data['text_content'] = cleaned_text
            
            # If we have original_full_message and the content is short, try to extract from there
            if (not message_body or (message_body and len(message_body) < 200)) and 'original_full_message' in email_data:
                logger.info("Using original_full_message as content source")
                full_message = email_data['original_full_message']
                
                # Extract content from the full message
                extracted_content = self._extract_content_from_full_message(full_message, is_forwarded)
                
                if extracted_content and (not message_body or len(extracted_content) > len(message_body)):
                    message_body = extracted_content
                    logger.info(f"Extracted better content from original_full_message, length: {len(message_body)}")
            
            # If we still don't have content, check raw_content
            if (not message_body or (message_body and len(message_body) < 200)) and 'raw_content' in email_data:
                logger.info("Using raw_content as content source")
                raw_content = email_data['raw_content']
                
                # Extract content from raw content
                extracted_content = self._extract_content_from_raw(raw_content, is_forwarded)
                
                if extracted_content and (not message_body or len(extracted_content) > len(message_body)):
                    message_body = extracted_content
                    logger.info(f"Extracted better content from raw_content, length: {len(message_body)}")
                    
            # Special handling for forwarded emails
            if is_forwarded:
                logger.info("Applying special forwarded email handling")
                
                # Try to get raw message if available
                if 'raw_message' in email_data:
                    logger.info("Extracting content from raw_message for forwarded email")
                    forwarded_content = self._extract_forwarded_content(email_data['raw_message'])
                    
                    if forwarded_content and len(forwarded_content) > 200:
                        message_body = forwarded_content
                        logger.info(f"Extracted content from raw_message for forwarded email, length: {len(message_body)}")
                
                # Check for forwarded_html in content dictionary
                if isinstance(content, dict) and 'forwarded_html' in content:
                    forwarded_html = content['forwarded_html']
                    if forwarded_html and len(forwarded_html) > 200:
                        message_body = forwarded_html
                        logger.info(f"Using forwarded_html from content dictionary, length: {len(message_body)}")
                
                # If we still don't have good content for forwarded email, try deep search
                if not message_body or len(message_body) < 200:
                    logger.info("Attempting deep search for forwarded email content")
                    deep_search_content = self._deep_search_content(email_data, is_forwarded=True)
                    
                    if deep_search_content and (not message_body or len(deep_search_content) > len(message_body)):
                        message_body = deep_search_content
                        logger.info(f"Found better content through deep search, length: {len(message_body)}")
            
            # Final check for content length
            if not message_body or len(message_body) < 50:
                logger.warning(f"No substantial content found in email: {subject}")
                
                # Try to combine all available content sources
                all_content = []
                
                # Add HTML content if available
                if email_data.get('html_content'):
                    all_content.append(self._extract_text_from_html(email_data['html_content']))
                
                # Add text content if available
                if email_data.get('text_content'):
                    all_content.append(email_data['text_content'])
                
                # Add any content from the content dictionary
                if isinstance(content, dict):
                    for key, value in content.items():
                        if isinstance(value, str) and len(value) > 50:
                            if '<html' in value.lower():
                                all_content.append(self._extract_text_from_html(value))
                            else:
                                all_content.append(value)
                
                # Combine all content
                if all_content:
                    message_body = "\n\n".join(all_content)
                    logger.info(f"Combined content from multiple sources: {len(message_body)} chars")
                else:
                    # Create a minimal content if nothing was found
                    message_body = f"Email '{subject}' with no extractable content."
            
            # Extract links from content
            links = []
            if message_body and len(message_body) > 50:
                # Determine content type (HTML or text)
                content_type = 'html' if '<html' in message_body.lower() or '<div' in message_body.lower() else 'text'
                links = self.extract_links(message_body, content_type)
                logger.info(f"Extracted {len(links)} links from email content")
            
            # Store the final content
            email_data['content'] = message_body
            email_data['content_type'] = 'html' if '<html' in message_body.lower() or '<div' in message_body.lower() else 'text'
            email_data['links'] = links
            
            return email_data
        
        except Exception as e:
            logger.error(f"Error parsing email: {e}", exc_info=True)
            return None
        finally:
            if session:
                session.close()
    
    def _clean_html(self, html_content, is_forwarded=False, subject=''):
        """Clean and process HTML content"""
        if not html_content or not isinstance(html_content, str):
            return ""
        
        # Special handling for emails with emojis or specific subjects
        if '🤖' in subject or 'AI Risk Curve' in subject or 'CoreWeave IPO' in subject:
            logger.info(f"Applying special HTML cleaning for emoji email: {subject}")
            
            # Look for substantial content blocks in divs
            import re
            content_blocks = re.findall(r'<div[^>]*>(.*?)</div>', html_content, re.DOTALL)
            if content_blocks:
                # Find the largest content block
                largest_block = max(content_blocks, key=len)
                if len(largest_block) > 200:  # Only use if substantial
                    logger.info(f"Found large content block in HTML: {len(largest_block)} chars")
                    return f"<div>{largest_block}</div>"
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script, style, and header tags
            for tag in soup(['script', 'style', 'header']):
                tag.decompose()
            
            # Remove common email footer elements
            for element in soup.select('.footer, .email-footer, .unsubscribe, [id*="footer"], [class*="footer"]'):
                element.decompose()
            
            # Special handling for forwarded emails
            if is_forwarded:
                # Handle Gmail forwarded emails specifically
                gmail_quote = soup.select_one('.gmail_quote')
                if gmail_quote:
                    logger.info("Found Gmail quote section")
                    # Extract just the forwarded content
                    return str(gmail_quote)
                
                # Find forwarded content in HTML
                forwarded_div = None
                
                # Look for divs with forwarded markers
                for div in soup.find_all('div'):
                    if div.get_text() and any(marker in div.get_text().lower() for marker in ["forwarded message", "begin forwarded", "original message"]):
                        # Take the parent of this div which likely contains the full forwarded content
                        forwarded_div = div.parent
                        break
                    
                # If found a specific forwarded section, extract just that
                if forwarded_div:
                    logger.info("Found forwarded message section")
                    return str(forwarded_div)
            
            # If we reach here, clean up the whole document
            # Remove classes commonly used for quotations or footers
            for element in soup.select('[class*="quote"], [class*="signature"]'):
                element.decompose()
            
            # If this is a forwarded email but we couldn't find forwarded content yet, look for tables
            # (some email clients format forwarded content in tables)
            if is_forwarded:
                tables = soup.find_all('table')
                if tables:
                    # Often the largest table contains the forwarded content
                    largest_table = max(tables, key=lambda t: len(str(t)))
                    if len(str(largest_table)) > 200:  # Only use if substantial
                        return str(largest_table)
                
            # Return the full cleaned body
            if soup.body:
                return str(soup.body)
            else:
                return str(soup)
            
        except Exception as e:
            logger.exception(f"Error cleaning HTML: {e}")
            return html_content  # Return original if cleaning fails
    
    def _deep_search_content(self, email_data, is_forwarded=False, depth=0, max_depth=5):
        """Deep search for content in the email data structure.
        
        This method recursively searches through the email data structure
        to find the most substantial content.
        
        Args:
            email_data (dict): The email data to search
            is_forwarded (bool): Whether this is a forwarded email
            depth (int): Current recursion depth
            max_depth (int): Maximum recursion depth
            
        Returns:
            str: The best content found in the email data
        """
        if depth > max_depth or not email_data:
            return ""
            
        # Track the best content found so far
        best_content = ""
        
        # Check all the common content fields for forwarded emails
        if is_forwarded:
            # Check forward-specific fields
            if 'raw_message' in email_data and isinstance(email_data['raw_message'], (str, bytes)):
                content = self._extract_forwarded_content(email_data['raw_message'])
                if content and len(content) > len(best_content):
                    logger.info(f"Found better content in raw_message field: {len(content)} chars")
                    best_content = content
            
            # Check for original message in different fields
            for field in ['original_message', 'original_content', 'forward_content', 'message']:
                if field in email_data and isinstance(email_data[field], (str, bytes)):
                    content = self._extract_forwarded_content(email_data[field])
                    if content and len(content) > len(best_content):
                        logger.info(f"Found better content in {field} field: {len(content)} chars")
                        best_content = content
        
        # Process content field if it's a dictionary
        content_dict = email_data.get('content', {})
        if isinstance(content_dict, dict):
            # Check HTML content
            if 'html' in content_dict and content_dict['html']:
                html_content = content_dict['html']
                
                # Process HTML content based on whether it's a forwarded email
                cleaned_html = self._clean_html(html_content, is_forwarded=is_forwarded)
                if cleaned_html and len(cleaned_html) > len(best_content):
                    logger.info(f"Found better content in content.html field: {len(cleaned_html)} chars")
                    best_content = cleaned_html
            
            # Check text content
            if 'text' in content_dict and content_dict['text']:
                text_content = content_dict['text']
                
                # Clean the text content
                cleaned_text = self._clean_text(text_content)
                if cleaned_text and len(cleaned_text) > len(best_content):
                    logger.info(f"Found better content in content.text field: {len(cleaned_text)} chars")
                    best_content = cleaned_text
            
            # Recursively search in the content dictionary
            deep_content = self._deep_search_content_recursive(content_dict, depth + 1, max_depth)
            if deep_content and len(deep_content) > len(best_content):
                logger.info(f"Found better content through recursive search in content dictionary: {len(deep_content)} chars")
                best_content = deep_content
        
        # Check direct content fields
        elif 'content' in email_data and isinstance(email_data['content'], str):
            content = email_data['content']
            if content and len(content) > len(best_content):
                logger.info(f"Found content in direct content field: {len(content)} chars")
                best_content = content
        
        # Check HTML and text fields
        for field in ['html', 'text', 'body', 'html_content', 'text_content']:
            if field in email_data and isinstance(email_data[field], str):
                content = email_data[field]
                
                # Process content based on type
                if 'html' in field:
                    content = self._clean_html(content, is_forwarded=is_forwarded)
                else:
                    content = self._clean_text(content)
                
                if content and len(content) > len(best_content):
                    logger.info(f"Found better content in {field} field: {len(content)} chars")
                    best_content = content
        
        # Try recursive search on all dictionary fields
        for key, value in email_data.items():
            # Skip already processed fields
            if key in ['content', 'html', 'text', 'raw_message', 'original_message']:
                continue
                
            if isinstance(value, dict):
                deep_content = self._deep_search_content_recursive(value, depth + 1, max_depth)
                if deep_content and len(deep_content) > len(best_content):
                    logger.info(f"Found better content through recursive search in {key}: {len(deep_content)} chars")
                    best_content = deep_content
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, (dict, list)):
                        deep_content = self._deep_search_content_recursive(item, depth + 1, max_depth)
                        if deep_content and len(deep_content) > len(best_content):
                            logger.info(f"Found better content through recursive search in {key} list item: {len(deep_content)} chars")
                            best_content = deep_content
        
        # If we found substantial content, return it
        if best_content and len(best_content) > 200:
            return best_content
            
        # If the content is very short, add an informative message
        if not best_content or len(best_content) < 50:
            subject = email_data.get('subject', 'Unknown Subject')
            return f"No substantial content found in forwarded email: {subject}"
            
        return best_content
    
    def _deep_search_content_recursive(self, data, depth=0, max_depth=5):
        """Recursively search through nested structures for meaningful content."""
        # Guard against excessive recursion
        if depth > max_depth:
            return ""
        
        # Handle different data types
        if isinstance(data, dict):
            # Look for likely content fields in dictionaries
            for key in ['content', 'body', 'message', 'text', 'html']:
                if key in data:
                    value = data[key]
                    if isinstance(value, str) and len(value) > 100:
                        return value  # Found substantial content
                    content = self._deep_search_content_recursive(value, depth + 1, max_depth)
                    if content:
                        return content
            
            # If no specific key found, search all dictionary values
            for value in data.values():
                content = self._deep_search_content_recursive(value, depth + 1, max_depth)
                if content:
                    return content
                    
        elif isinstance(data, list):
            # For lists, search each item
            for item in data:
                content = self._deep_search_content_recursive(item, depth + 1, max_depth)
                if content:
                    return content
                    
        elif isinstance(data, str) and len(data) > 100:
            # If it's a substantial string, it might be content
            return data
            
        # No content found
        return ""
    
    def _extract_text_from_html(self, html_content):
        """Extract readable text from HTML content"""
        if not html_content:
            return ""
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Get text while preserving some structure
            text = ""
            for element in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']):
                if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    # Add headings with emphasis
                    text += element.get_text(strip=True) + "\n\n"
                else:
                    # Add regular paragraphs
                    element_text = element.get_text(strip=True)
                    if element_text:  # Only add non-empty elements
                        text += element_text + "\n\n"
            
            # If we couldn't extract structured text, fall back to all text
            if not text:
                text = soup.get_text()
            
            return text.strip()
        except Exception as e:
            logger.exception(f"Error extracting text from HTML: {e}")
            # Fallback to a simple tag removal if BeautifulSoup fails
            import re
            text = re.sub(r'<[^>]*>', ' ', html_content)
            return re.sub(r'\s+', ' ', text).strip()
    
    def _process_single_email(self, message_id, message_data, gmail_service=None):
        """Process a single email from Gmail API response."""
        try:
            email_data = {}
            
            # Extract headers
            headers = message_data.get('payload', {}).get('headers', [])
            for header in headers:
                name = header.get('name', '').lower()
                value = header.get('value', '')
                
                if name == 'subject':
                    email_data['subject'] = value
                elif name == 'from':
                    email_data['from'] = value
                elif name == 'to':
                    email_data['to'] = value
                elif name == 'date':
                    email_data['date'] = value
                
            # Get parts from payload
            payload = message_data.get('payload', {})
            
            # Initialize content variables
            html_content = ""
            text_content = ""
            
            # Check for forwarded emails specifically
            email_data['is_forwarded'] = False
            
            subject = email_data.get('subject', '')
            if subject and any(marker in subject.lower() for marker in ["fwd:", "fw:", "forwarded"]):
                email_data['is_forwarded'] = True
                logger.info(f"Detected forwarded email: {subject}")
            
            # Special handling for emails with emoji or specific problematic subjects
            needs_original_message = False
            if subject and ('🤖' in subject or '💹' in subject or 'AI Risk Curve' in subject or 'CoreWeave IPO' in subject):
                logger.info(f"Processing special format email: {subject}")
                needs_original_message = True
            
            # Always get the full raw message for problematic emails
            if needs_original_message or email_data['is_forwarded']:
                if gmail_service:
                    try:
                        # Get the full raw message
                        full_message = gmail_service.users().messages().get(
                            userId='me', id=message_id, format='raw'
                        ).execute()
                        
                        import base64
                        raw_email_bytes = base64.urlsafe_b64decode(full_message['raw'])
                        raw_email_string = raw_email_bytes.decode('utf-8', errors='replace')
                        
                        email_data['original_full_message'] = raw_email_string
                        logger.info(f"Retrieved original full message, length: {len(raw_email_string)}")
                    except Exception as e:
                        logger.error(f"Error getting original message: {e}")
            
            # Process parts recursively
            if 'parts' in payload:
                self._process_parts(payload['parts'], email_data)
            else:
                # Handle single part messages
                mime_type = payload.get('mimeType', '')
                body_data = payload.get('body', {}).get('data', '')
                
                if body_data:
                    decoded_data = self._decode_base64(body_data)
                    
                    if 'text/html' in mime_type:
                        html_content = decoded_data
                    elif 'text/plain' in mime_type:
                        text_content = decoded_data
                
                email_data['html_content'] = html_content
                email_data['text_content'] = text_content
            
            # Parse content
            return self.parse(email_data)
            
        except Exception as e:
            logger.exception(f"Error processing email {message_id}: {e}")
            return {'error': str(e)}
    
    def extract_links(self, content, content_type='html'):
        """Extract links from content."""
        links = []
        
        try:
            if content_type.lower() == 'html':
                # Parse HTML and extract links
                soup = BeautifulSoup(content, 'html.parser')
                
                # Find all anchor tags
                for a_tag in soup.find_all('a'):
                    # Extract URL
                    url = a_tag.get('href', '')
                    
                    # Skip empty URLs
                    if not url:
                        continue
                    
                    # Skip invalid URLs
                    if not self._is_valid_url(url):
                        continue
                    
                    # Extract title from the anchor text
                    title = a_tag.get_text(strip=True)
                    
                    # If no title, try the title attribute
                    if not title:
                        title = a_tag.get('title', '')
                    
                    # If still no title, use "Link" as placeholder
                    if not title:
                        title = "Link"
                    
                    # Check if this is a tracking URL
                    is_tracking = self._is_tracking_url(url)
                    
                    # Add to links list
                    links.append({
                        'url': url,
                        'title': title,
                        'source': 'html',
                        'is_tracking': is_tracking,  # Flag tracking URLs for later resolution
                        'original_url': url          # Store the original URL regardless
                    })
            else:
                # For plain text, use regex to extract URLs
                links = self._extract_links_with_regex(content)
                
                # Flag tracking URLs in plain text links too
                for link in links:
                    url = link.get('url', '')
                    link['is_tracking'] = self._is_tracking_url(url)
                    link['original_url'] = url
            
            # Deduplicate links
            unique_links = []
            seen_urls = set()
            
            for link in links:
                url = link.get('url', '').strip()
                
                # Skip if we've seen this URL already
                if url in seen_urls:
                    continue
                
                # Add to seen set and unique links
                seen_urls.add(url)
                unique_links.append(link)
            
            logger.info(f"Extracted {len(unique_links)} unique links from content")
            return unique_links
            
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
            'tracking.tldrnewsletter.com',
            'beehiiv.com',
            'substack.com',
            'mailchimp.com',
            'convertkit.com',
            'constantcontact.com',
            'hubspotemail.net',
            'alphasignal.ai',
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
            # Handle TLDR newsletter style URLs
            if 'tracking.tldrnewsletter.com/CL0/' in url:
                # Extract the URL after CL0/
                parts = url.split('CL0/', 1)
                if len(parts) > 1:
                    # The actual URL is everything after CL0/ and before an optional trailing parameter
                    actual_url = parts[1].split('/', 1)[0] if '/' in parts[1] else parts[1]
                    return actual_url
                    
            # Handle Beehiiv trackers
            if 'link.mail.beehiiv.com/ss/c/' in url:
                # For beehiiv URLs, let's try to extract any embedded URLs
                import re
                embedded_urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', url)
                
                # Get the last URL in the string, which is most likely to be the destination
                # but filter out known tracking domains
                if embedded_urls:
                    for embedded_url in embedded_urls:
                        if not any(domain in embedded_url for domain in [
                            'beehiiv.com', 'substack.com', 'mailchimp.com'
                        ]):
                            return embedded_url
                
            # For other tracking URLs, try to find an embedded URL
            import re
            embedded_urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', url)
            
            if embedded_urls:
                # Filter out known tracking domains
                for embedded_url in embedded_urls:
                    if not self._is_tracking_url(embedded_url):
                        return embedded_url
                        
            # If we can't extract a clear URL, return the original
            return url
            
        except Exception as e:
            logger.error(f"Error unwrapping tracking URL {url}: {e}")
            return url
    
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
    
    def _extract_forwarded_content(self, raw_message):
        """Extract content from a forwarded email's raw message."""
        try:
            # Check if raw_message is a Message object or a string
            if hasattr(raw_message, 'as_string'):
                # It's an email.message.Message object, convert to string
                raw_message_str = raw_message.as_string()
            else:
                # It's already a string
                raw_message_str = raw_message
                
            # Now proceed with string operations
            is_html = '<html' in raw_message_str.lower() or '<!doctype html' in raw_message_str.lower()
            
            # For HTML content, use BeautifulSoup to parse it
            if is_html:
                soup = BeautifulSoup(raw_message_str, 'html.parser')
                body = soup.find('body')
                
                if body:
                    forwarded_content = body.get_text(separator='\n', strip=True)
                    return forwarded_content
                return raw_message_str
            
            # For plain text content, extract content based on common patterns
            lines = raw_message_str.split('\n')
            content_lines = []
            in_forwarded_section = False
            
            for line in lines:
                if any(marker in line for marker in ['---------- Forwarded message ---------', '-------- Original Message --------']):
                    in_forwarded_section = True
                    continue
                    
                if in_forwarded_section and not line.startswith('>') and not any(marker in line for marker in ['From:', 'Date:', 'Subject:', 'To:']):
                    content_lines.append(line)
            
            if content_lines:
                return '\n'.join(content_lines)
            
            # If all else fails, just return the raw message with minimal cleaning
            return raw_message_str
            
        except Exception as e:
            self.logger.error(f"Error extracting forwarded content: {e}", exc_info=True)
            if hasattr(raw_message, 'as_string'):
                # Return a simplified version if it's an email.message.Message
                try:
                    if raw_message.is_multipart():
                        for part in raw_message.walk():
                            content_type = part.get_content_type()
                            if content_type == 'text/plain' or content_type == 'text/html':
                                payload = part.get_payload(decode=True)
                                if payload:
                                    return payload.decode('utf-8', errors='replace')
                    else:
                        payload = raw_message.get_payload(decode=True)
                        if payload:
                            return payload.decode('utf-8', errors='replace')
                except Exception as inner_e:
                    self.logger.error(f"Error extracting payload: {inner_e}")
            
            # Last resort fallback
            return str(raw_message)[:500]

    def _extract_content_from_full_message(self, full_message, is_forwarded=False):
        """Extract content from a full email message.
        
        Args:
            full_message (str): The complete email message
            is_forwarded (bool): Whether this is a forwarded email
            
        Returns:
            str: Extracted content
        """
        if not full_message:
            return ""
            
        try:
            # Check if this is an HTML message
            is_html = '<html' in full_message.lower() or '<div' in full_message.lower()
            
            if is_html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(full_message, 'html.parser')
                
                # For forwarded emails, look for specific markers 
                if is_forwarded:
                    # Look for Gmail's forwarded message quote
                    gmail_quote = soup.select_one('.gmail_quote')
                    if gmail_quote:
                        logger.info("Found Gmail quote in forwarded email")
                        return gmail_quote.get_text(separator='\n')
                    
                    # Look for common forwarded message markers in the text
                    for marker in ["---------- Forwarded message ---------", 
                                  "Begin forwarded message:", 
                                  "Forwarded message", 
                                  "Original Message"]:
                        marker_elements = soup.find_all(string=lambda s: s and marker in s)
                        if marker_elements:
                            for element in marker_elements:
                                # Get the parent and all content after it
                                parent = element.parent
                                if parent:
                                    content = parent.get_text(separator='\n')
                                    # Also get all siblings after this element
                                    for sibling in parent.next_siblings:
                                        if sibling.name and sibling.get_text():
                                            content += '\n' + sibling.get_text(separator='\n')
                                    
                                    if len(content) > 200:
                                        logger.info(f"Extracted content after marker: {marker}")
                                        return content
                    
                    # Look for elements with specific styles that indicate forwarded content
                    for element in soup.find_all(['div', 'blockquote']):
                        style = element.get('style', '')
                        if 'border' in style or 'margin' in style or 'padding' in style:
                            content = element.get_text(separator='\n')
                            if len(content) > 200:
                                logger.info("Found styled element that may contain forwarded content")
                                return content
                
                # If no specific forwarded content found, extract all text
                if soup.body:
                    return soup.body.get_text(separator='\n')
                else:
                    return soup.get_text(separator='\n')
            else:
                # For plain text, use different approach
                import re
                
                if is_forwarded:
                    # Look for forwarded message markers in plain text
                    for marker in ["---------- Forwarded message ---------", 
                                  "Begin forwarded message:", 
                                  "Forwarded message", 
                                  "Original Message"]:
                        if marker in full_message:
                            # Extract content after the marker
                            parts = full_message.split(marker, 1)
                            if len(parts) > 1:
                                logger.info(f"Found forwarded marker in plain text: {marker}")
                                return parts[1]
                    
                    # Look for email headers that indicate forwarded content
                    header_pattern = r"From:.*?\nDate:.*?\nSubject:.*?\nTo:"
                    match = re.search(header_pattern, full_message, re.DOTALL)
                    if match:
                        # Get everything after the headers
                        headers_end = match.end()
                        if headers_end < len(full_message):
                            logger.info("Found forwarded email headers in plain text")
                            return full_message[headers_end:]
                
                # If no specific pattern found, return the whole message
                return full_message
                
        except Exception as e:
            logger.error(f"Error extracting content from full message: {e}", exc_info=True)
            return full_message

    def _extract_content_from_raw(self, raw_content, is_forwarded=False):
        """Extract content from raw content.
        
        Args:
            raw_content (str): The raw content
            is_forwarded (bool): Whether the message is forwarded
            
        Returns:
            str: Extracted content
        """
        if not raw_content:
            return ""
        
        try:
            # If it's JSON, try to parse it
            if isinstance(raw_content, str) and (raw_content.startswith('{') or raw_content.startswith('[')):
                import json
                try:
                    data = json.loads(raw_content)
                    if isinstance(data, dict):
                        for key in ['content', 'main_content', 'text', 'html']:
                            if key in data and data[key]:
                                content = data[key]
                                if isinstance(content, str) and len(content) > 100:
                                    return content
                except:
                    # Not valid JSON, continue with raw content as is
                    pass
            
            # If it's a string, treat it as HTML or plain text
            if isinstance(raw_content, str):
                return self._extract_content_from_full_message(raw_content, is_forwarded)
            
            # If it's a dict, try to get content fields
            if isinstance(raw_content, dict):
                for key in ['content', 'main_content', 'text', 'html']:
                    if key in raw_content and raw_content[key]:
                        content = raw_content[key]
                        if isinstance(content, str) and len(content) > 100:
                            return content
            
            # Convert to string as a last resort
            return str(raw_content)
        
        except Exception as e:
            logger.error(f"Error extracting content from raw content: {e}", exc_info=True)
            return str(raw_content)

    def _clean_text(self, text_content):
        """Clean plain text content.
        
        Args:
            text_content (str): Text content to clean
            
        Returns:
            str: Cleaned text
        """
        if not text_content:
            return ""
        
        # Normalize line endings
        text = text_content.replace('\r\n', '\n').replace('\r', '\n')
        
        # Split into lines
        lines = text.splitlines()
        
        # Remove empty lines
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        
        # Join back with newlines
        cleaned_text = '\n'.join(non_empty_lines)
        
        return cleaned_text 