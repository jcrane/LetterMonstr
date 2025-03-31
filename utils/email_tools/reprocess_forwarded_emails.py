#!/usr/bin/env python3
"""
Reprocess Forwarded Emails

This script identifies all forwarded emails in the database, deletes their associated
processed content entries, and renames their message_ids so they will be reprocessed
with the improved email parser.
"""

import os
import sys
from datetime import datetime
import logging

# Fix path to properly add the project root
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # Go up two levels to the project root
sys.path.insert(0, project_root)

# Import required modules
from src.database.models import get_session, ProcessedEmail, ProcessedContent, EmailContent

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def reprocess_forwarded_emails():
    """Identify and reset forwarded emails for reprocessing."""
    # Get database path
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
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
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
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

def reprocess_short_content_emails():
    """Reset emails with very short content for reprocessing."""
    # Get database path
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
    # Create session
    session = get_session(db_path)
    
    try:
        # First gather emails with very short content
        short_content_entries = session.query(ProcessedContent).filter(
            ProcessedContent.processed_content.like('%Very short content%') |
            ProcessedContent.processed_content.like('%No content extracted%') |
            ProcessedContent.processed_content.like('%Original email may have had limited content%')
        ).all()
        
        # Build a list of email IDs to reprocess
        email_ids = set()
        for entry in short_content_entries:
            if entry.email_id:
                email_ids.add(entry.email_id)
        
        # Get the actual email objects
        emails_to_reprocess = session.query(ProcessedEmail).filter(
            ProcessedEmail.id.in_(email_ids)
        ).all()
        
        print(f"Found {len(emails_to_reprocess)} emails with very short content.")
        
        # Ask for confirmation
        confirm = input("Do you want to reset these emails for reprocessing? (yes/y): ")
        
        if confirm.lower() not in ['yes', 'y']:
            print("Operation cancelled.")
            return
        
        # Process each problem email
        for email in emails_to_reprocess:
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
        print(f"Successfully reset {len(emails_to_reprocess)} emails for reprocessing.")
        print("The next time the system runs, it will process these emails with improved parsing.")
        
    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

def reprocess_specific_email():
    """Find and reprocess a specific problematic email by subject pattern."""
    # Get database path
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
    # Create session
    session = get_session(db_path)
    
    print("\nReprocess emails by subject pattern")
    print("-----------------------------------")
    
    # Ask the user for a subject pattern to search
    subject_pattern = input("Enter a subject pattern to search for (e.g. 'New AI Risk Curve' or 'emoji'): ")
    
    if not subject_pattern:
        print("No search pattern provided. Operation cancelled.")
        return
    
    # Query for emails matching the pattern
    emails = session.query(ProcessedEmail).filter(
        ProcessedEmail.subject.like(f'%{subject_pattern}%')
    ).all()
    
    if not emails:
        print(f"No emails found with subject pattern: '{subject_pattern}'")
        return
    
    print(f"Found {len(emails)} emails matching the subject pattern:")
    for email in emails:
        print(f"  - ID: {email.id}, Subject: {email.subject}, Processed: {email.date_processed}")
    
    proceed = input("\nDo you want to reset these emails for reprocessing? (y/n): ")
    if proceed.lower() != 'y':
        print("Operation cancelled.")
        return
    
    # Reset each matching email
    reset_count = 0
    for email in emails:
        # Delete associated processed content
        content_entries = session.query(ProcessedContent).filter_by(email_id=email.id).all()
        for content in content_entries:
            print(f"Deleting ProcessedContent entry {content.id} for email: {email.subject}")
            session.delete(content)
        
        # Keep EmailContent entries as they contain the original email data
        email_contents = session.query(EmailContent).filter_by(email_id=email.id).all()
        print(f"Keeping {len(email_contents)} email content entries for email: {email.subject}")
        
        # Rename the message_id to force reprocessing
        old_message_id = email.message_id
        email.message_id = old_message_id + "_reprocessed_" + datetime.now().strftime("%Y%m%d%H%M%S")
        print(f"Resetting message ID from {old_message_id} to {email.message_id}")
        
        reset_count += 1
    
    session.commit()
    print(f"\nSuccessfully reset {reset_count} emails for reprocessing.")
    print("The next time the system runs, it will process these emails with the improved parser.")
    print("The original email content is preserved in the EmailContent table.")

if __name__ == "__main__":
    print("===============================================")
    print("Reprocess Emails Tool")
    print("===============================================")
    print("This script identifies emails in the database that need to be")
    print("reprocessed with the improved email parser.")
    print()
    print("Options:")
    print("1: Reprocess only forwarded emails (Fwd: in subject)")
    print("2: Reprocess all emails")
    print("3: Reprocess only emails with very short content")
    print("4: Reprocess emails by subject pattern")
    print("0: Exit")
    print()
    
    choice = input("Enter your choice (1/2/3/4/0): ")
    
    if choice == "1":
        reprocess_forwarded_emails()
    elif choice == "2":
        reprocess_all_emails()
    elif choice == "3":
        reprocess_short_content_emails()
    elif choice == "4":
        reprocess_specific_email()
    else:
        print("Exiting without making changes.") 