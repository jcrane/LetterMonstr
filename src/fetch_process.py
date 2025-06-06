#!/usr/bin/env python3
"""
Periodic Email Fetcher and Processor for LetterMonstr.

This module handles periodic fetching and processing of emails
without immediately generating summaries.
"""

import os
import sys
import json
import logging
import hashlib
import time
from datetime import datetime, timedelta
import uuid
import schedule
from sqlalchemy import text

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Import required modules
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import components
from src.email_module.fetcher import EmailFetcher
from src.mail_handling.parser import EmailParser
from src.crawl.crawler import WebCrawler
from src.summarize.processor import ContentProcessor
from src.database.models import get_session, ProcessedEmail, ProcessedContent, EmailContent, Link

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(project_root, 'data', 'lettermonstr.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Custom JSON encoder to handle datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def json_serialize(obj):
    """Serialize object to JSON, handling special types."""
    def default_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Handle email Message objects by converting to string
        elif hasattr(obj, 'as_string') and callable(obj.as_string):
            return "Email Message Object"
        # Handle any other non-serializable objects
        else:
            return str(obj)
    
    try:
        # For string content, don't convert to JSON, just pass through directly
        if isinstance(obj, str):
            return obj
            
        # For dict content that might contain large strings, process specially
        elif isinstance(obj, dict):
            # Check if it contains large HTML or text content that should be preserved as is
            if ('html' in obj and isinstance(obj['html'], str) and len(obj['html']) > 10000) or \
               ('text' in obj and isinstance(obj['text'], str) and len(obj['text']) > 10000) or \
               ('content' in obj and isinstance(obj['content'], str) and len(obj['content']) > 10000):
                
                # For large email content, convert to a single string representation
                logger.info(f"Converting large email content to direct string storage")
                
                # Use HTML content if available as it contains more information
                if 'html' in obj and isinstance(obj['html'], str) and len(obj['html']) > 10000:
                    return obj['html']
                elif 'content' in obj and isinstance(obj['content'], str) and len(obj['content']) > 10000:
                    return obj['content']
                elif 'text' in obj and isinstance(obj['text'], str) and len(obj['text']) > 10000:
                    return obj['text']
            
            # Create a new dict with potential large string values intact
            processed_dict = {}
            for key, value in obj.items():
                if isinstance(value, str) and len(value) > 10000:
                    # For large string values, preserve them exactly as is
                    processed_dict[key] = value
                elif isinstance(value, dict):
                    # Recursively handle nested dictionaries
                    processed_dict[key] = json_serialize(value)
                else:
                    processed_dict[key] = value
            
            # Now serialize the processed dict
            try:
                return json.dumps(processed_dict, default=default_serializer)
            except TypeError as e:
                logger.warning(f"Error serializing dict with large values: {e}")
                # Fall back to a simpler serialization
                simple_dict = {k: str(v) if not isinstance(v, (int, float, bool, str, type(None))) else v 
                              for k, v in processed_dict.items()}
                return json.dumps(simple_dict)
        else:
            return json.dumps(obj, default=default_serializer)
    except Exception as e:
        logger.error(f"Error in JSON serialization: {e}", exc_info=True)
        # Last resort: convert the entire object to a string
        if isinstance(obj, dict):
            # For dicts, try to preserve large string fields
            result = {}
            for k, v in obj.items():
                if isinstance(v, str):
                    result[k] = v[:1000000]  # Preserve string content with reasonable limit
                else:
                    result[k] = str(v)
            return json.dumps(result)
        else:
            return json.dumps(str(obj))

class PeriodicFetcher:
    """Handles periodic fetching and processing of emails."""
    
    def __init__(self, config):
        """Initialize with configuration."""
        self.config = config
        self.email_fetcher = EmailFetcher(config['email'])
        self.email_parser = EmailParser()
        self.web_crawler = WebCrawler(config['content'])
        self.content_processor = ContentProcessor(config['content'])
        self.db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
        
        # Create status file path for tracking last fetch time
        self.status_file = os.path.join(project_root, 'data', 'fetch_status.json')
        
        # Initialize or load status
        self._init_status()
    
    def _init_status(self):
        """Initialize or load status from file."""
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, 'r') as f:
                    self.status = json.load(f)
                    logger.info(f"Loaded status from {self.status_file}")
            except Exception as e:
                logger.error(f"Error loading status file: {e}")
                self.status = {"last_fetch": None}
        else:
            self.status = {"last_fetch": None}
            self._save_status()
    
    def _save_status(self):
        """Save status to file."""
        try:
            with open(self.status_file, 'w') as f:
                json.dump(self.status, f)
                logger.info(f"Saved status to {self.status_file}")
        except Exception as e:
            logger.error(f"Error saving status file: {e}")
    
    def _generate_content_hash(self, content):
        """Generate a hash for content to detect duplicates."""
        # Handle datetime objects in content by recursively converting them to strings
        def serialize_json_safe(obj):
            if isinstance(obj, dict):
                return {k: serialize_json_safe(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [serialize_json_safe(item) for item in obj]
            elif isinstance(obj, datetime):
                return obj.isoformat()
            else:
                return obj
        
        # Create a JSON-safe copy of the content
        json_safe_content = serialize_json_safe(content)
        
        if isinstance(json_safe_content, dict):
            content_str = json.dumps(json_safe_content, sort_keys=True)
        else:
            content_str = str(json_safe_content)
        
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()
    
    def fetch_and_process(self):
        """Fetch new emails and process them without generating a summary."""
        logger.info("Starting periodic fetch and process...")
        
        try:
            # Fetch new emails
            logger.info("Fetching new emails...")
            emails = self.email_fetcher.fetch_new_emails()
            
            if not emails:
                logger.info("No new emails to process")
                return
            
            logger.info(f"Fetched {len(emails)} new emails")
            
            # Process each email - ONE AT A TIME to avoid database contention
            logger.info(f"Beginning to process {len(emails)} emails one at a time")
            successfully_processed = []
            
            for idx, email in enumerate(emails):
                # Create a new session for each email to ensure clean transactions
                session = get_session(self.db_path)
                try:
                    logger.info(f"Processing email {idx+1}/{len(emails)}: {email['subject']}")
                    
                    # Process this single email with its own session and transaction
                    processed = self._process_single_email(session, email)
                    if processed:
                        successfully_processed.append(email)
                    
                    # Commit the transaction 
                    session.commit()
                except Exception as e:
                    logger.error(f"Error processing email {email['subject']}: {e}", exc_info=True)
                    if hasattr(session, 'rollback'):
                        session.rollback()
                finally:
                    # Always close the session to release locks
                    session.close()
            
            logger.info(f"Successfully processed {len(successfully_processed)} emails")
            
            # Mark emails as read in Gmail if configured to do so
            if successfully_processed:
                if not self.config['email'].get('mark_read_only_after_summary', True):
                    self.email_fetcher.mark_emails_as_processed(successfully_processed)
                    logger.info(f"Marked {len(successfully_processed)} emails as read in Gmail")
                else:
                    logger.info("Emails will remain unread in Gmail until summary is sent")
            
            # Update last fetch time
            self.status["last_fetch"] = datetime.now().isoformat()
            self._save_status()
            
        except Exception as e:
            logger.error(f"Error during fetch and process: {e}", exc_info=True)
    
    def _process_single_email(self, session, email):
        """Process a single email with proper transaction handling."""
        try:
            # Enhanced forwarded email detection
            is_forwarded = False
            subject = email.get('subject', '')
            
            # Check various indicators that this might be a forwarded email
            if (subject.startswith('Fwd:') or 
                'forwarded message' in subject.lower() or 
                ('content' in email and isinstance(email['content'], dict) and
                 (('html' in email['content'] and 
                   ("---------- Forwarded message ---------" in email['content'].get('html', '') or
                    "Begin forwarded message:" in email['content'].get('html', '') or
                    "border:none;border-top:solid #B5C4DF" in email['content'].get('html', ''))) or
                  ('text' in email['content'] and
                   ("---------- Forwarded message ---------" in email['content'].get('text', '') or
                    "Begin forwarded message:" in email['content'].get('text', '')))))):
                is_forwarded = True
                logger.info(f"Detected forwarded email: {subject}")
                # Add a flag to the email data for the parser to use
                email['is_forwarded'] = True
                
                # Pre-create the email record for forwarded emails to ensure we have an ID
                email_record = self._mark_email_as_processed_in_db(session, email)
                # Add the DB ID to the email data for the parser to use
                email['db_id'] = email_record.id
                logger.info(f"Pre-created database record for forwarded email, ID: {email_record.id}")
                
                # Include raw message if available
                if 'raw_message' in email:
                    logger.info("Forwarding raw message data to parser")
                    # No need to do anything else, just make sure it's included
                elif 'raw_content' in email:
                    logger.info("Forwarding raw content data to parser")
            
            # Parse email content
            parsed_content = self.email_parser.parse(email)
            
            if not parsed_content:
                logger.warning(f"Failed to parse email: {email['subject']}")
                return False
                
            # Get content and type directly from parsed_content
            content = parsed_content.get('content', '')
            content_type = parsed_content.get('content_type', '')
            links = parsed_content.get('links', [])
                
            if not content:
                logger.warning(f"No content extracted from email: {email['subject']}")
                return False
                
            # Generate or use DB ID for the email
            if not is_forwarded:  # For forwarded emails, we already have the ID
                # Mark the email as processed in the database
                email_record = self._mark_email_as_processed_in_db(session, email)
                if not email_record:
                    logger.error(f"Failed to create database record for email: {email['subject']}")
                    return False
                    
                email_id = email_record.id
            else:
                email_id = email['db_id']
            
            # Process link content (this will extract content from the links)
            self._extract_link_content(email_id, content_type, content, links, session)
            
            # CRITICAL FIX: Check if the original content from email is a dict with HTML/text
            # and pass it directly to preserve the large content
            if isinstance(content, dict) and ('html' in content or 'text' in content):
                # This means we have a structured content dict with HTML or text
                html_len = len(content.get('html', '')) if isinstance(content.get('html', ''), str) else 0
                text_len = len(content.get('text', '')) if isinstance(content.get('text', ''), str) else 0
                logger.info(f"Passing structured content directly: HTML={html_len} chars, TEXT={text_len} chars")
                
                # Process the content source - passing the FULL content dictionary
                processed_content_entry = self._process_content_source(
                    session, 
                    content,  # Pass the full dict with HTML/text directly
                    content_type,
                    email_id,
                    email['subject'],
                    email.get('date'),
                    is_forwarded,
                    parsed_content
                )
            else:
                # Create a content source structure
                content_source = {
                    'type': content_type,
                    'content': content,
                    'is_full_email': True,
                    'links': links
                }
                
                # Process the content source
                processed_content_entry = self._process_content_source(
                    session, 
                    content_source['content'],
                    content_source['type'],
                    email_id,
                    email['subject'],
                    email.get('date'),
                    is_forwarded,
                    parsed_content
                )
            
            if not processed_content_entry:
                logger.warning(f"Failed to create processed content entry for email: {email['subject']}")
                return False
            
            logger.info(f"Successfully processed email: {email['subject']}")
            return True
            
        except Exception as e:
            logger.error(f"Error in _process_single_email: {e}", exc_info=True)
            return False
    
    def _mark_email_as_processed_in_db(self, session, email):
        """Mark an email as processed in the database without marking it as read in Gmail."""
        max_retries = 5
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                # Check if the email is already in the database
                existing = None
                if 'message_id' in email:
                    existing = session.query(ProcessedEmail).filter_by(message_id=email['message_id']).first()
                
                if existing:
                    # If it exists, update the processed date
                    existing.date_processed = datetime.now()
                    session.flush()  # Attempt to flush changes
                    logger.debug(f"Updated existing email {email['subject']} as processed in database")
                    return existing
                else:
                    # If it doesn't exist, create a new record
                    processed_email = ProcessedEmail(
                        message_id=email['message_id'],
                        subject=email['subject'],
                        sender=email['sender'],
                        date_received=email['date'],
                        date_processed=datetime.now()
                    )
                    session.add(processed_email)
                    session.flush()  # To get the ID
                    logger.debug(f"Added new email {email['subject']} to database")
                    return processed_email
                    
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    # If database is locked and we have retries left
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Database locked when marking email as processed, retrying in {wait_time:.2f}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Error marking email as processed in database: {e}", exc_info=True)
                    raise
                    
        # If we reach here, we've exhausted all retries
        logger.error(f"Failed to mark email as processed after {max_retries} attempts due to database locks")
        raise Exception(f"Database remained locked after {max_retries} attempts")

    def _extract_link_content(self, email_id, content_type, parsed_content, links, session):
        """Extract and store content from links."""
        try:
            # Get configuration for maximum links to crawl per email
            max_links = self.config['content'].get('max_links_per_email', 5)
            
            # Resolve tracking URLs in links first
            links = self._resolve_tracking_urls(links)
            
            # Store the links in the database
            content_id = self._store_email_content(email_id, content_type, parsed_content, links, session)
            
            if not content_id or not links:
                return
            
            # Only process a limited number of links to avoid overwhelming the crawler
            links_to_process = links[:max_links]
            logger.info(f"Processing {len(links_to_process)} of {len(links)} links")
            
            # Process each link
            for link in links_to_process:
                try:
                    url = link.get('url', '')
                    
                    # Skip if URL is not valid
                    if not url or not url.startswith('http'):
                        continue
                    
                    # Crawl the link
                    crawled_content = self.web_crawler.crawl(url)
                    
                    if not crawled_content:
                        logger.info(f"No content crawled from {url}")
                        continue
                    
                    # Process the content
                    self._process_crawled_content(crawled_content, url, email_id, link, session)
                    
                except Exception as e:
                    logger.error(f"Error processing link {link.get('url', '')}: {e}", exc_info=True)
            
        except Exception as e:
            logger.error(f"Error extracting link content: {e}", exc_info=True)
            
    def _resolve_tracking_urls(self, links):
        """Resolve tracking URLs to their final destinations."""
        resolved_links = []
        
        for link in links:
            try:
                url = link.get('url', '')
                
                # Skip if URL is empty
                if not url:
                    resolved_links.append(link)
                    continue
                
                # Check if this is a tracking URL using common patterns
                is_tracking = False
                tracking_domains = [
                    'mail.beehiiv.com',
                    'link.mail.beehiiv.com',
                    'email.mailchimpapp.com',
                    'mailchi.mp',
                    'click.convertkit-mail.com',
                    'track.constantcontact.com',
                    'links.substack.com',
                    'tracking.mailerlite.com',
                    'tracking.tldrnewsletter.com',
                    'sendgrid.net',
                    'email.mg.substack.com',
                ]
                
                for domain in tracking_domains:
                    if domain in url:
                        is_tracking = True
                        break
                
                # Additional checks for tracking URL patterns
                if not is_tracking:
                    tracking_patterns = [
                        '/redirect/',
                        '/track/',
                        '/click?',
                        '/ss/c/',
                        'CL0/',
                    ]
                    
                    for pattern in tracking_patterns:
                        if pattern in url:
                            is_tracking = True
                            break
                
                # If it's a tracking URL, try to resolve it
                if is_tracking:
                    logger.info(f"Resolving tracking URL: {url}")
                    
                    try:
                        # Use the web crawler to follow redirects and get the final URL
                        final_url = self.web_crawler.resolve_redirect(url)
                        
                        if final_url and final_url != url:
                            logger.info(f"Resolved tracking URL: {url} -> {final_url}")
                            
                            # Create a new link entry with the resolved URL
                            resolved_link = link.copy()
                            resolved_link['url'] = final_url
                            resolved_link['original_url'] = url  # Keep the original URL for reference
                            
                            resolved_links.append(resolved_link)
                            continue
                        
                    except Exception as e:
                        logger.error(f"Error resolving tracking URL {url}: {e}")
                
                # If we couldn't resolve it or it's not a tracking URL, keep the original
                resolved_links.append(link)
                
            except Exception as e:
                logger.error(f"Error processing link in resolver: {e}")
                resolved_links.append(link)
        
        return resolved_links

    def _store_email_content(self, email_id, content_type, content, links, session):
        """Store email content and links in the database."""
        max_retries = 5
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                # Create content entry
                content_entry = EmailContent(
                    email_id=email_id,
                    content_type=content_type
                )
                
                # Use the set_content method to properly handle different data types
                content_entry.set_content(content)
                
                session.add(content_entry)
                try:
                    session.flush()  # Get ID without committing
                except Exception as e:
                    if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                        # If database is locked and we have retries left, raise to outer handler
                        raise
                
                content_id = content_entry.id
                logger.debug(f"Created content entry with ID: {content_id}")
                
                # Store links if any
                if links:
                    for link in links:
                        url = link.get('url', '')
                        title = link.get('title', '')
                        
                        # Skip empty URLs
                        if not url:
                            continue
                        
                        link_entry = Link(
                            content_id=content_id,
                            url=url,
                            title=title
                        )
                        
                        session.add(link_entry)
                    
                    logger.debug(f"Added {len(links)} links to content ID: {content_id}")
                
                # Commit is handled by the caller
                return content_id
                
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    # If database is locked and we have retries left
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Database locked when storing email content, retrying in {wait_time:.2f}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Error storing email content: {e}", exc_info=True)
                    return None
        
        # If we reach here, we've exhausted all retries
        logger.error(f"Failed to store email content after {max_retries} attempts due to database locks")
        return None
            
    def _process_content_source(self, session, content, content_type, email_id, subject, date, is_forwarded=False, email_data=None):
        """Process a single content source and create ProcessedContent entry."""
        max_retries = 5
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                # Initialize content processor if needed
                if not hasattr(self, 'content_processor'):
                    logger.info("Initializing ContentProcessor")
                    from src.summarize.processor import ContentProcessor
                    self.content_processor = ContentProcessor(self.db_path)
                
                # Skip if already processed based on URL for non-email content
                if email_id is None and content_type == 'article':
                    source_url = content.get('url', '')
                    if source_url:
                        existing = session.query(ProcessedContent).filter_by(url=source_url).first()
                        if existing:
                            logger.info(f"Content already exists with URL: {source_url}")
                            return existing
                
                # Sanitize the email data to ensure it can be serialized
                sanitized_email_data = self._sanitize_for_json(email_data) if email_data else None
                
                # Extract the best content directly
                best_content = None
                best_content_type = None
                best_content_length = 0
                
                # For email content from fetcher, extract HTML or text directly
                if isinstance(content, dict):
                    if 'html' in content and isinstance(content['html'], str) and len(content['html']) > 1000:
                        best_content = content['html']
                        best_content_type = 'html'
                        best_content_length = len(best_content)
                        logger.info(f"Found HTML content: {best_content_length} chars")
                    
                    if 'text' in content and isinstance(content['text'], str) and len(content['text']) > best_content_length:
                        best_content = content['text']
                        best_content_type = 'text'
                        best_content_length = len(best_content)
                        logger.info(f"Found text content: {best_content_length} chars")
                
                # If we have substantial content, store it directly
                if best_content and best_content_length > 5000:
                    logger.info(f"Storing raw {best_content_type} content directly for {subject}: {best_content_length} chars")
                    
                    # Extract clean text from HTML if needed
                    clean_content = best_content
                    if best_content_type == 'html' and best_content_length > 10000:
                        try:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(best_content, 'html.parser')
                            text_content = soup.get_text(separator='\n', strip=True)
                            
                            if len(text_content) > 1000:
                                clean_content = text_content
                                logger.info(f"Extracted clean text from HTML: {len(clean_content)} chars")
                        except Exception as e:
                            logger.warning(f"Failed to extract text from HTML: {e}")
                    
                    # Generate content hash for deduplication
                    content_hash = hashlib.md5(f"{subject}_{datetime.now().isoformat()}".encode('utf-8')).hexdigest()
                    
                    # Create a JSON structure with all the content variants
                    content_structure = {
                        'source': subject,
                        'date': date.isoformat() if isinstance(date, datetime) else date,
                        'content': clean_content,
                        'content_type': content_type,
                        'is_forwarded': is_forwarded,
                        'original_length': best_content_length,
                        'original_content_type': best_content_type
                    }
                    
                    # Add HTML or text if available
                    if isinstance(content, dict):
                        if 'html' in content and content['html']:
                            content_structure['html'] = content['html']
                        if 'text' in content and content['text']:
                            content_structure['text'] = content['text']
                    
                    # Store the full structure as serialized JSON
                    serialized_content = json.dumps(content_structure)
                    
                    # Create ProcessedContent entry
                    processed_content = ProcessedContent(
                        content_hash=content_hash,
                        email_id=email_id,
                        source=subject,
                        content_type=content_type,
                        processed_content=serialized_content,
                        date_processed=datetime.now(),
                        is_summarized=False
                    )
                    
                    session.add(processed_content)
                    try:
                        session.flush()  # Try to flush changes to get ID
                    except Exception as e:
                        if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                            # If database is locked and we have retries left, raise to outer handler
                            raise
                    
                    logger.info(f"Created ProcessedContent entry with ID: {processed_content.id}")
                    return processed_content
                
                # If no large content found, use the content processor normally
                logger.info(f"No large content found, using content processor for: {subject}")
                
                # Create content item for processing
                content_item = {
                    'source': subject,
                    'date': date,
                    'content_type': content_type,
                    'is_forwarded': is_forwarded,
                    'original_email': sanitized_email_data
                }
                
                # For email content, set the content directly
                # If content is a dict (from email_module.fetcher), keep both html and text
                if isinstance(content, dict):
                    if 'html' in content and content['html']:
                        content_item['content'] = content['html']
                        content_item['html'] = content['html']
                        logger.info(f"Using HTML content from email: {len(content['html'])} chars")
                    elif 'text' in content and content['text']:
                        content_item['content'] = content['text']
                        content_item['text'] = content['text']
                        logger.info(f"Using text content from email: {len(content['text'])} chars")
                    
                    # Store all content variants for later use
                    for key, value in content.items():
                        if key not in ['attachments'] and isinstance(value, str) and len(value) > 0:
                            content_item[key] = value
                else:
                    # Simple string content
                    content_item['content'] = content
                
                # Additional logging to trace content length
                content_length = 0
                if isinstance(content_item.get('content'), str):
                    content_length = len(content_item['content'])
                logger.info(f"Content item for {subject} has content length: {content_length} chars")
                
                # For crawled content, structure differently
                if content_type == 'article':
                    content_item['crawled_content'] = [content]
                
                # Process through the normal pipeline
                processed_items = self.content_processor.process_and_deduplicate([content_item])
                
                if not processed_items:
                    logger.warning(f"No processed items returned for: {subject}")
                    return None
                
                processed_item = processed_items[0]  # Take the first item
                
                # Generate content hash for deduplication
                content_hash = self._generate_content_hash(processed_item)
                
                # Check if content already exists
                existing = session.query(ProcessedContent).filter_by(content_hash=content_hash).first()
                if existing:
                    logger.info(f"Content already exists with hash: {content_hash}")
                    return existing
                
                # Get the serialized content, which might now be just HTML for large emails
                serialized_content = json_serialize(processed_item)
                
                # Create ProcessedContent entry
                processed_content = ProcessedContent(
                    content_hash=content_hash,
                    email_id=email_id,
                    source=subject,
                    content_type=content_type,
                    processed_content=serialized_content,
                    date_processed=datetime.now(),
                    is_summarized=False
                )
                
                session.add(processed_content)
                try:
                    session.flush()  # Try to flush changes to get ID
                except Exception as e:
                    if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                        # If database is locked and we have retries left, raise to outer handler
                        raise
                
                logger.info(f"Created ProcessedContent entry with ID: {processed_content.id}")
                return processed_content
                
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    # If database is locked and we have retries left
                    wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Database locked when processing content, retrying in {wait_time:.2f}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Error processing content source: {e}", exc_info=True)
                    return None
                    
        # If we reach here, we've exhausted all retries
        logger.error(f"Failed to process content after {max_retries} attempts due to database locks")
        return None

    def _sanitize_for_json(self, obj):
        """Sanitize an object for JSON serialization by removing or converting problematic fields."""
        if obj is None:
            return None
        
        if isinstance(obj, dict):
            # Create a new cleaned dictionary
            result = {}
            for key, value in obj.items():
                # Skip any raw_message or message fields that might contain email.Message objects
                if key in ['raw_message', 'message']:
                    continue
                    
                # Recursively sanitize nested dictionaries and lists
                result[key] = self._sanitize_for_json(value)
            return result
        elif isinstance(obj, list):
            return [self._sanitize_for_json(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        else:
            # Convert any other types to string
            return str(obj)

    def _process_emails(self, emails, gmail_service=None):
        """Process new emails and extract content"""
        logger.info(f"Processing {len(emails)} emails")
        processed_count = 0
        
        fetcher = EmailFetcher(self.config)
        parser = EmailParser()
        
        for email in emails:
            try:
                # Get email details
                message_id = email['id']
                
                # Skip if already processed
                if self._is_email_processed(message_id):
                    logger.debug(f"Email {message_id} already processed, skipping.")
                    continue
                    
                # Get full message
                message_data = fetcher.get_email_by_id(message_id, gmail_service)
                
                # Parse email content
                email_data = parser.parse(message_data)
                
                # Save email to database
                email_id = fetcher.mark_email_as_processed(email_data, message_id)
                
                # Extract content and content type
                content = email_data.get('content', '')
                content_type = email_data.get('content_type', 'text')
                
                # Extract links
                links = email_data.get('links', [])
                
                # Store email content
                session = get_session(self.db_path)
                try:
                    # Store content separately
                    fetcher._store_email_content(email_id, content_type, content, links, session)
                    
                    # Process content for summarization
                    subject = email_data.get('subject', 'No Subject')
                    date = email_data.get('date', datetime.now())
                    self._process_content_source(session, content, content_type, email_id, subject, date, 
                                              is_full_email=True, email_data=email_data)
                    
                    session.commit()
                except Exception as e:
                    logger.error(f"Error storing/processing content: {e}", exc_info=True)
                    session.rollback()
                finally:
                    session.close()
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing email {email.get('id', 'unknown')}: {e}", exc_info=True)
        
        return processed_count

    def _process_crawled_content(self, crawled_content, url, email_id, link_data, session):
        """Process crawled content from a link."""
        try:
            # Skip if no content
            if not crawled_content:
                logger.warning(f"No crawled content for URL: {url}")
                return
            
            for content in crawled_content:
                # Skip ad content
                if content.get('is_ad', False):
                    logger.info(f"Skipping ad content from {url}")
                    continue
                
                # Get link information
                title = content.get('title', link_data.get('title', 'No Title'))
                content_text = content.get('content', '')
                
                # Ensure we have actual content before proceeding
                if not content_text or len(content_text.strip()) < 50:
                    logger.warning(f"Insufficient content from URL: {url}, skipping")
                    continue
                
                # Create content item for processing
                content_item = {
                    'source': title,
                    'url': url,
                    'content': content_text,
                    'content_type': 'article',
                    'crawled_date': datetime.now().isoformat()
                }
                
                # Process the content item
                processed_content = self._process_content_source(
                    session, 
                    content_item,
                    'article',
                    email_id,
                    title,
                    datetime.now()
                )
                
                if processed_content:
                    logger.info(f"Successfully processed content from URL: {url}")
                else:
                    logger.warning(f"Failed to process content from URL: {url}")
        
        except Exception as e:
            logger.error(f"Error processing crawled content from {url}: {e}", exc_info=True)

def load_config():
    """Load configuration from YAML file."""
    config_path = os.path.join(project_root, 'config', 'config.yaml')
    
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def ensure_summarizable_structure(content_dict):
    """
    Ensure the content dictionary has the proper structure for summarization.
    The summarizer expects content in an email_content dictionary.
    """
    if not isinstance(content_dict, dict):
        return content_dict
        
    # If there's no email_content but there is content, create the structure
    if 'email_content' not in content_dict and 'content' in content_dict:
        content_dict['email_content'] = {
            'content': content_dict['content'],
            'content_type': content_dict.get('content_type', 'text')
        }
        logger.debug("Added email_content structure for summarizer compatibility")
    
    return content_dict

def run_periodic_fetch():
    """Run the periodic fetch and process."""
    # Load configuration
    config = load_config()
    
    # Check if periodic fetching is enabled
    if not config['email'].get('periodic_fetch', False):
        logger.info("Periodic fetching is disabled in config")
        return
    
    try:
        # Create and run the fetcher
        fetcher = PeriodicFetcher(config)
        fetcher.fetch_and_process()
        
        logger.info("Periodic fetch and process completed")
    except Exception as e:
        logger.error(f"Error in periodic fetcher: {e}", exc_info=True)
        # We don't want to crash the scheduler, so just log the error

def force_process_all_emails():
    """Force process all unread emails, ignoring if they were previously processed."""
    # Load configuration
    config = load_config()
    
    # Create fetcher
    fetcher = PeriodicFetcher(config)
    
    # Use the raw fetch method to get all unread emails
    logger.info("Forcing fetch and processing of all unread emails, regardless of processed status...")
    emails = fetcher.email_fetcher.fetch_raw_unread_emails()
    
    if not emails:
        logger.info("No unread emails found to process")
        return
    
    logger.info(f"Found {len(emails)} unread emails to process")
    
    # Process the emails - one at a time to avoid database contention
    successfully_processed = []
    
    for idx, email in enumerate(emails):
        # Create a new session for each email
        session = get_session(fetcher.db_path)
        try:
            logger.info(f"Force processing email {idx+1}/{len(emails)}: {email['subject']}")
            
            # Process this single email
            processed = process_single_email(session, email, fetcher)
            if processed:
                successfully_processed.append(email)
                
            # Commit the transaction
            session.commit()
        except Exception as e:
            logger.error(f"Error force processing email {email['subject']}: {e}", exc_info=True)
            if hasattr(session, 'rollback'):
                session.rollback()
        finally:
            # Always close the session
            session.close()
    
    logger.info(f"Successfully force processed {len(successfully_processed)} emails")
    
    # Mark emails as read in Gmail if configured
    if successfully_processed and config['email'].get('mark_read_after_force_process', True):
        fetcher.email_fetcher.mark_emails_as_processed(successfully_processed)
        logger.info(f"Marked {len(successfully_processed)} emails as read in Gmail")
    
    logger.info("Force processing completed")

def process_single_email(session, email, fetcher):
    """Process a single email with proper transaction handling for force processing."""
    try:
        # Check if this is a forwarded email and flag it
        is_forwarded = email['subject'].startswith('Fwd:')
        if is_forwarded:
            logger.info(f"Detected forwarded email: {email['subject']}")
            email['is_forwarded'] = True
        
        # Create a fresh email record
        email_record = fetcher._mark_email_as_processed_in_db(session, email)
        email['db_id'] = email_record.id
        logger.info(f"Created database record for email, ID: {email_record.id}")
        
        # Parse email content
        parsed_content = fetcher.email_parser.parse(email)
        if not parsed_content:
            logger.warning(f"No content could be parsed from email: {email['subject']}")
            return False
        
        # Extract links
        links = fetcher.email_parser.extract_links(
            parsed_content.get('content', ''),
            parsed_content.get('content_type', 'html')
        )
        logger.info(f"Found {len(links)} links to crawl")
        
        # Crawl links
        crawled_content = fetcher.web_crawler.crawl(links)
        logger.info(f"Crawled {len(crawled_content)} links successfully")
        
        # Special handling for forwarded emails after they've been parsed
        if is_forwarded:
            # Check if we have content in email_contents table
            email_content_entries = session.query(EmailContent).filter_by(email_id=email_record.id).all()
            
            if email_content_entries:
                # Use the actual content from email_contents table
                main_content = email_content_entries[0].content
                content_type = email_content_entries[0].content_type
                
                # Extract links from the actual content rather than using database records
                links = fetcher.email_parser.extract_links(main_content, content_type)
                logger.info(f"Re-extracted {len(links)} links from the actual content")
                
                # Recrawl the newly extracted links
                if links:
                    logger.info(f"Recrawling {len(links)} links from actual forwarded email content")
                    crawled_content = fetcher.web_crawler.crawl(links)
                    logger.info(f"Recrawled {len(crawled_content)} links successfully")
                
                logger.info(f"Using actual content from email_contents for forced forwarded email: {email['subject']}, size: {len(main_content)} chars")
                
                # Create combined content with the actual email content
                combined_content = {
                    'email_content': {
                        'content': main_content,
                        'content_type': content_type,
                        'links': links
                    },
                    'crawled_content': crawled_content
                }
                
                # Process the content
                processed_combined = {
                    'source': email['subject'],
                    'date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                    'content': main_content,  # Use the actual content from email_contents
                    'links': links,
                    'articles': []
                }
                
                # Extract additional links from the email content if they exist
                # This helps with getting article URLs from forwarded newsletters
                if main_content and len(main_content) > 100:
                    try:
                        from bs4 import BeautifulSoup
                        import re
                        
                        # Check if we have HTML content
                        if '<a ' in main_content or '<A ' in main_content:
                            # Parse the HTML to extract links
                            soup = BeautifulSoup(main_content, 'html.parser')
                            additional_links = []
                            
                            for a_tag in soup.find_all('a', href=True):
                                href = a_tag['href']
                                text = a_tag.get_text().strip()
                                
                                # Skip empty or javascript links
                                if not href or href.startswith('javascript:') or href == '#':
                                    continue
                                    
                                # Skip image links
                                if href.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                                    continue
                                
                                # Skip tracking links
                                skip_domains = ['beehiiv.com', 'mailchimp.com', 'substack.com', 'mail.', 'unsubscribe', 'preferences']
                                if any(domain in href.lower() for domain in skip_domains):
                                    continue
                                
                                # Use text or href as title
                                title = text if text and len(text) > 1 else href
                                
                                # Ensure href is a full URL
                                if href.startswith('http'):
                                    additional_links.append({
                                        'url': href,
                                        'title': title,
                                        'source': 'forwarded_content'
                                    })
                            
                            # Add unique links to the existing links
                            existing_urls = {link.get('url') for link in links}
                            for link in additional_links:
                                if link['url'] not in existing_urls:
                                    links.append(link)
                                    existing_urls.add(link['url'])
                        
                        # Also try to find URLs in the text content
                        url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+'
                        found_urls = re.findall(url_pattern, main_content)
                        
                        for url in found_urls:
                            # Clean the URL
                            url = url.rstrip('.,;:\'\"!?)')
                            
                            # Normalize the URL
                            if url.startswith('www.'):
                                url = 'http://' + url
                                
                            # Skip tracking links and image URLs
                            skip_domains = ['beehiiv.com', 'mailchimp.com', 'substack.com', 'mail.', 'unsubscribe', 'preferences']
                            if any(domain in url.lower() for domain in skip_domains):
                                continue
                                
                            if url.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                                continue
                                
                            # Check if this URL is already in our links
                            if url not in existing_urls:
                                links.append({
                                    'url': url,
                                    'title': url,
                                    'source': 'regex_extracted'
                                })
                                existing_urls.add(url)
                    except Exception as e:
                        logger.warning(f"Error extracting additional links from forwarded content: {e}")
                
                # Update processed_combined with possibly enhanced links
                processed_combined['links'] = links
                
                # Update crawled articles
                if crawled_content:
                    articles = []
                    for item in crawled_content:
                        articles.append({
                            'title': item.get('title', ''),
                            'url': item.get('url', ''),
                            'content': item.get('clean_content', '')
                        })
                    processed_combined['articles'] = articles
                
                # Generate a unique hash for this forced processing
                content_hash = f"force_{uuid.uuid4().hex}"
            else:
                # Fallback to regular processing if no content in email_contents
                combined_content = {
                    'email_content': parsed_content,
                    'crawled_content': crawled_content,
                }
                
                processed_combined = {
                    'source': email['subject'],
                    'date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                    'content': parsed_content.get('content', ''),
                    'links': links,
                    'articles': [],
                }
                
                # Update crawled articles
                if crawled_content:
                    articles = []
                    for item in crawled_content:
                        articles.append({
                            'title': item.get('title', ''),
                            'url': item.get('url', ''),
                            'content': item.get('clean_content', '')
                        })
                    processed_combined['articles'] = articles
                
                # Generate a unique hash for this forced processing
                content_hash = f"force_{uuid.uuid4().hex}"
        else:
            # Regular non-forwarded email processing
            combined_content = {
                'email_content': parsed_content,
                'crawled_content': crawled_content,
            }
            
            processed_combined = {
                'source': email['subject'],
                'date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                'content': parsed_content.get('content', ''),
                'links': links,
                'articles': [],
            }
            
            # Update crawled articles
            if crawled_content:
                articles = []
                for item in crawled_content:
                    articles.append({
                        'title': item.get('title', ''),
                        'url': item.get('url', ''),
                        'content': item.get('clean_content', '')
                    })
                processed_combined['articles'] = articles
            
            # Generate a unique hash for this forced processing
            content_hash = f"force_{uuid.uuid4().hex}"
        
        # Fix structure for summarizer compatibility
        processed_combined = ensure_summarizable_structure(processed_combined)
        
        # Create metadata
        metadata = {
            'email_subject': email['subject'],
            'email_sender': email['sender'],
            'email_date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
            'num_links': len(links),
            'num_crawled': len(crawled_content),
            'force_processed': True,
            'is_forwarded': is_forwarded
        }
        
        # Create processed content entry
        processed_content = ProcessedContent(
            content_hash=content_hash,
            email_id=email_record.id,
            source=email['subject'],
            content_type='combined',
            processed_content=json_serialize(processed_combined),
            date_processed=datetime.now(),
            is_summarized=False
        )
        
        session.add(processed_content)
        session.flush()
        logger.info(f"Stored forced processed content for email: {email['subject']} with ID: {processed_content.id}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing single email {email['subject']} in force mode: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    run_periodic_fetch() 