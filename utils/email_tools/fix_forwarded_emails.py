#!/usr/bin/env python3
"""
Fix Forwarded Emails Content

This script directly extracts content from EmailContent records for forwarded emails
and updates the corresponding ProcessedContent entries with proper content.
"""

import os
import sys
import logging
import json
from datetime import datetime

# Fix path to properly add the project root
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # Go up two levels to the project root
sys.path.insert(0, project_root)

# Import database models
from src.database.models import get_session, ProcessedEmail, ProcessedContent, EmailContent
from src.mail_handling.parser import EmailParser
from src.summarize.processor import ContentProcessor

# Import from fetch_process.py
from src.fetch_process import load_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def get_db_path():
    """Get the path to the database."""
    return os.path.join(project_root, 'data', 'lettermonstr.db')

def json_serialize(obj):
    """Serialize to JSON, handling datetime objects."""
    def default_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    return json.dumps(obj, default=default_serializer)

def fix_forwarded_emails():
    """Fix forwarded emails by directly extracting content from email records."""
    db_path = get_db_path()
    session = get_session(db_path)
    
    try:
        # Get all forwarded emails
        forwarded_emails = session.query(ProcessedEmail).filter(
            ProcessedEmail.subject.like('Fwd:%')
        ).all()
        
        if not forwarded_emails:
            logger.info("No forwarded emails found in the database.")
            return
        
        logger.info(f"Found {len(forwarded_emails)} forwarded emails to fix.")
        
        # Create parser and content processor
        parser = EmailParser()
        config = load_config()
        content_processor = ContentProcessor(config['content'])
        
        # Process each forwarded email
        fixed_count = 0
        for email in forwarded_emails:
            logger.info(f"Processing email: {email.subject}")
            
            # Get the associated EmailContent entries
            email_content_entries = session.query(EmailContent).filter_by(email_id=email.id).all()
            
            if not email_content_entries:
                logger.warning(f"No content entries found for email {email.subject}.")
                continue
            
            # Get the ProcessedContent entries
            processed_content_entries = session.query(ProcessedContent).filter_by(email_id=email.id).all()
            
            if not processed_content_entries:
                logger.warning(f"No processed content entries found for email {email.subject}.")
                continue
            
            # Use the first EmailContent entry as the source
            email_content = email_content_entries[0]
            
            # Create an email_data dictionary for the parser
            email_data = {
                'subject': email.subject,
                'content': email_content.content,
                'content_type': email_content.content_type,
                'is_forwarded': True
            }
            
            # Extract content using the parser's extract_forwarded_content method
            extracted_content = parser._extract_forwarded_content(email_content.content)
            
            if not extracted_content or len(extracted_content) < 200:
                logger.warning(f"Failed to extract meaningful content for {email.subject}.")
                continue
            
            # Process the content
            processed_text = content_processor.clean_content(extracted_content, email_content.content_type)
            
            # Create a content object for the processor
            content_obj = {
                'source': email.subject,
                'content': processed_text,
                'date': email.date_received,
            }
            
            # Create processed content
            processed_items = content_processor.process_and_deduplicate([content_obj])
            
            if not processed_items:
                logger.warning(f"No processed content returned for {email.subject}")
                continue
            
            processed_item = processed_items[0]
            
            # Update the ProcessedContent entries
            for processed_content in processed_content_entries:
                # Update the processed_content field with the new content
                processed_content.processed_content = json_serialize(processed_item)
                
                logger.info(f"Updated ProcessedContent entry {processed_content.id} for email {email.subject}.")
                fixed_count += 1
            
            # Commit after each email
            session.commit()
        
        logger.info(f"Fixed {fixed_count} processed content entries for {len(forwarded_emails)} forwarded emails.")
    
    except Exception as e:
        logger.error(f"Error fixing forwarded emails: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    logger.info("Starting fix for forwarded emails...")
    fix_forwarded_emails()
    logger.info("Finished fixing forwarded emails.") 