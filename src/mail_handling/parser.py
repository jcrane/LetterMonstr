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
        """Parse the email content and extract meaningful information"""
        try:
            logger.info(f"Parsing email: {email_data.get('subject', '')}")
            
            # Store raw values
            raw_html = email_data.get('html_content', '')
            raw_text = email_data.get('text_content', '')
            subject = email_data.get('subject', '')
            
            # Special handling for problematic emails with emoji
            if 'AI Risk Curve' in subject or 'CoreWeave IPO' in subject or '🤖' in subject or '💹' in subject:
                logger.info(f"Special handling for emoji email: {subject}")
                
                # First, check if we have the original_full_message
                if 'original_full_message' in email_data:
                    full_message = email_data['original_full_message']
                    
                    # Try to extract content directly
                    lines = full_message.splitlines()
                    content_start = False
                    content_lines = []
                    
                    for line in lines:
                        # Look for blank line after headers which typically marks the start of content
                        if not content_start and line.strip() == '':
                            content_start = True
                            continue
                        
                        if content_start:
                            # Skip common email separators/signatures
                            if '--' in line and len(line.strip()) < 10:
                                continue
                            content_lines.append(line)
                    
                    if content_lines:
                        extracted_content = '\n'.join(content_lines)
                        if len(extracted_content) > 100:  # Only use if substantial
                            logger.info(f"Extracted content directly from message, length: {len(extracted_content)}")
                            email_data['main_content'] = extracted_content
                            email_data['content_source'] = 'original_message_direct'
                            return email_data
            
            # Check if email appears to be a forwarded message
            is_forwarded = False
            forwarded_markers = [
                "fwd:", "fw:", "forwarded", 
                "---------- forwarded message ---------", 
                "begin forwarded message"
            ]
            
            # Check subject for forwarding markers
            if any(marker in subject.lower() for marker in forwarded_markers):
                is_forwarded = True
                logger.info(f"Detected forwarded email from subject: {subject}")
            
            # Check content for forwarding markers if we have content
            if not is_forwarded and raw_html:
                lower_html = raw_html.lower()
                if any(marker in lower_html for marker in forwarded_markers) or "gmail_quote" in lower_html:
                    is_forwarded = True
                    logger.info(f"Detected forwarded email from content markers")
            
            # If this is a forwarded email with emoji, try another approach
            if is_forwarded and ('🤖' in subject or '💹' in subject or 'AI Risk Curve' in subject):
                logger.info(f"Using specialized approach for forwarded emoji email: {subject}")
                
                # Try to use the raw text content directly if available
                if raw_text and len(raw_text) > 100:
                    # Remove common email headers from forwarded messages
                    import re
                    cleaned_text = raw_text
                    
                    # Remove forwarded headers pattern
                    header_pattern = r"(-{5,}|={5,})\s*(Forwarded|Original).*?(-{5,}|={5,})"
                    cleaned_text = re.sub(header_pattern, "", cleaned_text, flags=re.DOTALL | re.IGNORECASE)
                    
                    # Remove email headers
                    header_lines = [
                        r"From:.*?[\r\n]",
                        r"Sent:.*?[\r\n]", 
                        r"To:.*?[\r\n]",
                        r"Subject:.*?[\r\n]",
                        r"Date:.*?[\r\n]"
                    ]
                    
                    for pattern in header_lines:
                        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)
                    
                    # If we have substantial content after cleaning
                    if len(cleaned_text) > 100:
                        logger.info(f"Using directly cleaned text content, length: {len(cleaned_text)}")
                        email_data['main_content'] = cleaned_text
                        email_data['content_source'] = 'cleaned_text_direct'
                        return email_data
            
            # If HTML content exists, use it as primary source
            if raw_html:
                # Clean and extract content from HTML
                cleaned_html = self._clean_html(raw_html, is_forwarded, subject)
                main_content = self._extract_text_from_html(cleaned_html)
                content_source = 'html'
            else:
                # If no HTML, use text content
                main_content = raw_text
                content_source = 'text'
            
            # If content is too short (or empty) or we know it's forwarded, try deeper search
            if (not main_content or len(main_content) < 100) or is_forwarded:
                alternative_content, better_source = self._deep_search_content(email_data, is_forwarded)
                
                # Only use alternative if it's substantially better
                if alternative_content and len(alternative_content) > max(len(main_content) if main_content else 0, 50):
                    main_content = alternative_content
                    content_source = better_source
                    logger.info(f"Using better content from '{better_source}', new length: {len(main_content)}")
            
            # Last resort: If still no good content and we have original_full_message, try direct extraction
            if (not main_content or len(main_content) < 50) and 'original_full_message' in email_data:
                logger.info("Trying direct extraction from original_full_message as last resort")
                orig_message = email_data['original_full_message']
                
                # Try a different approach to extract content
                import re
                
                # Remove all email headers
                headers_end = re.search(r'\r?\n\r?\n', orig_message)
                if headers_end:
                    content_part = orig_message[headers_end.end():]
                    
                    # Remove any quoted reply/forwarded markers
                    content_part = re.sub(r'On.*?wrote:', '', content_part, flags=re.DOTALL)
                    content_part = re.sub(r'--+.*?--+', '', content_part, flags=re.DOTALL)
                    
                    if len(content_part) > 100:
                        main_content = content_part
                        content_source = 'original_message_direct_extract'
                        logger.info(f"Extracted content directly from original message, length: {len(main_content)}")
            
            # Set the main content in the email data
            email_data['main_content'] = main_content
            email_data['content_source'] = content_source
            
            # Last fallback: if content is still too short, take everything we have
            if not main_content or len(main_content) < 50:
                logger.warning(f"Very short content for source: {subject}, length: {len(main_content) if main_content else 0}")
                
                # Use the full message as a last resort
                if 'original_full_message' in email_data:
                    email_data['main_content'] = email_data['original_full_message']
                    email_data['content_source'] = 'full_message_fallback'
                    logger.info(f"Using full message as fallback, length: {len(email_data['original_full_message'])}")
            
            return email_data
        except Exception as e:
            logger.exception(f"Error parsing email: {e}")
            # Still return what we have even if processing failed
            if 'main_content' not in email_data:
                email_data['main_content'] = email_data.get('text_content', '')
            return email_data
    
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
    
    def _deep_search_content(self, email_data, is_forwarded=False):
        """Search more deeply for content in complex email structures"""
        raw_html = email_data.get('html_content', '')
        raw_text = email_data.get('text_content', '')
        best_content = ""
        content_source = ""
        
        # Special handling for emails with forwarded markers in the subject
        subject = email_data.get('subject', '')
        if is_forwarded or ('fwd:' in subject.lower()) or ('🤖' in subject):
            logger.info(f"Deep search for forwarded email or special email: {subject}")
            
            # Try to extract content from original full message
            if 'original_full_message' in email_data:
                orig_message = email_data['original_full_message']
                
                # Search for forwarded content in the original message
                forwarded_sections = []
                
                # Look for common forwarded email markers
                markers = [
                    "---------- Forwarded message ---------",
                    "Begin forwarded message:",
                    "From:",
                    "Date:",
                    "Subject:",
                    "To:"
                ]
                
                # Find the position of all these markers
                marker_positions = {}
                for marker in markers:
                    if marker in orig_message:
                        marker_positions[marker] = orig_message.find(marker)
                
                if marker_positions:
                    # Find the first marker that appears
                    first_marker = min(marker_positions.items(), key=lambda x: x[1])[0]
                    start_pos = marker_positions[first_marker]
                    
                    # Find the actual content after headers
                    header_end = orig_message.find("\n\n", start_pos)
                    if header_end > 0:
                        content = orig_message[header_end+2:]
                        forwarded_sections.append(content)
                
                # If we found forwarded sections, use the longest one
                if forwarded_sections:
                    best_content = max(forwarded_sections, key=len)
                    content_source = 'original_message_forwarded'
                    logger.info(f"Found content in original message forwarded section: {len(best_content)} chars")
        
        # If we still don't have good content, try parsing HTML more aggressively
        if not best_content and raw_html:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(raw_html, 'html.parser')
                
                # Try different content extraction strategies
                
                # 1. Look for main content divs
                content_candidates = []
                for div in soup.find_all('div', class_=lambda c: c and ('content' in c.lower() or 'body' in c.lower())):
                    content_candidates.append(div.get_text(strip=True))
                
                # 2. Look for large text blocks
                for p in soup.find_all(['p', 'div']):
                    text = p.get_text(strip=True)
                    if len(text) > 100:  # Only consider substantial paragraphs
                        content_candidates.append(text)
                
                if content_candidates:
                    best_content = max(content_candidates, key=len)
                    content_source = 'aggressive_html'
                    logger.info(f"Found content through aggressive HTML parsing: {len(best_content)} chars")
            except Exception as e:
                logger.exception(f"Error in aggressive HTML parsing: {e}")
        
        # If we found something better, return it
        if best_content:
            return best_content, content_source
        
        # Otherwise return empty result
        return "", ""
    
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
    
    def _deep_search_content(self, data, depth=0, max_depth=5):
        """Recursively search for the largest text content in a nested structure."""
        if depth > max_depth:
            return ""
        
        if isinstance(data, str):
            return data
        
        best_content = ""
        
        if isinstance(data, dict):
            # First check common content keys
            for key in ['html', 'text', 'content', 'body', 'message', 'payload', 'value', 'data', 'source', 'parsed']:
                if key in data and isinstance(data[key], str) and len(data[key]) > len(best_content):
                    best_content = data[key]
                
            # Special handling for Gmail structure
            if 'payload' in data and isinstance(data['payload'], dict):
                # Gmail specific - check for parts array
                if 'parts' in data['payload'] and isinstance(data['payload']['parts'], list):
                    for part in data['payload']['parts']:
                        if isinstance(part, dict) and 'body' in part and 'data' in part['body']:
                            content = self._deep_search_content(part['body']['data'], depth + 1, max_depth)
                            if len(content) > len(best_content):
                                best_content = content
            
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
        
        # If content is HTML, try to extract just the meaningful text from it to detect 
        # if it's an empty HTML template
        if best_content and '<html' in best_content.lower():
            try:
                # Check if this is valid HTML with actual content
                soup = BeautifulSoup(best_content, 'html.parser')
                text_only = soup.get_text(strip=True)
                
                # If the text content is very short, this might be an empty template
                if len(text_only) < 50:
                    logger.warning(f"Found HTML content but it has very little text ({len(text_only)} chars)")
                    best_content = text_only if text_only else best_content
            except Exception as e:
                logger.error(f"Error parsing potential HTML content: {e}")
                
        return best_content 