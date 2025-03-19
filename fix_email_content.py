#!/usr/bin/env python3
"""
Fix Email Content Processing

This script updates the content in the processed_content entries
by using the actual content from the email_contents table.
This fixes issues where processed_content entries have empty or very short content.
"""

import os
import sys
import json
import logging
from datetime import datetime

# Set up the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'fix_email_content.log'))
    ]
)
logger = logging.getLogger(__name__)

# Try to import required modules
try:
    from src.database.models import get_session, ProcessedContent, ProcessedEmail, EmailContent
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    sys.exit(1)

def json_serialize(obj):
    """Serialize object to JSON with datetime handling."""
    class DateTimeEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return super().default(obj)
    return json.dumps(obj, cls=DateTimeEncoder)

def json_deserialize(json_str):
    """Deserialize JSON string back to object."""
    try:
        return json.loads(json_str)
    except:
        return {}

def fix_email_content():
    """Fix the processed_content entries by updating them with content from email_contents."""
    print("\nLetterMonstr - Fix Email Content Processing")
    print("=======================================\n")
    
    try:
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Get all processed content
            processed_content_entries = session.query(ProcessedContent).all()
            
            if not processed_content_entries:
                print("No processed content found in the database.")
                return
            
            print(f"Found {len(processed_content_entries)} processed content entries.")
            
            # Direct approach - treat all entries as potentially problematic
            empty_entries = processed_content_entries
            print(f"Will check and fix all {len(empty_entries)} entries, regardless of content length.")
            
            # Ask for confirmation
            confirmation = input(f"Do you want to update all {len(empty_entries)} entries with content from email_contents? (y/n): ")
            if confirmation.lower() != 'y':
                print("Operation cancelled by user.")
                return
            
            # Fix each entry
            fixed_count = 0
            unfixable_count = 0
            
            for entry in empty_entries:
                try:
                    # Skip entries without an email_id
                    if not entry.email_id:
                        logger.warning(f"Entry {entry.id} has no associated email, skipping.")
                        unfixable_count += 1
                        continue
                    
                    # Find email content in email_contents table
                    email_content = session.query(EmailContent).filter_by(email_id=entry.email_id).first()
                    
                    if not email_content:
                        logger.warning(f"No content found in email_contents for email_id {entry.email_id}, skipping entry {entry.id}.")
                        unfixable_count += 1
                        continue
                    
                    # Attempt to get the current content length before modification
                    try:
                        processed_content_dict = json_deserialize(entry.processed_content)
                        original_content = processed_content_dict.get('content', '')
                        original_length = len(original_content) if isinstance(original_content, str) else 0
                    except:
                        original_length = 0
                    
                    # Get the raw content dict
                    try:
                        raw_content_dict = json_deserialize(entry.raw_content)
                    except:
                        raw_content_dict = {'email_content': {}}
                    
                    # Get the processed content dict
                    try:
                        processed_content_dict = json_deserialize(entry.processed_content)
                    except:
                        processed_content_dict = {'content': '', 'links': []}
                    
                    # Update the content in the processed_content dict
                    processed_content_dict['content'] = email_content.content
                    
                    # Update the raw content with the email content
                    if 'email_content' in raw_content_dict:
                        if isinstance(raw_content_dict['email_content'], dict):
                            raw_content_dict['email_content']['content'] = email_content.content
                        else:
                            raw_content_dict['email_content'] = {
                                'content': email_content.content,
                                'content_type': 'html',
                                'links': []
                            }
                    else:
                        raw_content_dict['email_content'] = {
                            'content': email_content.content,
                            'content_type': 'html',
                            'links': []
                        }
                    
                    # Serialize back to JSON
                    entry.processed_content = json_serialize(processed_content_dict)
                    entry.raw_content = json_serialize(raw_content_dict)
                    
                    # Mark as modified
                    fixed_count += 1
                    new_length = len(email_content.content) if email_content.content else 0
                    logger.info(f"Fixed content for entry {entry.id}, email_id {entry.email_id}, content length: {original_length} -> {new_length}")
                    print(f"Entry {entry.id}: Content length before:{original_length}, after:{new_length}")
                except Exception as e:
                    logger.error(f"Error fixing content for entry {entry.id}: {e}", exc_info=True)
                    print(f"Error fixing entry {entry.id}: {str(e)}")
                    unfixable_count += 1
            
            # Commit changes
            session.commit()
            print(f"\nSuccessfully fixed {fixed_count} entries with actual email content.")
            if unfixable_count > 0:
                print(f"Could not fix {unfixable_count} entries (no associated email content found).")
            
            # Reset summarized status
            confirmation = input("\nDo you want to mark all content as unsummarized to ensure it gets included in the next summary? (y/n): ")
            if confirmation.lower() == 'y':
                # Update all content to be unsummarized
                updated = session.query(ProcessedContent).update({ProcessedContent.summarized: False})
                session.commit()
                print(f"Marked {updated} entries as unsummarized.")
            
        except Exception as e:
            logger.error(f"Error fixing email content: {e}", exc_info=True)
            session.rollback()
            print(f"\nError: {str(e)}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error initializing components: {e}", exc_info=True)
        print(f"\nError: {str(e)}")

if __name__ == "__main__":
    fix_email_content() 