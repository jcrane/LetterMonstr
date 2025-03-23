#!/usr/bin/env python3
"""
Reset the processed status of emails so they can be processed again.

This is a one-time fix to help migrate from the old system (which only marked emails as processed)
to the new system (which stores their content in the ProcessedContent table).
"""

import os
import sys
from datetime import datetime

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import database models
from src.database.models import get_session, ProcessedEmail
from src.fetch_process import load_config

def reset_processed_status():
    """Reset the processed status of emails in the database."""
    # Get database path
    config = load_config()
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    
    # Create session
    session = get_session(db_path)
    
    try:
        # Get all processed emails
        processed_emails = session.query(ProcessedEmail).all()
        
        print(f"Found {len(processed_emails)} processed emails in the database.")
        
        # Ask for confirmation
        confirm = input("Do you want to reset the processed status of ALL emails? (yes/y): ")
        
        if confirm.lower() not in ['yes', 'y']:
            print("Operation cancelled.")
            return
        
        # Reset processed status by renaming message_ids
        # This will make the system think these are new emails
        for email in processed_emails:
            # Backup the original message_id
            original_id = email.message_id
            # Set a new message_id that won't match what's in Gmail
            email.message_id = f"RESET_{original_id}_{datetime.now().timestamp()}"
            print(f"Reset: {email.subject}")
        
        # Commit changes
        session.commit()
        print(f"Successfully reset the processed status of {len(processed_emails)} emails.")
        print("The next time the system runs, it will process these emails as if they were new.")
        
    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    print("This script will reset the processed status of emails in the database.")
    print("WARNING: This will cause all emails to be processed again.")
    print()
    
    reset_processed_status() 