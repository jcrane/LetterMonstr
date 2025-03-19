#!/usr/bin/env python3
"""
Fix Content Processing Issue

This script diagnoses and fixes the issue where emails are marked as processed
but their content is not being stored in the ProcessedContent table.
"""

import os
import sys
import json
import logging
from datetime import datetime

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import required modules
from src.database.models import get_session, ProcessedEmail, ProcessedContent, EmailContent
from src.fetch_process import load_config, PeriodicFetcher
from src.mail_handling.parser import EmailParser
from src.crawl.crawler import WebCrawler
from src.summarize.processor import ContentProcessor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Helper function for JSON serialization with datetime support
def json_dump_safe(obj):
    """Serialize object to JSON with datetime handling."""
    def json_serial(obj):
        """JSON serializer for objects not serializable by default json code."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    return json.dumps(obj, default=json_serial)

def fix_content_processing():
    """Fix the content processing issue in the database."""
    # Load configuration
    config = load_config()
    
    # Create DB session
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    
    # Create required objects
    email_parser = EmailParser()
    web_crawler = WebCrawler(config['content'])
    content_processor = ContentProcessor(config['content'])
    
    try:
        # Get emails that are processed but don't have corresponding content
        # This requires a left join with ProcessedContent to find those with no content
        processed_emails = session.query(ProcessedEmail).all()
        
        logger.info(f"Found {len(processed_emails)} processed emails in database")
        
        # Count how many have content
        emails_with_content = 0
        for email in processed_emails:
            # Check for any content linked to this email
            content_entries = session.query(ProcessedContent).filter_by(email_id=email.id).all()
            if content_entries:
                emails_with_content += 1
        
        logger.info(f"{emails_with_content} emails have content entries, {len(processed_emails) - emails_with_content} are missing content")
        
        if emails_with_content == len(processed_emails):
            logger.info("All emails have content entries, no action needed")
            return
        
        # Ask for confirmation
        confirm = input("Do you want to fix the content processing issue for emails missing content? (yes/y): ")
        
        if confirm.lower() not in ['yes', 'y']:
            logger.info("Operation cancelled")
            return
        
        # Create a fetcher instance to use its content hash generation method
        fetcher = PeriodicFetcher(config)
        
        # Process each email that doesn't have content
        fixed_count = 0
        for email in processed_emails:
            # Check if this email already has content
            content_entries = session.query(ProcessedContent).filter_by(email_id=email.id).all()
            if content_entries:
                logger.debug(f"Email {email.id} already has content entries, skipping")
                continue
            
            # Check if the email has raw content in the EmailContent table
            email_contents = session.query(EmailContent).filter_by(email_id=email.id).all()
            
            if not email_contents:
                logger.warning(f"Email {email.id} has no raw content in EmailContent table, cannot fix")
                continue
            
            logger.info(f"Processing email {email.id}: {email.subject}")
            
            # Extract HTML content
            html_content = None
            text_content = None
            
            for content in email_contents:
                if content.content_type == 'html':
                    html_content = content.content
                elif content.content_type == 'text':
                    text_content = content.content
            
            if not html_content and not text_content:
                logger.warning(f"Email {email.id} has no usable content, skipping")
                continue
            
            # Create a fake email object for the parser
            fake_email = {
                'subject': email.subject,
                'sender': email.sender,
                'date': email.date_received,
                'message_id': email.message_id,
                'is_forwarded': email.subject.startswith('Fwd:'),
                'db_id': email.id
            }
            
            # Fake parsed content since we already have the raw content
            parsed_content = {
                'id': email.id,
                'content': html_content or text_content,
                'content_type': 'html' if html_content else 'text',
                'links': []
            }
            
            # Extract links
            links = email_parser.extract_links(
                parsed_content.get('content', ''),
                parsed_content.get('content_type', 'html')
            )
            logger.info(f"Found {len(links)} links to crawl")
            
            # Crawl links
            crawled_content = web_crawler.crawl(links)
            logger.info(f"Crawled {len(crawled_content)} links successfully")
            
            # Combine email content with crawled content
            combined_content = {
                'source': email.subject,
                'email_content': parsed_content,
                'crawled_content': crawled_content,
                'date': email.date_received
            }
            
            # Process the content
            try:
                processed_combined = content_processor.process_and_deduplicate([combined_content])
                if processed_combined and len(processed_combined) > 0:
                    processed_combined = processed_combined[0]
                else:
                    processed_combined = combined_content
                    logger.warning("Content processing returned empty result, using raw content")
            except Exception as e:
                logger.error(f"Error during content processing: {e}", exc_info=True)
                processed_combined = combined_content
            
            # Generate content hash
            content_hash = fetcher._generate_content_hash(processed_combined)
            
            # Add "fix" to content hash to avoid duplication with regular processing
            fix_hash = f"fix_{content_hash}"
            
            # Store metadata
            metadata = {
                'email_subject': email.subject,
                'email_sender': email.sender,
                'email_date': email.date_received.isoformat() if hasattr(email.date_received, 'isoformat') else str(email.date_received),
                'num_links': len(links),
                'num_crawled': len(crawled_content),
                'fixed_content': True
            }
            
            # Create processed content entry
            processed_content = ProcessedContent(
                content_hash=fix_hash,
                email_id=email.id,
                source=email.subject,
                content_type='combined',
                raw_content=json_dump_safe(combined_content),
                processed_content=json_dump_safe(processed_combined),
                content_metadata=json_dump_safe(metadata),
                date_processed=datetime.now(),
                summarized=False
            )
            
            try:
                session.add(processed_content)
                session.flush()
                logger.info(f"Added missing content for email: {email.subject} with ID: {processed_content.id}")
                fixed_count += 1
            except Exception as e:
                logger.error(f"Error adding content for email {email.id}: {e}", exc_info=True)
                session.rollback()
        
        # Commit all changes
        session.commit()
        logger.info(f"Successfully fixed content for {fixed_count} emails")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()

def diagnose_database():
    """Diagnose the database state."""
    # Create DB session
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    
    try:
        # Count processed emails
        email_count = session.query(ProcessedEmail).count()
        content_count = session.query(ProcessedContent).count()
        
        print("\n=== DATABASE DIAGNOSIS ===")
        print(f"ProcessedEmail entries: {email_count}")
        print(f"ProcessedContent entries: {content_count}")
        
        if email_count > 0 and content_count == 0:
            print("\nDIAGNOSIS: Content processing is not working correctly.")
            print("Emails are being marked as processed but their content is not being stored.")
            print("This script will attempt to fix that by adding the missing content entries.")
            print("\nROOT CAUSE: The content processing code may have errors or the processed content isn't being saved correctly.")
            
        elif email_count > 0 and content_count > 0 and email_count > content_count:
            print(f"\nDIAGNOSIS: Some emails ({email_count - content_count}) are missing content entries.")
            
        else:
            print("\nDIAGNOSIS: The database appears to be in a normal state.")
            
    except Exception as e:
        print(f"Error diagnosing database: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    print("=== LetterMonstr Content Processing Fix Tool ===")
    print("This tool diagnoses and fixes issues with email content processing.")
    
    # First diagnose the database
    diagnose_database()
    
    # Ask if the user wants to proceed with fixing
    proceed = input("\nDo you want to proceed with the fixing process? (yes/y): ")
    
    if proceed.lower() in ['yes', 'y']:
        fix_content_processing()
    else:
        print("Operation cancelled.") 