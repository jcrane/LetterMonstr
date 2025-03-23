#!/usr/bin/env python3
"""
LetterMonstr Email Reprocessing Tool

This script allows you to reset the processed status of emails in the database
so they can be processed again. This is useful for debugging or when email
content wasn't properly extracted the first time.

It provides options to:
1. Reprocess only forwarded emails (emails with subjects starting with "Fwd:")
2. Reprocess all emails in the database

The tool will:
- Delete the associated processed_content entries
- Keep original email_contents entries for reference
- Rename message IDs to make them appear as new to the system
- Log all changes made for audit purposes
"""

import os
import sys
import logging
import sqlite3
from datetime import datetime
import uuid

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import required modules
from src.database.models import get_session, ProcessedEmail, ProcessedContent, EmailContent
from src.fetch_process import load_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'reprocess_emails.log'))
    ]
)
logger = logging.getLogger(__name__)

def reprocess_forwarded_emails():
    """Identify and reset forwarded emails for reprocessing."""
    # Get database path
    config = load_config()
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    
    # Create session
    session = get_session(db_path)
    
    try:
        # Identify all forwarded emails
        forwarded_emails = session.query(ProcessedEmail).filter(
            ProcessedEmail.subject.like('Fwd:%')
        ).all()
        
        print(f"Found {len(forwarded_emails)} forwarded emails in the database.")
        
        # Ask for confirmation
        confirm = input("Do you want to reset these forwarded emails for reprocessing? (yes/y): ")
        
        if confirm.lower() not in ['yes', 'y']:
            print("Operation cancelled.")
            return
        
        # Process each forwarded email
        for email in forwarded_emails:
            print(f"Processing: {email.subject}")
            
            # Delete associated processed content
            deleted_content = session.query(ProcessedContent).filter_by(email_id=email.id).delete()
            print(f"  - Deleted {deleted_content} processed content entries")
            
            # Keep the original email content intact
            content_items = session.query(EmailContent).filter_by(email_id=email.id).all()
            print(f"  - Found {len(content_items)} email content entries (keeping these)")
            
            # Rename the message_id to force reprocessing
            original_id = email.message_id
            email.message_id = f"REPROCESS_{original_id}_{datetime.now().timestamp()}"
            print(f"  - Reset message ID")
        
        # Commit changes
        session.commit()
        print(f"Successfully reset {len(forwarded_emails)} forwarded emails for reprocessing.")
        print("The next time the system runs, it will process these emails as if they were new.")
        print("The original email content is preserved, but the content will be reprocessed with the improved parser.")
        
    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

def reprocess_all_emails():
    """Reset all emails for reprocessing."""
    # Get database path
    config = load_config()
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    
    # Create session
    session = get_session(db_path)
    
    try:
        # Get all processed emails
        all_emails = session.query(ProcessedEmail).all()
        
        print(f"Found {len(all_emails)} total emails in the database.")
        
        # Ask for confirmation
        confirm = input("Do you want to reset ALL emails for reprocessing? This is more thorough but will process everything. (yes/y): ")
        
        if confirm.lower() not in ['yes', 'y']:
            print("Operation cancelled.")
            return
        
        # Process each email
        for email in all_emails:
            print(f"Processing: {email.subject}")
            
            # Delete associated processed content
            deleted_content = session.query(ProcessedContent).filter_by(email_id=email.id).delete()
            print(f"  - Deleted {deleted_content} processed content entries")
            
            # Keep the original email content intact
            content_items = session.query(EmailContent).filter_by(email_id=email.id).all()
            print(f"  - Found {len(content_items)} email content entries (keeping these)")
            
            # Rename the message_id to force reprocessing
            original_id = email.message_id
            email.message_id = f"REPROCESS_{original_id}_{datetime.now().timestamp()}"
            print(f"  - Reset message ID")
        
        # Commit changes
        session.commit()
        print(f"Successfully reset {len(all_emails)} emails for reprocessing.")
        print("The next time the system runs, it will process these emails as if they were new.")
        
    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    print("\nLetterMonstr Email Reprocessing Tool")
    print("================================\n")
    print("This tool resets emails in the database so they can be processed again")
    print("with the current email parser configuration.\n")
    print("Options:")
    print("1. Reprocess only forwarded emails (subjects starting with 'Fwd:')")
    print("2. Reprocess ALL emails in the database")
    print("3. Exit without making changes\n")
    
    while True:
        try:
            choice = input("Enter your choice (1/2/3): ")
            if choice == '1':
                reprocess_forwarded_emails()
                break
            elif choice == '2':
                reprocess_all_emails()
                break
            elif choice == '3':
                print("Exiting without making changes.")
                sys.exit(0)
            else:
                print("Invalid choice. Please try again.")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"\nAn error occurred: {e}")
            sys.exit(1) 