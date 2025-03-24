#!/usr/bin/env python3
"""
Reset Processed Content Status

This script resets the summarized status of all processed content entries,
making them available for summary generation.
"""

import os
import sys
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
        logging.FileHandler(os.path.join('data', 'reset_content.log'))
    ]
)
logger = logging.getLogger(__name__)

try:
    from src.database.models import get_session, ProcessedContent
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    sys.exit(1)

def reset_processed_content():
    """Reset the summarized status of all processed content entries."""
    print("\nLetterMonstr - Reset Processed Content Status")
    print("=========================================\n")
    
    try:
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Get all processed content
            all_content = session.query(ProcessedContent).all()
            
            if not all_content:
                print("No processed content found in the database.")
                return
            
            print(f"Found {len(all_content)} processed content entries.\n")
            
            # Ask for confirmation
            confirmation = input("Do you want to reset the 'summarized' status of all content? (y/n): ")
            if confirmation.lower() != 'y':
                print("Operation cancelled by user.")
                return
            
            # Reset summarized status
            reset_count = 0
            for item in all_content:
                item.summarized = False
                reset_count += 1
            
            # Commit changes
            session.commit()
            print(f"\nSuccessfully reset {reset_count} content entries. They are now marked as unsummarized.")
            print("The next summary will include these content items.")
            
        except Exception as e:
            logger.error(f"Error resetting content status: {e}", exc_info=True)
            session.rollback()
            print(f"\nError: {str(e)}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error initializing components: {e}", exc_info=True)
        print(f"\nError: {str(e)}")

if __name__ == "__main__":
    reset_processed_content() 