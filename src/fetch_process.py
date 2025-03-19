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
    """Serialize object to JSON with datetime handling."""
    return json.dumps(obj, cls=DateTimeEncoder)

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
            # Check if this is a forwarded email and flag it
            is_forwarded = email['subject'].startswith('Fwd:')
            if is_forwarded:
                logger.info(f"Detected forwarded email: {email['subject']}")
                # Add a flag to the email data for the parser to use
                email['is_forwarded'] = True
                
                # Pre-create the email record for forwarded emails to ensure we have an ID
                email_record = self._mark_email_as_processed_in_db(session, email)
                # Add the DB ID to the email data for the parser to use
                email['db_id'] = email_record.id
                logger.info(f"Pre-created database record for forwarded email, ID: {email_record.id}")
            
            # Parse email content
            parsed_content = self.email_parser.parse(email)
            
            if not parsed_content:
                logger.warning(f"No content could be parsed from email: {email['subject']}")
                # Try to extract at least something from the raw email content instead of using a minimal placeholder
                if is_forwarded:
                    logger.info(f"Attempting to extract raw content for forwarded email: {email['subject']}")
                    raw_content = email.get('content', {})
                    
                    # Check if we have any HTML or text content in the raw content
                    html_content = raw_content.get('html', '')
                    text_content = raw_content.get('text', '')
                    
                    if len(html_content) > 200:
                        logger.info(f"Using raw HTML content from email, length: {len(html_content)}")
                        parsed_content = {
                            'id': None,
                            'content': html_content,
                            'content_type': 'html',
                            'links': []
                        }
                    elif len(text_content) > 200:
                        logger.info(f"Using raw text content from email, length: {len(text_content)}")
                        parsed_content = {
                            'id': None,
                            'content': text_content,
                            'content_type': 'text',
                            'links': []
                        }
                    else:
                        # Only as a last resort, use the placeholder
                        logger.warning(f"No usable content found, using placeholder for forwarded email: {email['subject']}")
                        parsed_content = {
                            'id': None,
                            'content': f"[Forwarded email: {email['subject']}]",
                            'content_type': 'text',
                            'links': []
                        }
                else:
                    return False
            
            # Extract and crawl links
            links = self.email_parser.extract_links(
                parsed_content.get('content', ''),
                parsed_content.get('content_type', 'html')
            )
            logger.info(f"Found {len(links)} links to crawl")
            
            # Crawl links
            crawled_content = self.web_crawler.crawl(links)
            logger.info(f"Crawled {len(crawled_content)} links successfully")
            
            # Get content from existing email record in the database
            email_record = None
            if is_forwarded and 'db_id' in email:
                # For forwarded emails, try to get the record we created earlier
                email_record = session.query(ProcessedEmail).get(email.get('db_id'))
                logger.info(f"Using existing DB record for forwarded email: {email['subject']}")
                
                # Special handling for forwarded emails - check if we have content in email_contents
                email_content_entries = session.query(EmailContent).filter_by(email_id=email_record.id).all()
                
                if email_content_entries:
                    # Use the actual content from email_contents table
                    main_content = email_content_entries[0].content
                    content_type = email_content_entries[0].content_type
                    
                    # Extract links from the actual content rather than using database records
                    links = self.email_parser.extract_links(main_content, content_type)
                    logger.info(f"Re-extracted {len(links)} links from the actual content")
                    
                    # Recrawl the newly extracted links
                    if links:
                        logger.info(f"Recrawling {len(links)} links from actual forwarded email content")
                        crawled_content = self.web_crawler.crawl(links)
                        logger.info(f"Recrawled {len(crawled_content)} links successfully")
                    
                    logger.info(f"Using actual content from email_contents for forwarded email: {email['subject']}, size: {len(main_content)} chars")
                    
                    # Create combined content with the actual email content
                    combined_content = {
                        'email_content': {
                            'content': main_content,
                            'content_type': content_type,
                            'links': links
                        },
                        'crawled_content': crawled_content
                    }
                    
                    # Process the content using the actual email content
                    processed_combined = {
                        'source': email['subject'],
                        'date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                        'content': main_content,  # Use the actual content from email_contents
                        'links': links,
                        'articles': []
                    }
                    
                    # Update with crawled content if any
                    if crawled_content:
                        articles = []
                        for item in crawled_content:
                            articles.append({
                                'title': item.get('title', ''),
                                'url': item.get('url', ''),
                                'content': item.get('clean_content', '')
                            })
                        processed_combined['articles'] = articles
                    
                    # Generate content hash using the actual content
                    content_hash = self._generate_content_hash(processed_combined)
                    
                    # Fix structure for summarizer compatibility
                    processed_combined = ensure_summarizable_structure(processed_combined)
                    
                    # Skip the regular processing and go directly to creating the ProcessedContent entry
                    logger.info(f"Using enhanced forwarded email processing for: {email['subject']}")
                    metadata = {
                        'email_subject': email['subject'],
                        'email_sender': email['sender'],
                        'email_date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                        'num_links': len(links),
                        'num_crawled': len(crawled_content),
                        'enhanced_processing': True
                    }
                    
                    # Create the ProcessedContent entry with the actual content
                    processed_content = ProcessedContent(
                        content_hash=content_hash,
                        email_id=email_record.id,
                        source=email['subject'],
                        content_type='combined',
                        raw_content=json_serialize(combined_content),
                        processed_content=json_serialize(processed_combined),
                        content_metadata=json_serialize(metadata),
                        date_processed=datetime.now(),
                        summarized=False
                    )
                    
                    session.add(processed_content)
                    session.flush()  # Flush to get the ID
                    logger.info(f"Stored enhanced processed content for forwarded email: {email['subject']} with ID: {processed_content.id}")
                    return True
            
            if not email_record:
                # Create or update the email record in the database
                email_record = self._mark_email_as_processed_in_db(session, email)
                logger.debug(f"Created/updated email record with ID: {email_record.id}")
            
            # Combine email content with crawled content
            combined_content = {
                'source': email['subject'],
                'email_content': parsed_content,
                'crawled_content': crawled_content,
                'date': email['date']
            }
            
            # Apply initial processing to prepare for later deduplication
            try:
                # Use the correct method name
                processed_combined = self.content_processor.process_and_deduplicate([combined_content])
                # The method returns a list, so take the first item if available
                if processed_combined and len(processed_combined) > 0:
                    processed_combined = processed_combined[0]
                else:
                    # Fallback if processing returns empty
                    processed_combined = combined_content
                    logger.warning("Content processing returned empty result, using raw content")
            except Exception as e:
                logger.error(f"Error during content processing: {e}", exc_info=True)
                # Use the raw content as fallback
                processed_combined = combined_content
            
            # Generate content hash for deduplication
            content_hash = self._generate_content_hash(processed_combined)
            
            # Fix structure for summarizer compatibility
            processed_combined = ensure_summarizable_structure(processed_combined)
            
            # Check if we already have this content
            existing = session.query(ProcessedContent).filter_by(content_hash=content_hash).first()
            
            if existing:
                logger.info(f"Content with hash {content_hash} already exists in database")
                return True
            
            # Store processed content in database
            metadata = {
                'email_subject': email['subject'],
                'email_sender': email['sender'],
                'email_date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                'num_links': len(links),
                'num_crawled': len(crawled_content)
            }
            
            # Create the processed content record
            processed_content = ProcessedContent(
                content_hash=content_hash,
                email_id=email_record.id,  # Set email_id directly
                source=email['subject'],
                content_type='combined',
                raw_content=json_serialize(combined_content),
                processed_content=json_serialize(processed_combined),
                content_metadata=json_serialize(metadata),
                date_processed=datetime.now(),
                summarized=False
            )
            
            session.add(processed_content)
            session.flush()  # Flush to get the ID
            logger.info(f"Stored processed content for email: {email['subject']} with ID: {processed_content.id}")
            return True
        
        except Exception as e:
            logger.error(f"Error processing single email {email['subject']}: {e}", exc_info=True)
            return False
    
    def _mark_email_as_processed_in_db(self, session, email):
        """Mark an email as processed in the database without marking it as read in Gmail."""
        try:
            # Check if the email is already in the database
            existing = None
            if 'message_id' in email:
                existing = session.query(ProcessedEmail).filter_by(message_id=email['message_id']).first()
            
            if existing:
                # If it exists, update the processed date
                existing.date_processed = datetime.now()
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
            logger.error(f"Error marking email as processed in database: {e}", exc_info=True)
            raise

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
    
    # Create and run the fetcher
    fetcher = PeriodicFetcher(config)
    fetcher.fetch_and_process()
    
    logger.info("Periodic fetch and process completed")

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
            raw_content=json_serialize(combined_content),
            processed_content=json_serialize(processed_combined),
            content_metadata=json_serialize(metadata),
            date_processed=datetime.now(),
            summarized=False
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