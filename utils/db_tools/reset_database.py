#!/usr/bin/env python3
"""
Reset LetterMonstr Database

This script completely resets the LetterMonstr database and status files to start fresh.
"""

import os
import sys
import json
import shutil
import logging
from datetime import datetime

# Fix path to properly add the project root
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))  # Go up two levels to the project root
sys.path.insert(0, project_root)

# Import database models
from src.database.models import init_db, Base
# We don't need load_config since we're directly specifying the database path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def reset_database():
    """Reset the database and related files."""
    # Define database path and status file path
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    status_file = os.path.join(project_root, 'data', 'fetch_status.json')
    
    # Ensure data directory exists
    os.makedirs(os.path.join(project_root, 'data'), exist_ok=True)
    
    # Ask for confirmation
    print("\n⚠️ WARNING: This will delete all data in the LetterMonstr database! ⚠️")
    print("All email processing history, content, and summaries will be permanently deleted.")
    print("This operation cannot be undone unless you have a backup.")
    confirm = input("\nDo you really want to reset the database? Type 'RESET' to confirm: ")
    
    if confirm != 'RESET':
        print("Operation cancelled.")
        return
    
    try:
        # Backup the current database
        if os.path.exists(db_path):
            backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copy2(db_path, backup_path)
            logger.info(f"Backed up existing database to {backup_path}")
            
            # Delete the current database
            os.remove(db_path)
            logger.info(f"Deleted existing database at {db_path}")
        
        # Reset fetch status file
        with open(status_file, 'w') as f:
            # Set last fetch to None or a date far in the past
            status = {"last_fetch": None}
            json.dump(status, f)
            logger.info(f"Reset fetch status file at {status_file}")
        
        # Initialize a new empty database
        Session = init_db(db_path)
        logger.info(f"Created new empty database at {db_path}")
        
        print("\n✅ Database reset successfully!")
        print("You can now run LetterMonstr to start fresh.")
        print("The existing database was backed up in case you need to restore it.")
        
    except Exception as e:
        logger.error(f"Error resetting database: {e}", exc_info=True)
        print(f"\n❌ Error resetting database: {e}")
        
if __name__ == "__main__":
    print("=== LetterMonstr Database Reset Tool ===")
    reset_database() 