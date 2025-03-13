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

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Import required modules
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import components
from src.mail_handling.fetcher import EmailFetcher
from src.mail_handling.parser import EmailParser
from src.crawl.crawler import WebCrawler
from src.summarize.processor import ContentProcessor
from src.database.models import get_session, ProcessedEmail, ProcessedContent

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(project_root, 'data', 'lettermonstr_fetch.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
        if isinstance(content, dict):
            content_str = json.dumps(content, sort_keys=True)
        else:
            content_str = str(content)
        
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()
    
    def fetch_and_process(self):
        """Fetch new emails and process them without generating a summary."""
        logger.info("Starting periodic fetch and process...")
        
        try:
            # Fetch new emails
            emails = self.email_fetcher.fetch_new_emails()
            
            if not emails:
                logger.info("No new emails to process")
                return
            
            logger.info(f"Fetched {len(emails)} new emails")
            
            # Process each email
            session = get_session(self.db_path)
            
            try:
                # Track successfully processed emails
                successfully_processed = []
                
                for email in emails:
                    try:
                        logger.info(f"Processing email: {email['subject']}")
                        
                        # Check if this is a forwarded email and flag it
                        is_forwarded = email['subject'].startswith('Fwd:')
                        if is_forwarded:
                            logger.info(f"Detected forwarded email: {email['subject']}")
                            # Add a flag to the email data for the parser to use
                            email['is_forwarded'] = True
                        
                        # Parse email content
                        parsed_content = self.email_parser.parse(email)
                        
                        if not parsed_content:
                            logger.warning(f"No content could be parsed from email: {email['subject']}")
                            continue
                        
                        # Extract and crawl links
                        links = self.email_parser.extract_links(
                            parsed_content.get('content', ''),
                            parsed_content.get('content_type', 'html')
                        )
                        logger.info(f"Found {len(links)} links to crawl")
                        
                        # Crawl links
                        crawled_content = self.web_crawler.crawl(links)
                        logger.info(f"Crawled {len(crawled_content)} links successfully")
                        
                        # Combine email content with crawled content
                        combined_content = {
                            'source': email['subject'],
                            'email_content': parsed_content,
                            'crawled_content': crawled_content,
                            'date': email['date']
                        }
                        
                        # Apply initial processing to prepare for later deduplication
                        processed_combined = self.content_processor.preprocess_content(combined_content)
                        
                        # Generate content hash for deduplication
                        content_hash = self._generate_content_hash(processed_combined)
                        
                        # Check if we already have this content
                        existing = session.query(ProcessedContent).filter_by(content_hash=content_hash).first()
                        
                        if existing:
                            logger.info(f"Content with hash {content_hash} already exists in database")
                            # Mark email as processed but not read in Gmail
                            self._mark_email_as_processed_in_db(session, email)
                            successfully_processed.append(email)
                            continue
                        
                        # Store processed content in database
                        metadata = {
                            'email_subject': email['subject'],
                            'email_sender': email['sender'],
                            'email_date': email['date'].isoformat() if isinstance(email['date'], datetime) else email['date'],
                            'num_links': len(links),
                            'num_crawled': len(crawled_content)
                        }
                        
                        processed_content = ProcessedContent(
                            content_hash=content_hash,
                            email_id=None,  # Will be updated after email is stored
                            source=email['subject'],
                            content_type='combined',
                            raw_content=json.dumps(combined_content),
                            processed_content=json.dumps(processed_combined),
                            content_metadata=json.dumps(metadata),
                            date_processed=datetime.now(),
                            summarized=False
                        )
                        
                        session.add(processed_content)
                        session.flush()  # Flush to get the ID
                        
                        # Mark email as processed but not read in Gmail if enabled
                        email_record = self._mark_email_as_processed_in_db(session, email)
                        
                        # Update email_id in processed_content
                        processed_content.email_id = email_record.id
                        
                        logger.info(f"Stored processed content for email: {email['subject']}")
                        successfully_processed.append(email)
                        
                    except Exception as e:
                        logger.error(f"Error processing email {email['subject']}: {e}", exc_info=True)
                
                # Commit all changes
                session.commit()
                logger.info(f"Successfully processed {len(successfully_processed)} emails")
                
                # Mark emails as read in Gmail if configured to do so
                if not self.config['email'].get('mark_read_only_after_summary', True):
                    self.email_fetcher.mark_emails_as_processed(successfully_processed)
                    logger.info(f"Marked {len(successfully_processed)} emails as read in Gmail")
                else:
                    logger.info("Emails will remain unread in Gmail until summary is sent")
                
                # Update last fetch time
                self.status["last_fetch"] = datetime.now().isoformat()
                self._save_status()
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error during fetch and process: {e}", exc_info=True)
    
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

if __name__ == "__main__":
    run_periodic_fetch() 